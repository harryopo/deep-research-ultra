#!/usr/bin/env python3
"""
Deep Research Ultra v4.0 — Phase 1: Plan（MECE 问题树）

实现麦肯锡 MECE 原则的问题拆解：
- M (Mutually Exclusive): 子问题互不重叠
- C (Collectively Exhaustive): 子问题合起来覆盖全部

核心组件：
- SubQuestion: 子问题数据结构（含假设、数据源、子树）
- IssueTree: MECE 问题树（支持层级拆解、验证、可视化）
- ResearchPlan: 调研计划（含主题、目标、深度、维度、问题树）
- PlanGenerator: 计划生成器（澄清、拆解、假设、数据源匹配）

输出：research_plan.json（供 Execute 阶段使用）

使用方式：
    # Claude 读取 SKILL.md 后调用本模块
    from plan import PlanGenerator, ResearchPlan

    generator = PlanGenerator()
    plan = generator.generate_plan(
        topic="2025 年最值得学习的 Python Web 框架",
        goal="技术选型",
        depth="standard",
        dimensions=["性能", "生态", "学习曲线", "生产案例", "社区活跃度"],
        time_range="2024-2025",
    )
    plan.save("research_plan.json")
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


# ============================================================
# 数据结构
# ============================================================

# ============================================================
# 问题链节点状态机（v5.1 新增，对齐秘塔问题链可视化 + Kimi 反思机制）
# ============================================================

# 状态流转：pending → searching → verified | conflict | supplementing → completed
STATUS_FLOW = {
    'pending':        ['searching'],
    'searching':      ['verified', 'conflict', 'supplementing', 'pending'],
    'verified':       ['completed', 'conflict'],   # 新证据可能推翻已验证结论
    'conflict':       ['supplementing', 'verified'],
    'supplementing':  ['verified', 'completed'],
    'completed':      [],
}

# 节点状态标注 emoji（对齐秘塔颜色：灰/蓝/绿/红/橙）
STATUS_EMOJI = {
    'pending':       '⏳',  # 灰：待处理
    'searching':     '🔄',  # 蓝：搜索中
    'verified':      '✅',  # 绿：结论明确
    'conflict':      '❌',  # 红：矛盾
    'supplementing': '⚠️',  # 橙：信息待补充
    'completed':     '📦',  # 归档
}


@dataclass
class SubQuestion:
    """
    子问题（MECE 问题树的节点）

    每个子问题包含：
    - 可验证的假设（Hypothesis-Driven）
    - 匹配的数据源（MCP/Skill/内置/降级）
    - 子问题（形成树结构）
    - v5.1 新增：问题链节点元数据（证据/置信度/查询历史/反思记录）
    """
    id: str                                    # 唯一标识
    question: str                              # 子问题描述
    hypothesis: str = ''                       # 可验证假设
    data_sources: List[str] = field(default_factory=list)  # 匹配的数据源
    depth: int = 0                             # 在树中的深度（0=根）
    children: List['SubQuestion'] = field(default_factory=list)  # 子问题
    parent_id: Optional[str] = None            # 父节点 ID
    keywords: List[str] = field(default_factory=list)  # 搜索关键词
    status: str = 'pending'  # pending/searching/verified/conflict/supplementing/completed
    search_count: int = 0                      # 已搜索次数
    findings_count: int = 0                    # 已发现证据数
    # v5.1 新增：问题链节点元数据（对齐秘塔 + Kimi）
    evidence: List[Dict] = field(default_factory=list)      # 关键证据 [{statement, source_url, source_domain, craap_grade}]
    confidence: float = 0.0                                  # 置信度 0-1
    search_queries: List[str] = field(default_factory=list)  # 已执行的搜索查询历史
    reflection_notes: List[str] = field(default_factory=list)  # 反思记录

    def add_child(self, child: 'SubQuestion') -> None:
        """添加子问题"""
        child.parent_id = self.id
        child.depth = self.depth + 1
        self.children.append(child)

    def is_leaf(self) -> bool:
        """是否为叶子节点"""
        return len(self.children) == 0

    def to_dict(self) -> Dict:
        """转为字典"""
        return {
            'id': self.id,
            'question': self.question,
            'hypothesis': self.hypothesis,
            'data_sources': self.data_sources,
            'depth': self.depth,
            'parent_id': self.parent_id,
            'keywords': self.keywords,
            'status': self.status,
            'search_count': self.search_count,
            'findings_count': self.findings_count,
            'evidence': self.evidence,
            'confidence': self.confidence,
            'search_queries': self.search_queries,
            'reflection_notes': self.reflection_notes,
            'children': [c.to_dict() for c in self.children],
        }


@dataclass
class ResearchPlan:
    """
    调研计划

    Phase 1 (Plan) 的输出，Phase 2 (Execute) 的输入。
    """
    topic: str                                          # 调研主题
    goal: str = ''                                      # 调研目标
    depth: str = 'standard'                             # 调研深度：quick/standard/deep
    dimensions: List[str] = field(default_factory=list) # 调研维度
    time_range: str = ''                                # 时间范围
    language: str = ''                                  # 语言偏好（zh/en/auto）
    region: str = ''                                    # 区域（cn/global）
    issue_tree: List[SubQuestion] = field(default_factory=list)  # MECE 问题树
    created_at: str = ''                                # 创建时间
    estimated_duration: str = ''                        # 预估时长
    estimated_sources: int = 0                          # 预估数据源数

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        """转为字典"""
        return {
            'topic': self.topic,
            'goal': self.goal,
            'depth': self.depth,
            'dimensions': self.dimensions,
            'time_range': self.time_range,
            'language': self.language,
            'region': self.region,
            'issue_tree': [q.to_dict() for q in self.issue_tree],
            'created_at': self.created_at,
            'estimated_duration': self.estimated_duration,
            'estimated_sources': self.estimated_sources,
        }

    def save(self, path: str) -> None:
        """保存为 JSON 文件"""
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    @classmethod
    def load(cls, path: str) -> 'ResearchPlan':
        """从 JSON 文件加载"""
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict) -> 'ResearchPlan':
        """从字典构建"""
        tree_data = data.get('issue_tree', [])
        issue_tree = [SubQuestion(**q) if isinstance(q, dict) else q for q in tree_data]
        return cls(
            topic=data.get('topic', ''),
            goal=data.get('goal', ''),
            depth=data.get('depth', 'standard'),
            dimensions=data.get('dimensions', []),
            time_range=data.get('time_range', ''),
            language=data.get('language', ''),
            region=data.get('region', ''),
            issue_tree=issue_tree,
            created_at=data.get('created_at', ''),
            estimated_duration=data.get('estimated_duration', ''),
            estimated_sources=data.get('estimated_sources', 0),
        )

    def get_all_questions(self) -> List[SubQuestion]:
        """获取所有子问题（扁平化）"""
        result = []
        def _collect(q: SubQuestion):
            result.append(q)
            for child in q.children:
                _collect(child)
        for q in self.issue_tree:
            _collect(q)
        return result

    def get_leaf_questions(self) -> List[SubQuestion]:
        """获取所有叶子节点子问题"""
        return [q for q in self.get_all_questions() if q.is_leaf()]


# ============================================================
# MECE 问题树
# ============================================================

class IssueTree:
    """
    MECE 问题树

    提供问题树的操作和验证：
    - 添加子问题
    - MECE 验证（重叠检查、覆盖检查）
    - 可视化（Mermaid 图表）
    - 遍历（DFS/BFS）
    """

    def __init__(self):
        self.roots: List[SubQuestion] = []

    def add_root(self, question: str, hypothesis: str = '',
                 data_sources: Optional[List[str]] = None,
                 keywords: Optional[List[str]] = None) -> SubQuestion:
        """添加根问题"""
        q = SubQuestion(
            id=self._gen_id(),
            question=question,
            hypothesis=hypothesis,
            data_sources=data_sources or [],
            depth=0,
            keywords=keywords or [],
        )
        self.roots.append(q)
        return q

    def add_child(self, parent: SubQuestion, question: str,
                  hypothesis: str = '',
                  data_sources: Optional[List[str]] = None,
                  keywords: Optional[List[str]] = None) -> SubQuestion:
        """添加子问题"""
        q = SubQuestion(
            id=self._gen_id(),
            question=question,
            hypothesis=hypothesis,
            data_sources=data_sources or [],
            depth=parent.depth + 1,
            parent_id=parent.id,
            keywords=keywords or [],
        )
        parent.add_child(q)
        return q

    @staticmethod
    def _gen_id() -> str:
        """生成唯一 ID"""
        return f"q_{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------
    # MECE 验证
    # ------------------------------------------------------------

    def validate_mece(self) -> Dict[str, Any]:
        """
        验证 MECE 原则

        Returns:
            {
                'is_mece': bool,           # 是否满足 MECE
                'overlap_score': float,    # 重叠度（0=无重叠，越低越好）
                'coverage_score': float,   # 覆盖度（1=完全覆盖，越高越好）
                'issues': List[str],       # 发现的问题
                'suggestions': List[str],  # 改进建议
            }
        """
        issues = []
        suggestions = []

        # 检查每层子问题是否有重叠
        all_questions = self._collect_all()
        for q in all_questions:
            if not q.children:
                continue
            # 检查子问题之间的关键词重叠
            child_keywords = [set(c.keywords) for c in q.children if c.keywords]
            for i in range(len(child_keywords)):
                for j in range(i + 1, len(child_keywords)):
                    overlap = child_keywords[i] & child_keywords[j]
                    if overlap:
                        issues.append(
                            f"子问题 '{q.children[i].question}' 和 '{q.children[j].question}' "
                            f"关键词重叠: {overlap}"
                        )

            # 检查子问题数量（MECE 通常 3-7 个）
            n = len(q.children)
            if n < 3:
                suggestions.append(f"'{q.question}' 的子问题只有 {n} 个，可能未穷尽（建议 3-7 个）")
            elif n > 7:
                suggestions.append(f"'{q.question}' 的子问题有 {n} 个，可能过于分散（建议 3-7 个）")

        # 检查是否有假设
        no_hypothesis = [q for q in all_questions if q.is_leaf() and not q.hypothesis]
        if no_hypothesis:
            issues.append(f"{len(no_hypothesis)} 个叶子子问题缺少可验证假设")

        # 检查是否匹配数据源
        no_sources = [q for q in all_questions if q.is_leaf() and not q.data_sources]
        if no_sources:
            issues.append(f"{len(no_sources)} 个叶子子问题未匹配数据源")

        # 计算 MECE 分数
        overlap_score = 0.0
        coverage_score = 1.0 if all_questions and all(q.hypothesis for q in all_questions if q.is_leaf()) else 0.7

        is_mece = len(issues) == 0

        return {
            'is_mece': is_mece,
            'overlap_score': overlap_score,
            'coverage_score': coverage_score,
            'issues': issues,
            'suggestions': suggestions,
            'total_questions': len(all_questions),
            'leaf_questions': len([q for q in all_questions if q.is_leaf()]),
            'max_depth': max((q.depth for q in all_questions), default=0),
        }

    def _collect_all(self) -> List[SubQuestion]:
        """收集所有节点"""
        result = []
        def _collect(q: SubQuestion):
            result.append(q)
            for child in q.children:
                _collect(child)
        for q in self.roots:
            _collect(q)
        return result

    # ------------------------------------------------------------
    # 可视化
    # ------------------------------------------------------------

    def to_mermaid(self) -> str:
        """
        生成 Mermaid 图表（mindmap 或 graph TD）

        Returns:
            Mermaid 语法字符串
        """
        lines = ["graph TD"]
        # 添加节点
        for root in self.roots:
            self._add_mermaid_node(root, lines)
        # 添加边
        for root in self.roots:
            self._add_mermaid_edges(root, lines)
        return '\n'.join(lines)

    def _add_mermaid_node(self, q: SubQuestion, lines: List[str]) -> None:
        """添加 Mermaid 节点"""
        # 节点 ID 用 q.id，文本截断
        # 优化：如果问题包含 " — " 分隔符（PlanGenerator 自动生成的格式），
        # 只显示分隔符后的维度部分，避免所有节点显示相同前缀
        text = q.question
        if ' — ' in text:
            # 取分隔符后的部分，更简洁
            text = text.split(' — ', 1)[1]
        text = text[:50].replace('"', "'").replace('\n', ' ')
        shape = f'["{text}"]'
        lines.append(f"    {q.id}{shape}")
        for child in q.children:
            self._add_mermaid_node(child, lines)

    def _add_mermaid_edges(self, q: SubQuestion, lines: List[str]) -> None:
        """添加 Mermaid 边"""
        for child in q.children:
            lines.append(f"    {q.id} --> {child.id}")
            self._add_mermaid_edges(child, lines)

    def to_markdown(self, indent: int = 2) -> str:
        """生成 Markdown 大纲"""
        lines = []
        for root in self.roots:
            self._add_markdown_node(root, lines, 0, indent)
        return '\n'.join(lines)

    def _add_markdown_node(self, q: SubQuestion, lines: List[str],
                           level: int, indent: int) -> None:
        prefix = ' ' * (level * indent)
        bullet = '-' if level == 0 else '*'
        line = f"{prefix}{bullet} {q.question}"
        if q.hypothesis:
            line += f"\n{prefix}  假设: {q.hypothesis}"
        if q.data_sources:
            line += f"\n{prefix}  数据源: {', '.join(q.data_sources)}"
        lines.append(line)
        for child in q.children:
            self._add_markdown_node(child, lines, level + 1, indent)


# ============================================================
# 数据源匹配器
# ============================================================

class DataSourceMatcher:
    """
    数据源匹配器

    根据子问题的特征匹配最合适的数据源：
    - 学术类问题 → arxiv / paper-search / sciverse
    - 社区类问题 → agent-reach / last30days
    - 开源类问题 → oss-finder
    - 技术文档类 → context7 / defuddle
    - 综合类 → tavily / firecrawl / open-websearch / websearch
    """

    # 关键词到数据源的映射
    KEYWORD_SOURCE_MAP = {
        # 学术
        '论文': ['arxiv', 'paper-search', 'sciverse'],
        'paper': ['arxiv', 'paper-search', 'sciverse'],
        '学术': ['arxiv', 'paper-search', 'sciverse'],
        'academic': ['arxiv', 'paper-search', 'sciverse'],
        '研究': ['arxiv', 'paper-search', 'sciverse', 'tavily'],
        'research': ['arxiv', 'paper-search', 'sciverse', 'tavily'],
        '引用': ['sciverse', 'paper-search'],
        'citation': ['sciverse', 'paper-search'],
        'arxiv': ['arxiv'],
        'pubmed': ['paper-search'],
        # 社区
        '社区': ['agent-reach', 'last30days'],
        'community': ['agent-reach', 'last30days'],
        '讨论': ['agent-reach', 'last30days'],
        'discussion': ['agent-reach', 'last30days'],
        'reddit': ['agent-reach', 'last30days'],
        '知乎': ['agent-reach'],
        '小红书': ['agent-reach'],
        'twitter': ['agent-reach', 'last30days'],
        '微博': ['agent-reach'],
        '哔哩哔哩': ['agent-reach'],
        'bilibili': ['agent-reach'],
        'youtube': ['agent-reach', 'last30days'],
        '播客': ['agent-reach'],
        'podcast': ['agent-reach'],
        # 开源
        '开源': ['oss-finder'],
        'open source': ['oss-finder'],
        'github': ['oss-finder'],
        'gitlab': ['oss-finder'],
        'gitee': ['oss-finder'],
        'npm': ['oss-finder'],
        'pypi': ['oss-finder'],
        '包': ['oss-finder', 'context7'],
        'package': ['oss-finder', 'context7'],
        '库': ['oss-finder', 'context7'],
        'library': ['oss-finder', 'context7'],
        '框架': ['oss-finder', 'context7', 'tavily'],
        'framework': ['oss-finder', 'context7', 'tavily'],
        # 技术文档
        '文档': ['context7', 'defuddle'],
        'docs': ['context7', 'defuddle'],
        'documentation': ['context7', 'defuddle'],
        'api': ['context7', 'defuddle', 'tavily'],
        '教程': ['context7', 'tavily', 'defuddle'],
        'tutorial': ['context7', 'tavily', 'defuddle'],
        # 时效性
        '最新': ['last30days', 'tavily'],
        'latest': ['last30days', 'tavily'],
        '最近': ['last30days', 'tavily'],
        'recent': ['last30days', 'tavily'],
        '趋势': ['last30days', 'tavily'],
        'trend': ['last30days', 'tavily'],
        '2025': ['last30days', 'tavily'],
        '2026': ['last30days', 'tavily'],
        # 对比
        '对比': ['tavily', 'firecrawl', 'websearch'],
        'compare': ['tavily', 'firecrawl', 'websearch'],
        'vs': ['tavily', 'firecrawl', 'websearch'],
        # 性能
        '性能': ['tavily', 'websearch', 'oss-finder'],
        'performance': ['tavily', 'websearch', 'oss-finder'],
        '基准': ['tavily', 'websearch'],
        'benchmark': ['tavily', 'websearch'],
    }

    @classmethod
    def match(cls, question: str, keywords: Optional[List[str]] = None) -> List[str]:
        """
        匹配数据源

        Args:
            question: 子问题描述
            keywords: 关键词列表

        Returns:
            匹配的数据源列表（去重，按匹配次数排序）
        """
        text = (question + ' ' + ' '.join(keywords or [])).lower()
        source_scores: Dict[str, int] = {}

        for keyword, sources in cls.KEYWORD_SOURCE_MAP.items():
            if keyword.lower() in text:
                for source in sources:
                    source_scores[source] = source_scores.get(source, 0) + 1

        # 按匹配次数排序
        sorted_sources = sorted(source_scores.items(), key=lambda x: -x[1])
        return [source for source, _ in sorted_sources]

    @classmethod
    def get_default_sources(cls) -> List[str]:
        """获取默认数据源（综合搜索）"""
        return ['tavily', 'open-websearch', 'websearch']


# ============================================================
# 调研计划生成器
# ============================================================

class PlanGenerator:
    """
    调研计划生成器

    工作流程：
    1. clarify_topic(): 澄清模糊主题（如需要）
    2. generate_issue_tree(): 生成 MECE 问题树（由 Claude LLM 完成）
    3. generate_hypotheses(): 为每个子问题生成可验证假设
    4. match_data_sources(): 匹配数据源
    5. generate_plan(): 输出 ResearchPlan
    """

    # 深度模式预设
    DEPTH_PRESETS = {
        'quick': {
            'description': '快速调研（1-2 分钟）',
            'max_sub_questions': 3,
            'max_depth': 1,
            'sources_per_question': 2,
            'estimated_duration': '1-2 分钟',
            'estimated_sources': '5-10',
        },
        'standard': {
            'description': '标准调研（3-5 分钟）',
            'max_sub_questions': 5,
            'max_depth': 2,
            'sources_per_question': 3,
            'estimated_duration': '3-5 分钟',
            'estimated_sources': '15-25',
        },
        'deep': {
            'description': '深度调研（10-20 分钟）',
            'max_sub_questions': 8,
            'max_depth': 3,
            'sources_per_question': 5,
            'estimated_duration': '10-20 分钟',
            'estimated_sources': '30-50',
        },
    }

    # 常见维度模板
    DIMENSION_TEMPLATES = {
        'tech_select': ['性能', '生态', '学习曲线', '生产案例', '社区活跃度', '文档质量'],
        'comparison': ['特性对比', '性能基准', '适用场景', '生态成熟度', '迁移成本'],
        'trend': ['当前状态', '技术演进', '社区动态', '未来方向', '潜在风险'],
        'best_practice': ['核心原则', '常见模式', '反模式', '工具链', '案例分析'],
        'academic': ['理论基础', '关键论文', '实验方法', '数据集', '评估指标', '开源实现'],
    }

    def clarify_topic(self, topic: str) -> Dict[str, Any]:
        """
        分析主题，判断是否需要澄清

        Returns:
            {
                'needs_clarification': bool,
                'detected_dimension': str,  # 检测到的维度模板
                'suggested_dimensions': List[str],
                'suggested_depth': str,
                'ambiguity_points': List[str],  # 模糊点
            }
        """
        topic_lower = topic.lower()

        # 检测维度模板
        detected_dimension = ''
        if any(kw in topic_lower for kw in ['vs', '对比', 'compare', '比较']):
            detected_dimension = 'comparison'
        elif any(kw in topic_lower for kw in ['趋势', 'trend', '未来', 'future', '演进']):
            detected_dimension = 'trend'
        elif any(kw in topic_lower for kw in ['最佳实践', 'best practice', '实践', 'practice']):
            detected_dimension = 'best_practice'
        elif any(kw in topic_lower for kw in ['论文', 'paper', '学术', 'academic', '研究', 'research']):
            detected_dimension = 'academic'
        elif any(kw in topic_lower for kw in ['选型', '选择', '哪个', 'best', '推荐']):
            detected_dimension = 'tech_select'

        suggested_dimensions = self.DIMENSION_TEMPLATES.get(detected_dimension, [])

        # 判断是否需要澄清
        # 短主题、无明确方向 → 需要澄清
        ambiguity_points = []
        if len(topic) < 10:
            ambiguity_points.append('主题过短，建议明确具体方向')
        if not detected_dimension:
            ambiguity_points.append('未识别调研类型，建议选择维度')
        if not any(kw in topic_lower for kw in ['2024', '2025', '2026', '最新', 'recent']):
            ambiguity_points.append('未指定时间范围')

        needs_clarification = len(ambiguity_points) > 0 or not detected_dimension

        # 建议深度
        if detected_dimension == 'academic':
            suggested_depth = 'deep'
        elif detected_dimension in ['comparison', 'trend']:
            suggested_depth = 'standard'
        else:
            suggested_depth = 'standard'

        return {
            'needs_clarification': needs_clarification,
            'detected_dimension': detected_dimension,
            'suggested_dimensions': suggested_dimensions,
            'suggested_depth': suggested_depth,
            'ambiguity_points': ambiguity_points,
        }

    def match_data_sources(self, question: str, keywords: Optional[List[str]] = None) -> List[str]:
        """为子问题匹配数据源"""
        sources = DataSourceMatcher.match(question, keywords)
        if not sources:
            sources = DataSourceMatcher.get_default_sources()
        return sources

    def generate_plan(
        self,
        topic: str,
        goal: str = '',
        depth: str = 'standard',
        dimensions: Optional[List[str]] = None,
        time_range: str = '',
        language: str = 'auto',
        region: str = '',
        issue_tree_data: Optional[List[Dict]] = None,
    ) -> ResearchPlan:
        """
        生成调研计划

        注意：MECE 问题树的实际拆解由 Claude LLM 完成。
        本方法接收 Claude 拆解后的结构化数据，组装为 ResearchPlan。

        Args:
            topic: 调研主题
            goal: 调研目标
            depth: 调研深度（quick/standard/deep）
            dimensions: 调研维度
            time_range: 时间范围
            language: 语言（auto/zh/en）
            region: 区域
            issue_tree_data: Claude 拆解后的问题树数据
                [{
                    "question": "...",
                    "hypothesis": "...",
                    "keywords": ["..."],
                    "children": [...]
                }]

        Returns:
            ResearchPlan 对象
        """
        preset = self.DEPTH_PRESETS.get(depth, self.DEPTH_PRESETS['standard'])

        # 如果未提供维度，使用预设
        if not dimensions:
            clarification = self.clarify_topic(topic)
            dimensions = clarification['suggested_dimensions'] or ['综合']

        # 按深度模式截取维度数量（保持 dimensions 与 issue_tree 数量一致）
        max_questions = preset['max_sub_questions']
        dimensions = dimensions[:max_questions]

        # 构建问题树
        issue_tree = []
        if issue_tree_data:
            for q_data in issue_tree_data:
                q = self._build_sub_question(q_data, depth=0)
                # 自动匹配数据源
                if not q.data_sources:
                    q.data_sources = self.match_data_sources(q.question, q.keywords)
                issue_tree.append(q)
        else:
            # 如果未提供问题树数据，根据维度生成骨架
            for dim in dimensions:
                q = SubQuestion(
                    id=IssueTree._gen_id(),
                    question=f"{topic} — {dim}",
                    hypothesis=f"假设：{dim} 维度存在值得关注的发现",
                    data_sources=self.match_data_sources(dim),
                    depth=0,
                    keywords=[dim.lower()],
                )
                issue_tree.append(q)

        # 估算数据源数
        leaf_count = sum(1 for q in issue_tree for _ in [q])  # 简化估算
        estimated_sources = leaf_count * preset['sources_per_question']

        return ResearchPlan(
            topic=topic,
            goal=goal,
            depth=depth,
            dimensions=dimensions,
            time_range=time_range,
            language=language,
            region=region,
            issue_tree=issue_tree,
            estimated_duration=preset['estimated_duration'],
            estimated_sources=estimated_sources,
        )

    def _build_sub_question(self, data: Dict, depth: int = 0,
                            parent_id: Optional[str] = None) -> SubQuestion:
        """递归构建子问题"""
        q = SubQuestion(
            id=data.get('id', IssueTree._gen_id()),
            question=data.get('question', ''),
            hypothesis=data.get('hypothesis', ''),
            data_sources=data.get('data_sources', []),
            depth=depth,
            parent_id=parent_id,
            keywords=data.get('keywords', []),
        )
        for child_data in data.get('children', []):
            child = self._build_sub_question(child_data, depth + 1, q.id)
            q.children.append(child)
        return q


# ============================================================
# CLI 入口
# ============================================================

def _main():
    """命令行入口：python plan.py <topic> [--depth standard]"""
    import argparse
    parser = argparse.ArgumentParser(description='生成 MECE 调研计划')
    parser.add_argument('topic', help='调研主题')
    parser.add_argument('--depth', default='standard', choices=['quick', 'standard', 'deep'])
    parser.add_argument('--goal', default='')
    parser.add_argument('--time-range', default='')
    parser.add_argument('--output', default='research_plan.json')
    args = parser.parse_args()

    generator = PlanGenerator()
    clarification = generator.clarify_topic(args.topic)
    print("主题分析：")
    print(json.dumps(clarification, indent=2, ensure_ascii=False))

    plan = generator.generate_plan(
        topic=args.topic,
        goal=args.goal,
        depth=args.depth,
        dimensions=clarification['suggested_dimensions'],
        time_range=args.time_range,
    )
    plan.save(args.output)
    print(f"\n调研计划已保存到 {args.output}")
    print(f"主题: {plan.topic}")
    print(f"深度: {plan.depth}")
    print(f"子问题数: {len(plan.issue_tree)}")
    print(f"预估时长: {plan.estimated_duration}")


if __name__ == "__main__":
    _main()
