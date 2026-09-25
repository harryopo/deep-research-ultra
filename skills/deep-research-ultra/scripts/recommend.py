"""
Deep Research Ultra v5.2 — 推荐度评分系统

基于调研报告格式最佳实践调研报告实现。

核心功能：
1. GitHubRecommender: 8 维推荐度评分（人气/活跃/维护/社区/文档/依赖/相关/生态）
2. PaperRecommender: 5 维推荐度评分（引用/时效/权威/h-index/相关）
3. 分组排序（旗舰≥10k / 主流1k-10k / 小众<1k 三组独立排序）
4. 意图识别权重调整（novel_approach 意图下降低人气权重，提升相关性权重）
5. 推荐等级（借鉴 ThoughtWorks Technology Radar 四环模型）

设计理念：
- star 数采用 log10 对数缩放，避免高星项目垄断评分
- 分组排序确保低星项目也有展示机会（"小众结果可借鉴"）
- 意图识别调整权重（novel_approach → 人气权重 0.05，相关性 0.35）
- 推荐等级四环：Adopt（采纳）/ Trial（试验）/ Assess（评估）/ Hold（谨慎）
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


# ============================================================
# 推荐度评分数据结构
# ============================================================

@dataclass
class RecommendationScore:
    """推荐度评分结果"""
    total_score: float                              # 总分（0-100）
    grade: str                                      # 推荐等级（Adopt/Trial/Assess/Hold）
    dimensions: Dict[str, float] = field(default_factory=dict)  # 各维度得分
    group: str = ''                                 # 分组（flagship/mainstream/niche）
    rank_in_group: int = 0                          # 组内排名
    intent_weighted: bool = False                   # 是否使用了意图权重
    recommendation_reason: str = ''                 # 推荐理由

    def to_dict(self) -> Dict:
        return {
            'total_score': round(self.total_score, 1),
            'grade': self.grade,
            'dimensions': {k: round(v, 1) for k, v in self.dimensions.items()},
            'group': self.group,
            'rank_in_group': self.rank_in_group,
            'intent_weighted': self.intent_weighted,
            'recommendation_reason': self.recommendation_reason,
        }


# ============================================================
# 意图权重配置
# ============================================================

INTENT_WEIGHTS = {
    # 意图类型: (popularity, activity, maintenance, community, docs, dependency, relevance, ecosystem)
    'default':       (0.15, 0.15, 0.15, 0.10, 0.10, 0.10, 0.15, 0.10),
    'novel_approach':(0.05, 0.15, 0.10, 0.10, 0.10, 0.05, 0.35, 0.10),
    'production_ready': (0.20, 0.20, 0.20, 0.10, 0.10, 0.10, 0.05, 0.05),
    'learning':      (0.10, 0.10, 0.10, 0.10, 0.20, 0.05, 0.25, 0.10),
    'comparison':    (0.15, 0.15, 0.15, 0.10, 0.10, 0.10, 0.15, 0.10),
}


# ============================================================
# GitHub 项目推荐度评分器
# ============================================================

class GitHubRecommender:
    """
    GitHub 项目推荐度评分器

    8 维评分模型（每维 0-100）：
    1. popularity（人气）: log10(stars+1) * 缩放系数
    2. activity（活跃度）: 最近 commit + push 时间 + release 频率
    3. maintenance（维护）: 是否归档 + issue 响应 + 最后更新时间
    4. community（社区）: contributors + forks + watchers
    5. docs（文档）: README 长度 + 是否有文档站
    6. dependency（依赖健康）: 依赖是否过时（如有数据）
    7. relevance（相关性）: 关键词匹配度 + topic 匹配
    8. ecosystem（生态）: 是否被其他高星项目引用

    分组策略：
    - flagship（旗舰）: stars >= 1000
    - mainstream（主流）: 100 <= stars < 1000
    - niche（小众）: stars < 100

    推荐等级（借鉴 Technology Radar 四环）：
    - Adopt（采纳）: 总分 >= 75
    - Trial（试验）: 总分 >= 55
    - Assess（评估）: 总分 >= 35
    - Hold（谨慎）: 总分 < 35
    """

    # 分组阈值
    FLAGSHIP_THRESHOLD = 1000
    MAINSTREAM_THRESHOLD = 100

    # 推荐等级阈值
    GRADE_ADOPT = 75
    GRADE_TRIAL = 55
    GRADE_ASSESS = 35

    def score(
        self,
        repo_data: Dict[str, Any],
        query: str = '',
        intent: str = 'default',
    ) -> RecommendationScore:
        """
        评分单个 GitHub 项目

        Args:
            repo_data: 仓库数据（来自 GitHubDeepSearchEngine._parse_repo 的 raw 字段）
            query: 原始查询关键词（用于相关性评分）
            intent: 查询意图（default/novel_approach/production_ready/learning/comparison）

        Returns:
            RecommendationScore 对象
        """
        weights = INTENT_WEIGHTS.get(intent, INTENT_WEIGHTS['default'])

        # 1. 人气（log10 对数缩放）
        stars = repo_data.get('stars', 0)
        popularity = min(100, math.log10(stars + 1) * 25)  # log10(10000)≈4 → 100分

        # 2. 活跃度
        activity = self._score_activity(repo_data)

        # 3. 维护状态
        maintenance = self._score_maintenance(repo_data)

        # 4. 社区
        forks = repo_data.get('forks', 0)
        watchers = repo_data.get('watchers', 0)
        community = min(100, math.log10(forks + 1) * 30 + math.log10(watchers + 1) * 20)

        # 5. 文档（从 description 推断）
        description = repo_data.get('description', '') or ''
        docs = min(100, len(description) * 2) if description else 20
        if repo_data.get('has_wiki', True):
            docs += 10
        docs = min(100, docs)

        # 6. 依赖健康（默认中性，有数据时再评）
        dependency = 50  # 默认中性

        # 7. 相关性
        relevance = self._score_relevance(repo_data, query)

        # 8. 生态（默认中性，有依赖图数据时再评）
        ecosystem = 50
        if repo_data.get('depends_on'):
            ecosystem = 70  # 被其他项目依赖说明有生态价值
        if repo_data.get('discovery_method') == 'awesome_list':
            ecosystem = 80  # 被收录到 awesome 列表说明有社区认可

        dimensions = {
            'popularity': popularity,
            'activity': activity,
            'maintenance': maintenance,
            'community': community,
            'docs': docs,
            'dependency': dependency,
            'relevance': relevance,
            'ecosystem': ecosystem,
        }

        # 加权总分
        total = sum(d * w for d, w in zip(dimensions.values(), weights))

        # 分组
        if stars >= self.FLAGSHIP_THRESHOLD:
            group = 'flagship'
        elif stars >= self.MAINSTREAM_THRESHOLD:
            group = 'mainstream'
        else:
            group = 'niche'

        # 推荐等级
        if total >= self.GRADE_ADOPT:
            grade = 'Adopt'
        elif total >= self.GRADE_TRIAL:
            grade = 'Trial'
        elif total >= self.GRADE_ASSESS:
            grade = 'Assess'
        else:
            grade = 'Hold'

        # 推荐理由
        reason = self._generate_reason(dimensions, grade, group, repo_data)

        return RecommendationScore(
            total_score=total,
            grade=grade,
            dimensions=dimensions,
            group=group,
            intent_weighted=(intent != 'default'),
            recommendation_reason=reason,
        )

    def _score_activity(self, repo_data: Dict) -> float:
        """活跃度评分"""
        pushed_at = repo_data.get('pushed_at', '')
        updated_at = repo_data.get('updated_at', '')
        open_issues = repo_data.get('open_issues', 0)

        score = 0
        # 基于最后推送时间
        if pushed_at:
            try:
                pushed_date = datetime.strptime(pushed_at[:10], '%Y-%m-%d')
                days_since = (datetime.now() - pushed_date).days
                if days_since <= 30:
                    score += 50
                elif days_since <= 90:
                    score += 35
                elif days_since <= 180:
                    score += 20
                elif days_since <= 365:
                    score += 10
                else:
                    score += 0
            except (ValueError, TypeError):
                pass

        # 基于 open_issues（有 issue 说明有用户关注）
        if 0 < open_issues <= 100:
            score += 25
        elif 100 < open_issues <= 500:
            score += 20
        elif open_issues > 500:
            score += 15
        elif open_issues == 0:
            score += 10  # 无 issue 也可能是好项目

        return min(100, score)

    def _score_maintenance(self, repo_data: Dict) -> float:
        """维护状态评分"""
        archived = repo_data.get('archived', False)
        if archived:
            return 10  # 归档项目大幅降分

        updated_at = repo_data.get('updated_at', '')
        score = 50  # 基础分

        if updated_at:
            try:
                updated_date = datetime.strptime(updated_at[:10], '%Y-%m-%d')
                days_since = (datetime.now() - updated_date).days
                if days_since <= 30:
                    score += 40
                elif days_since <= 90:
                    score += 30
                elif days_since <= 180:
                    score += 15
                elif days_since > 365:
                    score -= 20
            except (ValueError, TypeError):
                pass

        return max(0, min(100, score))

    def _score_relevance(self, repo_data: Dict, query: str) -> float:
        """相关性评分（关键词匹配度）"""
        if not query:
            return 50

        query_lower = query.lower()
        query_words = set(query_lower.split())

        name = (repo_data.get('name', '') or '').lower()
        description = (repo_data.get('description', '') or '').lower()
        topics = [t.lower() for t in repo_data.get('topics', [])]

        score = 0
        # 名称匹配
        if query_lower in name:
            score += 40
        elif any(w in name for w in query_words):
            score += 25

        # 描述匹配
        if query_lower in description:
            score += 30
        elif any(w in description for w in query_words):
            score += 20

        # topic 匹配
        for topic in topics:
            if query_lower in topic or any(w in topic for w in query_words):
                score += 15
                break

        return min(100, score + 10)  # 基础分 10

    def _generate_reason(self, dims: Dict, grade: str, group: str, repo_data: Dict) -> str:
        """生成推荐理由"""
        stars = repo_data.get('stars', 0)
        name = repo_data.get('full_name', repo_data.get('name', ''))

        if repo_data.get('metadata_missing'):
            # 没取到 star 与推送时间，就不能说人家"零星、不活跃"——实测这条路上站着真实 586 星的仓库
            return (f"{name}: ⚠️ 未取到 star/更新等元数据（GitHub 详情接口没回），"
                    '分数按缺项计，不代表这个项目没人用')

        reasons = []
        if group == 'flagship':
            reasons.append(f"高星项目（⭐{stars}），社区认可度高")
        elif group == 'niche':
            reasons.append(f"小众项目（⭐{stars}），但具有参考价值")

        if dims.get('activity', 0) >= 50:
            reasons.append("活跃维护中")
        elif dims.get('activity', 0) < 20:
            reasons.append("⚠️ 活跃度较低")

        if dims.get('relevance', 0) >= 60:
            reasons.append("与查询高度相关")

        if repo_data.get('archived'):
            reasons.append("⚠️ 已归档，不再维护")

        if repo_data.get('discovery_method') == 'awesome_list':
            reasons.append("被 awesome 列表收录")

        if repo_data.get('discovery_method') == 'dependency_graph':
            reasons.append("被其他项目依赖")

        return f"{name}: {'，'.join(reasons)}" if reasons else name

    def rank_results(
        self,
        results: List[Any],  # SearchResult 列表
        query: str = '',
        intent: str = 'default',
    ) -> List[Dict[str, Any]]:
        """
        对搜索结果进行推荐度评分和分组排序

        Args:
            results: SearchResult 列表（raw 字段含 GitHub 仓库数据）
            query: 原始查询
            intent: 查询意图

        Returns:
            排序后的结果列表，每个元素包含：
            - result: 原 SearchResult
            - recommendation: RecommendationScore
            - group_rank: 组内排名
        """
        scored: List[Dict[str, Any]] = []

        for result in results:
            # 兼容 SearchResult 对象（有 raw 属性）和 dict（有 get 方法）
            if hasattr(result, 'raw'):
                repo_data = result.raw
            elif hasattr(result, 'get'):
                repo_data = result.get('raw', {})
            else:
                repo_data = {}
            # 只评分 GitHub 类型的结果
            if not repo_data or not isinstance(repo_data, dict):
                continue
            if repo_data.get('repo_type') != 'github':
                if 'stars' in repo_data:
                    pass  # 有 stars 字段也评分
                else:
                    continue

            rec = self.score(repo_data, query, intent)
            scored.append({
                'result': result,
                'recommendation': rec,
            })

        # 分组排序
        groups = {'flagship': [], 'mainstream': [], 'niche': []}
        for item in scored:
            groups[item['recommendation'].group].append(item)

        # 每组内按总分降序排序
        for group_name in groups:
            groups[group_name].sort(key=lambda x: x['recommendation'].total_score, reverse=True)
            for i, item in enumerate(groups[group_name]):
                item['recommendation'].rank_in_group = i + 1

        # 合并：旗舰组 → 主流组 → 小众组
        ranked = groups['flagship'] + groups['mainstream'] + groups['niche']

        return ranked


# ============================================================
# 学术论文推荐度评分器
# ============================================================

class PaperRecommender:
    """
    学术论文推荐度评分器

    5 维评分模型（每维 0-100）：
    1. citation_impact（引用影响力）: log10(citations+1) * 缩放 + influential 加权
    2. recency（时效性）: 发表时间衰减（3 年半衰期）
    3. authority（来源权威）: 期刊/会议影响因子 + arXiv 分类
    4. author_h_index（作者 h-index）: 通讯作者 h-index
    5. relevance（相关性）: 标题/摘要关键词匹配

    推荐等级：
    - Must Read（必读）: 总分 >= 80
    - Recommended（推荐）: 总分 >= 60
    - Optional（可选）: 总分 >= 40
    - Skip（跳过）: 总分 < 40
    """

    # 5 维权重
    DEFAULT_WEIGHTS = (0.30, 0.20, 0.20, 0.10, 0.20)

    # 半衰期（年）
    HALF_LIFE_YEARS = 3.0

    def score(
        self,
        paper_data: Dict[str, Any],
        query: str = '',
    ) -> RecommendationScore:
        """
        评分单篇论文

        Args:
            paper_data: 论文数据（含 citations/published_date/venue/authors/title/abstract）
            query: 原始查询关键词
        """
        weights = self.DEFAULT_WEIGHTS

        # 1. 引用影响力
        citations = paper_data.get('citation_count', 0) or paper_data.get('citations', 0)
        influential = paper_data.get('influential_citation_count', 0)
        citation_impact = min(100, math.log10(citations + 1) * 20)
        if influential:
            citation_impact += min(20, influential * 5)
        citation_impact = min(100, citation_impact)

        # 2. 时效性（指数衰减）
        published_date = paper_data.get('published_date', '') or paper_data.get('year', '')
        recency = self._score_recency(published_date)

        # 3. 来源权威
        venue = paper_data.get('venue', '') or paper_data.get('journal', '')
        authority = self._score_authority(venue, paper_data)

        # 4. 作者 h-index
        h_index = paper_data.get('author_h_index', 0)
        author_score = min(100, h_index * 2) if h_index else 50

        # 5. 相关性
        relevance = self._score_relevance(paper_data, query)

        dimensions = {
            'citation_impact': citation_impact,
            'recency': recency,
            'authority': authority,
            'author_h_index': author_score,
            'relevance': relevance,
        }

        total = sum(d * w for d, w in zip(dimensions.values(), weights))

        # 推荐等级
        if total >= 80:
            grade = 'Must Read'
        elif total >= 60:
            grade = 'Recommended'
        elif total >= 40:
            grade = 'Optional'
        else:
            grade = 'Skip'

        return RecommendationScore(
            total_score=total,
            grade=grade,
            dimensions=dimensions,
            group='paper',
            recommendation_reason=self._generate_reason(dimensions, grade, paper_data),
        )

    def _score_recency(self, published_date: str) -> float:
        """时效性评分（3 年半衰期指数衰减）"""
        if not published_date:
            return 50  # 无日期信息，中性

        try:
            # 尝试解析年份
            year_str = str(published_date)[:4]
            year = int(year_str)
            current_year = datetime.now().year
            years_ago = current_year - year

            # 指数衰减：half_life=3 年
            score = 100 * math.exp(-0.231 * years_ago)  # ln(2)/3 ≈ 0.231
            return max(0, min(100, score))
        except (ValueError, TypeError):
            return 50

    def _score_authority(self, venue: str, paper_data: Dict) -> float:
        """来源权威性评分"""
        if not venue:
            # arXiv 预印本，基于分类评分
            categories = paper_data.get('categories', [])
            if categories:
                # 顶会/顶刊相关分类加分
                top_categories = ['cs.LG', 'cs.CL', 'cs.AI', 'cs.CV', 'stat.ML']
                if any(c in top_categories for c in categories):
                    return 65
            return 45  # 无 venue 信息

        venue_lower = venue.lower()
        # 顶会/顶刊列表
        top_venues = [
            'nature', 'science', 'cell',
            'neurips', 'icml', 'iclr', 'cvpr', 'acl', 'emnlp', 'naacl',
            'aaai', 'ijcai', 'sigkdd', 'siggraph', 'ccs', 's&p',
            'jmlr', 'tpami', 'trends cogn sci',
        ]
        if any(v in venue_lower for v in top_venues):
            return 90

        # 二级会议/期刊
        second_tier = [
            'workshop', 'symposium', 'conference',
            'transaction', 'journal',
        ]
        if any(v in venue_lower for v in second_tier):
            return 60

        return 50

    def _score_relevance(self, paper_data: Dict, query: str) -> float:
        """相关性评分"""
        if not query:
            return 50

        query_lower = query.lower()
        query_words = set(query_lower.split())

        title = (paper_data.get('title', '') or '').lower()
        abstract = (paper_data.get('abstract', '') or paper_data.get('summary', '') or '').lower()

        score = 0
        if query_lower in title:
            score += 50
        elif any(w in title for w in query_words):
            score += 35

        if query_lower in abstract:
            score += 30
        elif any(w in abstract for w in query_words):
            score += 20

        return min(100, score + 10)

    def _generate_reason(self, dims: Dict, grade: str, paper_data: Dict) -> str:
        """生成推荐理由"""
        title = paper_data.get('title', '')[:80]
        citations = paper_data.get('citation_count', 0) or paper_data.get('citations', 0)

        reasons = []
        if citations > 100:
            reasons.append(f"高引论文（{citations} 次引用）")
        elif citations > 10:
            reasons.append(f"被引 {citations} 次")

        if dims.get('recency', 0) >= 70:
            reasons.append("近期发表")
        if dims.get('authority', 0) >= 80:
            reasons.append("顶会/顶刊")
        if dims.get('relevance', 0) >= 60:
            reasons.append("高度相关")

        return f"{title}: {'，'.join(reasons)}" if reasons else title

    def rank_results(
        self,
        results: List[Any],
        query: str = '',
    ) -> List[Dict[str, Any]]:
        """对论文搜索结果进行推荐度评分和排序"""
        scored: List[Dict[str, Any]] = []

        for result in results:
            # 兼容 SearchResult 对象（有 raw 属性）和 dict（有 get 方法）
            if hasattr(result, 'raw'):
                paper_data = result.raw
            elif hasattr(result, 'get'):
                paper_data = result.get('raw', {})
            else:
                paper_data = {}
            if not paper_data or not isinstance(paper_data, dict):
                continue

            rec = self.score(paper_data, query)
            scored.append({
                'result': result,
                'recommendation': rec,
            })

        # 按总分降序排序
        scored.sort(key=lambda x: x['recommendation'].total_score, reverse=True)

        for i, item in enumerate(scored):
            item['recommendation'].rank_in_group = i + 1

        return scored


# ============================================================
# 意图识别（简化版，供推荐度评分使用）
# ============================================================

def detect_intent(query: str) -> str:
    """
    检测查询意图（用于推荐度权重调整）

    Args:
        query: 查询字符串

    Returns:
        意图类型：default/novel_approach/production_ready/learning/comparison
    """
    query_lower = query.lower()

    # novel_approach: 寻找新方法/创新
    novel_keywords = ['novel', 'new', 'innovative', 'alternative', '小众', '创新', '新方法', '替代']
    if any(k in query_lower for k in novel_keywords):
        return 'novel_approach'

    # production_ready: 生产可用
    prod_keywords = ['production', 'enterprise', 'stable', 'production-ready', '生产', '企业级', '稳定']
    if any(k in query_lower for k in prod_keywords):
        return 'production_ready'

    # learning: 学习/教程
    learn_keywords = ['learn', 'tutorial', 'beginner', '学习', '教程', '入门', '初学']
    if any(k in query_lower for k in learn_keywords):
        return 'learning'

    # comparison: 对比
    compare_keywords = ['vs', 'compare', 'comparison', '对比', '比较', '区别']
    if any(k in query_lower for k in compare_keywords):
        return 'comparison'

    return 'default'
