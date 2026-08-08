#!/usr/bin/env python3
"""
Deep Research Ultra v4.0 — Phase 2 反思循环（Reflect）

实现深度调研的反思循环（Drill-down）：
- 每轮搜索后评估覆盖率
- 识别覆盖空白（coverage_gaps）
- 生成新子问题（Drill-down）
- 最多 3 轮反思（避免无限循环）

工作流程：
    首轮搜索 → 评估覆盖率 → 识别空白 → 生成新子问题 → 再次搜索 → ... → 达到阈值或上限

修复 v3.2.0 的问题：
- v3 的"迭代搜索"只是关键词变体（中文→英文、加年份）
  → v4 真正的深度：基于已有结果生成更深问题，再搜索
- v3 没有覆盖率评估
  → v4 引入覆盖率评估指标
- v3 没有反思循环
  → v4 实现 Plan → Reflect → Re-search 循环

使用方式：
    reflector = Reflector(max_rounds=3)
    for round_num in range(reflector.max_rounds):
        # 执行搜索...
        reflection = reflector.reflect(plan, results, round_num)
        if not reflection.should_drill_down:
            break
        # 根据 reflection.new_subquestions 继续搜索
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CoverageGap:
    """覆盖空白（未充分调研的领域）"""
    dimension: str                  # 维度名称
    reason: str                     # 空白原因
    suggested_question: str         # 建议的新子问题
    priority: str = 'medium'        # high/medium/low
    related_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'dimension': self.dimension,
            'reason': self.reason,
            'suggested_question': self.suggested_question,
            'priority': self.priority,
            'related_keywords': self.related_keywords,
        }


@dataclass
class Reflection:
    """单轮反思结果"""
    round_num: int                                      # 当前轮次
    coverage_score: float                               # 覆盖率（0-1）
    verified_claims_count: int                          # 已验证结论数
    single_source_count: int                            # 单源结论数
    contradictions_count: int                           # 矛盾点数
    coverage_gaps: List[CoverageGap] = field(default_factory=list)  # 覆盖空白
    new_subquestions: List[str] = field(default_factory=list)       # 新子问题
    should_drill_down: bool = False                     # 是否需要继续深入
    drill_down_reason: str = ''                         # 继续深入的原因
    stop_reason: str = ''                               # 停止的原因
    suggestions: List[str] = field(default_factory=list)            # 改进建议
    created_at: str = ''                                # 创建时间

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            'round_num': self.round_num,
            'coverage_score': round(self.coverage_score, 2),
            'verified_claims_count': self.verified_claims_count,
            'single_source_count': self.single_source_count,
            'contradictions_count': self.contradictions_count,
            'coverage_gaps': [g.to_dict() for g in self.coverage_gaps],
            'new_subquestions': self.new_subquestions,
            'should_drill_down': self.should_drill_down,
            'drill_down_reason': self.drill_down_reason,
            'stop_reason': self.stop_reason,
            'suggestions': self.suggestions,
            'created_at': self.created_at,
        }


@dataclass
class ReflectionHistory:
    """反思历史（记录所有轮次）"""
    reflections: List[Reflection] = field(default_factory=list)
    total_rounds: int = 0
    final_coverage: float = 0.0
    final_decision: str = ''  # completed/max_rounds_reached/sufficient

    def add(self, reflection: Reflection) -> None:
        self.reflections.append(reflection)
        self.total_rounds = len(self.reflections)
        self.final_coverage = reflection.coverage_score

    def to_dict(self) -> Dict:
        return {
            'total_rounds': self.total_rounds,
            'final_coverage': round(self.final_coverage, 2),
            'final_decision': self.final_decision,
            'reflections': [r.to_dict() for r in self.reflections],
        }


# ============================================================
# 反思器
# ============================================================

class Reflector:
    """
    反思器

    在每轮搜索后评估覆盖率，决定是否继续深入（Drill-down）。

    覆盖率评估维度：
    1. 维度覆盖：调研计划中的每个维度是否都有结果
    2. 子问题覆盖：每个子问题是否都有证据
    3. 来源多样性：是否使用了多种数据源
    4. 验证充分性：已验证结论占比
    5. 矛盾解决：矛盾点是否得到解释
    """

    # 覆盖率阈值（达到则停止）
    COVERAGE_THRESHOLD = 0.75
    # 最大反思轮次
    DEFAULT_MAX_ROUNDS = 3
    # 最小结果数（少于则继续）
    MIN_RESULTS_PER_QUESTION = 3

    def __init__(
        self,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        coverage_threshold: float = COVERAGE_THRESHOLD,
    ):
        self.max_rounds = max_rounds
        self.coverage_threshold = coverage_threshold
        self.history = ReflectionHistory()

    # ------------------------------------------------------------
    # 主反思入口
    # ------------------------------------------------------------

    def reflect(
        self,
        plan: Any,                       # ResearchPlan
        results: List[Any],              # 搜索结果
        round_num: int,                  # 当前轮次（从 0 开始）
        verification_result: Optional[Any] = None,  # VerificationResult
    ) -> Reflection:
        """
        执行一轮反思

        Args:
            plan: 调研计划（ResearchPlan 对象）
            results: 本轮搜索结果
            round_num: 当前轮次
            verification_result: 交叉验证结果

        Returns:
            Reflection 对象
        """
        # 1. 评估覆盖率
        coverage_score = self._evaluate_coverage(plan, results)

        # 2. 提取验证统计
        verified_count = 0
        single_count = 0
        contradiction_count = 0
        if verification_result:
            verified_count = len(verification_result.verified_claims)
            single_count = len(verification_result.single_source_claims)
            contradiction_count = len(verification_result.contradictions)

        # 3. 识别覆盖空白
        gaps = self._identify_gaps(plan, results, verification_result)

        # 4. 生成新子问题（Drill-down）
        new_subquestions = self._generate_drill_down_questions(gaps, results)

        # 5. 决定是否继续
        should_drill_down, stop_reason, drill_reason = self._should_continue(
            round_num, coverage_score, gaps, len(results)
        )

        # 6. 生成改进建议
        suggestions = self._generate_suggestions(
            coverage_score, gaps, verified_count, single_count, contradiction_count
        )

        reflection = Reflection(
            round_num=round_num,
            coverage_score=coverage_score,
            verified_claims_count=verified_count,
            single_source_count=single_count,
            contradictions_count=contradiction_count,
            coverage_gaps=gaps,
            new_subquestions=new_subquestions,
            should_drill_down=should_drill_down,
            drill_down_reason=drill_reason,
            stop_reason=stop_reason,
            suggestions=suggestions,
        )

        self.history.add(reflection)
        return reflection

    # ------------------------------------------------------------
    # 覆盖率评估
    # ------------------------------------------------------------

    def _evaluate_coverage(self, plan: Any, results: List[Any]) -> float:
        """
        评估覆盖率（0-1）

        评估维度：
        1. 维度覆盖（40%）：计划中的维度是否都有结果
        2. 来源多样性（20%）：使用了多少种数据源
        3. 结果数量（20%）：是否有足够的结果
        4. 验证充分性（20%）：已验证结论占比（如有验证结果）
        """
        scores = []

        # 1. 维度覆盖
        dimensions = getattr(plan, 'dimensions', []) if plan else []
        if dimensions:
            covered = 0
            for dim in dimensions:
                # 检查结果中是否有覆盖该维度的内容
                dim_keywords = dim.lower().split()
                for result in results:
                    content = ''
                    if hasattr(result, 'content'):
                        content = (result.content or '').lower()
                    elif isinstance(result, dict):
                        content = (result.get('content', '') or '').lower()
                    if any(kw in content for kw in dim_keywords):
                        covered += 1
                        break
            dim_score = covered / len(dimensions)
            scores.append(dim_score * 0.4)

        # 2. 来源多样性
        sources = set()
        for result in results:
            source = ''
            if hasattr(result, 'source'):
                source = result.source
            elif isinstance(result, dict):
                source = result.get('source', '')
            if source:
                sources.add(source)
        diversity_score = min(1.0, len(sources) / 4)  # 4 种以上数据源为满分
        scores.append(diversity_score * 0.2)

        # 3. 结果数量
        count_score = min(1.0, len(results) / 20)  # 20 条以上为满分
        scores.append(count_score * 0.2)

        # 4. 验证充分性（简化评估）
        if results:
            # 有 CRAAP 评分且 grade=high 的占比
            high_count = 0
            for result in results:
                craap = None
                if hasattr(result, 'craap_score'):
                    craap = result.craap_score
                elif isinstance(result, dict):
                    craap = result.get('craap_score', {})
                if craap and craap.get('grade') == 'high':
                    high_count += 1
            quality_score = high_count / len(results) if results else 0
            scores.append(quality_score * 0.2)

        return sum(scores) if scores else 0.0

    # ------------------------------------------------------------
    # 覆盖空白识别
    # ------------------------------------------------------------

    def _identify_gaps(
        self,
        plan: Any,
        results: List[Any],
        verification_result: Optional[Any],
    ) -> List[CoverageGap]:
        """识别覆盖空白"""
        gaps = []

        # 1. 维度覆盖空白
        dimensions = getattr(plan, 'dimensions', []) if plan else []
        for dim in dimensions:
            dim_keywords = dim.lower().split()
            covered = False
            for result in results:
                content = ''
                if hasattr(result, 'content'):
                    content = (result.content or '').lower()
                elif isinstance(result, dict):
                    content = (result.get('content', '') or '').lower()
                if any(kw in content for kw in dim_keywords):
                    covered = True
                    break
            if not covered:
                gaps.append(CoverageGap(
                    dimension=dim,
                    reason=f'维度 "{dim}" 未被任何结果覆盖',
                    suggested_question=f'关于 {dim} 的具体信息和数据',
                    priority='high',
                    related_keywords=dim_keywords,
                ))

        # 2. 子问题覆盖空白
        issue_tree = getattr(plan, 'issue_tree', []) if plan else []
        for q in issue_tree:
            if hasattr(q, 'question') and hasattr(q, 'findings_count'):
                if q.findings_count < self.MIN_RESULTS_PER_QUESTION:
                    gaps.append(CoverageGap(
                        dimension=q.question,
                        reason=f'子问题 "{q.question}" 的证据不足（{q.findings_count} 条）',
                        suggested_question=f'深入调研：{q.question}',
                        priority='medium',
                        related_keywords=getattr(q, 'keywords', []),
                    ))

        # 3. 单源结论（需要交叉验证）
        if verification_result:
            for claim in verification_result.single_source_claims:
                gaps.append(CoverageGap(
                    dimension=claim.statement[:50],
                    reason=f'结论 "{claim.statement[:50]}..." 仅有单一来源，需交叉验证',
                    suggested_question=f'寻找更多来源支持或反驳：{claim.statement[:50]}',
                    priority='medium',
                ))

        # 4. 矛盾未解决
        if verification_result:
            for con in verification_result.contradictions:
                gaps.append(CoverageGap(
                    dimension='矛盾解决',
                    reason=f'存在矛盾："{con.claim_a[:30]}..." vs "{con.claim_b[:30]}..."',
                    suggested_question=f'分析矛盾原因：{con.claim_a[:30]} vs {con.claim_b[:30]}',
                    priority='high',
                ))

        # 5. 数据源类型空白
        sources_used = set()
        for result in results:
            source = ''
            if hasattr(result, 'source'):
                source = result.source
            elif isinstance(result, dict):
                source = result.get('source', '')
            if source:
                sources_used.add(source)

        # 检查是否缺少学术源
        academic_sources = {'arxiv', 'paper-search', 'sciverse'}
        if not (sources_used & academic_sources):
            gaps.append(CoverageGap(
                dimension='学术文献',
                reason='未使用学术数据源，可能遗漏重要研究',
                suggested_question='搜索相关学术论文和研究',
                priority='medium',
                related_keywords=['论文', 'paper', 'research'],
            ))

        # 检查是否缺少社区源
        community_sources = {'agent-reach', 'last30days'}
        if not (sources_used & community_sources):
            gaps.append(CoverageGap(
                dimension='社区讨论',
                reason='未使用社区数据源，可能遗漏真实使用案例',
                suggested_question='搜索社区讨论和真实使用案例',
                priority='low',
                related_keywords=['reddit', '讨论', 'discussion'],
            ))

        return gaps

    # ------------------------------------------------------------
    # Drill-down 问题生成
    # ------------------------------------------------------------

    def _generate_drill_down_questions(
        self,
        gaps: List[CoverageGap],
        results: List[Any],
    ) -> List[str]:
        """
        根据覆盖空白生成新的子问题

        实际的问题生成由 Claude LLM 完成（基于已有结果和空白）。
        本方法提供基于规则的初始建议。
        """
        questions = []
        for gap in gaps:
            if gap.priority == 'high':
                questions.append(gap.suggested_question)

        # 基于已有结果生成更深入的问题
        # 例如：如果发现了"FastAPI 性能好"，可以深入问"在什么场景下性能好"
        if len(results) > 5:
            questions.append('基于已有发现，深入分析原因和机制')

        return questions

    # ------------------------------------------------------------
    # 决策：是否继续
    # ------------------------------------------------------------

    def _should_continue(
        self,
        round_num: int,
        coverage_score: float,
        gaps: List[CoverageGap],
        results_count: int,
        history: Optional[Any] = None,
    ) -> tuple:
        """
        决定是否继续深入（v5.1 多信号停止判断，对齐 Kimi 反思机制）

        停止信号（满足任一即停止）：
        1. 硬上限：达到最大反思轮次
        2. 覆盖率达标：coverage_score >= threshold
        3. 边际收益递减：连续两轮覆盖率提升 < 5%（对齐 Kimi 信息增量判断）
        4. 无高优先级空白且覆盖率 >= 0.6
        5. 无覆盖空白

        继续信号：
        - 结果太少（< 5 条）
        - 存在高优先级覆盖空白
        - 覆盖率低于阈值

        Args:
            round_num: 当前反思轮次（0 起算）
            coverage_score: 当前覆盖率 0-1
            gaps: 覆盖空白列表
            results_count: 当前结果总数
            history: 反思历史（v5.1 新增，用于边际收益判断）

        Returns:
            (should_drill_down: bool, stop_reason: str, drill_down_reason: str)
        """
        # 1. 硬上限（保留）
        if round_num >= self.max_rounds - 1:
            return False, f'已达到最大反思轮次（{self.max_rounds} 轮）', ''

        # 2. 覆盖率达标（保留）
        if coverage_score >= self.coverage_threshold:
            return False, f'覆盖率已达标（{coverage_score:.0%}）', ''

        # 3. 边际收益递减判断（v5.1 新增，对齐 Kimi）
        #    连续两轮覆盖率提升 < 5% 且覆盖率 >= 0.6 → 视为收敛，停止
        if history and hasattr(history, 'reflections') and len(history.reflections) >= 2:
            prev_cov = history.reflections[-2].coverage_score
            curr_cov = history.reflections[-1].coverage_score
            delta = curr_cov - prev_cov
            if delta < 0.05 and coverage_score >= 0.6:
                return False, f'覆盖率边际收益递减（+{delta:.0%}），视为收敛', ''

        # 4. 无高优先级空白且覆盖率 >= 0.6 → 停止（v5.1 新增）
        high_gaps = [g for g in gaps if g.priority == 'high']
        if not high_gaps and coverage_score >= 0.6:
            return False, '无高优先级空白且覆盖率达标', ''

        # 5. 结果太少（保留）
        if results_count < 5:
            return True, '', f'结果数量不足（{results_count} 条），需要继续搜索'

        # 6. 有高优先级空白（保留）
        if high_gaps:
            return True, '', f'存在 {len(high_gaps)} 个高优先级覆盖空白'

        # 7. 无明确空白（保留）
        if not gaps:
            return False, '无覆盖空白', ''

        # 8. 默认继续
        return True, '', f'覆盖率 {coverage_score:.0%} 低于阈值 {self.coverage_threshold:.0%}'

    # ------------------------------------------------------------
    # 改进建议
    # ------------------------------------------------------------

    def _generate_suggestions(
        self,
        coverage_score: float,
        gaps: List[CoverageGap],
        verified_count: int,
        single_count: int,
        contradiction_count: int,
    ) -> List[str]:
        """生成改进建议"""
        suggestions = []

        if coverage_score < 0.5:
            suggestions.append('覆盖率较低，建议扩大搜索范围或调整关键词')

        if single_count > verified_count:
            suggestions.append(f'单源结论较多（{single_count} 条），需要寻找更多独立来源进行交叉验证')

        if contradiction_count > 0:
            suggestions.append(f'存在 {contradiction_count} 个矛盾点，需要分析原因并给出平衡的结论')

        # 按优先级排序空白
        high_gaps = [g for g in gaps if g.priority == 'high']
        medium_gaps = [g for g in gaps if g.priority == 'medium']
        if high_gaps:
            suggestions.append(f'优先补充：{", ".join(g.dimension for g in high_gaps[:3])}')
        if medium_gaps:
            suggestions.append(f'建议补充：{", ".join(g.dimension for g in medium_gaps[:3])}')

        return suggestions

    # ------------------------------------------------------------
    # LLM 反思提示
    # ------------------------------------------------------------

    @staticmethod
    def get_llm_reflect_prompt(
        plan: Any,
        results: List[Any],
        gaps: List[CoverageGap],
        round_num: int,
    ) -> str:
        """生成 LLM 反思的提示词"""
        # 提取计划信息
        topic = getattr(plan, 'topic', '') if plan else ''
        dimensions = getattr(plan, 'dimensions', []) if plan else []

        # 结果摘要
        results_summary = []
        for r in results[:10]:  # 只取前 10 条
            title = r.title if hasattr(r, 'title') else r.get('title', '')
            source = r.source if hasattr(r, 'source') else r.get('source', '')
            results_summary.append(f"- [{source}] {title}")
        results_text = '\n'.join(results_summary)

        # 空白摘要
        gaps_text = '\n'.join(f"- [{g.priority}] {g.dimension}: {g.reason}" for g in gaps)

        return f"""请基于以下信息进行深度调研反思：

调研主题: {topic}
调研维度: {', '.join(dimensions)}
当前轮次: 第 {round_num + 1} 轮

已收集结果（前 10 条）:
{results_text}

覆盖空白:
{gaps_text}

请分析：
1. 已有结果是否充分回答了调研问题？
2. 哪些维度需要更深入的调查？
3. 应该生成哪些新的子问题来 Drill-down？
4. 是否需要使用不同的数据源或搜索策略？

请以 JSON 格式返回：
{{
  "coverage_assessment": "覆盖率评估说明",
  "new_subquestions": ["新子问题1", "新子问题2"],
  "should_drill_down": true/false,
  "reason": "继续或停止的原因",
  "suggestions": ["改进建议1", "改进建议2"]
}}
"""


# ============================================================
# 便捷函数
# ============================================================

def reflect_on_results(
    plan: Any,
    results: List[Any],
    round_num: int = 0,
    verification_result: Optional[Any] = None,
    max_rounds: int = 3,
) -> Reflection:
    """便捷函数：对结果进行反思"""
    reflector = Reflector(max_rounds=max_rounds)
    return reflector.reflect(plan, results, round_num, verification_result)


# ============================================================
# CLI 入口
# ============================================================

def _main():
    """命令行入口"""
    import json

    # 简单测试
    class MockPlan:
        topic = "FastAPI vs Django"
        dimensions = ['性能', '生态', '学习曲线']
        issue_tree = []

    mock_results = [
        type('R', (), {
            'title': 'FastAPI 性能测试',
            'source': 'tavily',
            'content': 'FastAPI 性能比 Flask 快 3 倍',
            'craap_score': {'grade': 'high', 'total': 85},
        })(),
        type('R', (), {
            'title': 'Django 生态成熟',
            'source': 'websearch',
            'content': 'Django 有丰富的第三方包',
            'craap_score': {'grade': 'medium', 'total': 60},
        })(),
    ]

    reflector = Reflector(max_rounds=3)
    reflection = reflector.reflect(MockPlan(), mock_results, 0)
    print(json.dumps(reflection.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
