#!/usr/bin/env python3
"""
Deep Research Ultra v4.0 — 交叉验证系统

实现核心原则：同一结论需 ≥2 个独立来源支持

功能：
- Claim（结论）提取：从搜索结果中提取关键结论
- 来源独立性判断：同一域名/同一作者视为同一来源
- 交叉验证：检查结论是否被多个独立来源支持
- 矛盾点检测：发现相互矛盾的结论
- 输出三类结论：
  1. verified_claims: 已验证（≥2 独立来源支持）
  2. single_source_claims: 单源结论（待确认）
  3. contradictions: 矛盾点（来源间相互冲突）

修复 v3.2.0 的问题：
- v3 只做 URL/标题去重，没有真正的交叉验证
  → v4 实现基于结论的交叉验证
- v3 没有矛盾点标注
  → v4 显式标注矛盾点

使用方式：
    verifier = CrossVerifier()
    result = verifier.verify(results, query="FastAPI 性能")
    # result 包含 verified_claims / single_source_claims / contradictions
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from urllib.parse import urlparse


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Claim:
    """
    结论（从搜索结果中提取的关键论点）

    每个结论关联多个证据（Evidence），形成 CER 结构：
    - Claim: 结论
    - Evidence: 证据
    - Reasoning: 推理链
    """
    id: str                                            # 唯一标识
    statement: str                                     # 结论陈述
    evidence: List['Evidence'] = field(default_factory=list)  # 支持证据
    status: str = 'pending'                            # pending/verified/single/contradicted
    confidence: float = 0.0                            # 置信度（0-1）
    contradictions: List[str] = field(default_factory=list)  # 矛盾结论 ID

    def add_evidence(self, ev: 'Evidence') -> None:
        self.evidence.append(ev)

    def get_sources(self) -> Set[str]:
        """获取所有证据来源的域名"""
        return {ev.source_domain for ev in self.evidence}

    def get_independent_source_count(self) -> int:
        """获取独立来源数"""
        return len(self.get_sources())

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'statement': self.statement,
            'evidence': [e.to_dict() for e in self.evidence],
            'status': self.status,
            'confidence': round(self.confidence, 2),
            'independent_sources': self.get_independent_source_count(),
            'contradictions': self.contradictions,
        }


@dataclass
class Evidence:
    """证据"""
    source_url: str                # 来源 URL
    source_domain: str             # 来源域名
    source_title: str = ''         # 来源标题
    source_author: str = ''        # 来源作者
    quote: str = ''                # 原文引用
    reasoning: str = ''            # 推理链（为什么支持结论）
    craap_score: float = 0.0       # 来源的 CRAAP 评分
    published_date: str = ''       # 发布日期

    def to_dict(self) -> Dict:
        return {
            'source_url': self.source_url,
            'source_domain': self.source_domain,
            'source_title': self.source_title,
            'source_author': self.source_author,
            'quote': self.quote,
            'reasoning': self.reasoning,
            'craap_score': self.craap_score,
            'published_date': self.published_date,
        }


@dataclass
class Contradiction:
    """矛盾点"""
    claim_a_id: str                # 结论 A 的 ID
    claim_b_id: str                # 结论 B 的 ID
    claim_a: str                   # 结论 A 陈述
    claim_b: str                   # 结论 B 陈述
    possible_reason: str = ''      # 可能的矛盾原因
    sources_a: List[str] = field(default_factory=list)  # A 的来源
    sources_b: List[str] = field(default_factory=list)  # B 的 来源

    def to_dict(self) -> Dict:
        return {
            'claim_a_id': self.claim_a_id,
            'claim_b_id': self.claim_b_id,
            'claim_a': self.claim_a,
            'claim_b': self.claim_b,
            'possible_reason': self.possible_reason,
            'sources_a': self.sources_a,
            'sources_b': self.sources_b,
        }


@dataclass
class VerificationResult:
    """验证结果"""
    query: str                                               # 原始查询
    verified_claims: List[Claim] = field(default_factory=list)        # 已验证结论
    single_source_claims: List[Claim] = field(default_factory=list)   # 单源结论
    contradictions: List[Contradiction] = field(default_factory=list) # 矛盾点
    total_results: int = 0                                   # 总结果数
    total_claims: int = 0                                    # 总结论数
    verification_rate: float = 0.0                           # 验证率
    created_at: str = ''                                     # 创建时间

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            'query': self.query,
            'verified_claims': [c.to_dict() for c in self.verified_claims],
            'single_source_claims': [c.to_dict() for c in self.single_source_claims],
            'contradictions': [c.to_dict() for c in self.contradictions],
            'total_results': self.total_results,
            'total_claims': self.total_claims,
            'verification_rate': round(self.verification_rate, 2),
            'created_at': self.created_at,
        }

    def summary(self) -> Dict:
        """摘要"""
        return {
            'total_results': self.total_results,
            'total_claims': self.total_claims,
            'verified': len(self.verified_claims),
            'single_source': len(self.single_source_claims),
            'contradictions': len(self.contradictions),
            'verification_rate': f"{self.verification_rate * 100:.1f}%",
        }


# ============================================================
# 交叉验证器
# ============================================================

class CrossVerifier:
    """
    交叉验证器

    工作流程：
    1. 从搜索结果中提取结论（由 Claude LLM 完成）
    2. 判断来源独立性（基于域名）
    3. 对相同/相似结论进行聚合
    4. 检测矛盾点
    5. 分类输出：verified / single_source / contradictions
    """

    # 同一域名视为同一来源
    # 这些域名下的不同子域名视为独立来源
    INDEPENDENT_SUBDOMAINS = {
        'github.com': {'gist.github.com'},  # GitHub Gist 与主站独立
        'medium.com': set(),  # 不同子域名视为同一来源
    }

    def __init__(self, min_sources_for_verification: int = 2):
        """
        Args:
            min_sources_for_verification: 验证所需的最少独立来源数（默认 2）
        """
        self.min_sources = min_sources_for_verification

    # ------------------------------------------------------------
    # 来源独立性判断
    # ------------------------------------------------------------

    @staticmethod
    def get_domain(url: str) -> str:
        """提取域名（去掉子域名）"""
        if not url:
            return ''
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            # 去掉 www. 前缀
            if domain.startswith('www.'):
                domain = domain[4:]
            # 提取主域名（最后两段）
            parts = domain.split('.')
            if len(parts) > 2:
                # 处理 .co.jp / .com.cn 等特殊情况
                if parts[-2] in ['co', 'com', 'org', 'net', 'gov', 'edu']:
                    return '.'.join(parts[-3:])
                return '.'.join(parts[-2:])
            return domain
        except Exception:
            return url

    def is_independent_source(self, url_a: str, url_b: str) -> bool:
        """判断两个 URL 是否为独立来源"""
        domain_a = self.get_domain(url_a)
        domain_b = self.get_domain(url_b)
        if domain_a != domain_b:
            return True
        # 同一域名，检查是否在独立子域名列表中
        for main_domain, independent_subs in self.INDEPENDENT_SUBDOMAINS.items():
            if main_domain in domain_a:
                for sub in independent_subs:
                    if sub in url_a or sub in url_b:
                        return True
        return False

    # ------------------------------------------------------------
    # 结论提取（由 Claude 完成）
    # ------------------------------------------------------------

    def extract_claims(self, results: List[Any], query: str = '') -> List[Claim]:
        """
        从搜索结果中提取结论

        注意：实际的结论提取由 Claude LLM 完成（语义理解）。
        本方法提供骨架和启发式规则，Claude 可以在此基础上补充。

        启发式规则：
        - 包含数字/数据的句子
        - 包含比较/结论性词汇的句子
        - 标题本身（通常是核心论点）
        """
        claims = []
        claim_counter = 0

        for result in results:
            # 提取字段
            if hasattr(result, 'title'):
                title = result.title
                url = result.url
                content = result.content
                author = getattr(result, 'author', '')
                published_date = getattr(result, 'published_date', '')
                craap_score = (
                    result.craap_score.get('total', 0)
                    if getattr(result, 'craap_score', None)
                    else 0
                )
            else:
                title = result.get('title', '')
                url = result.get('url', '')
                content = result.get('content', '')
                author = result.get('author', '')
                published_date = result.get('published_date', '')
                craap_score = result.get('craap_score', {}).get('total', 0)

            domain = self.get_domain(url)

            # 标题作为结论
            if title:
                claim_counter += 1
                claim = Claim(
                    id=f"claim_{claim_counter}",
                    statement=title,
                )
                claim.add_evidence(Evidence(
                    source_url=url,
                    source_domain=domain,
                    source_title=title,
                    source_author=author,
                    quote=content[:200] if content else '',
                    craap_score=craap_score,
                    published_date=published_date,
                ))
                claims.append(claim)

            # 从内容提取结论性句子
            if content:
                # 按句号分割
                sentences = re.split(r'[。.！!？?]', content)
                for sentence in sentences:
                    sentence = sentence.strip()
                    if len(sentence) < 10:
                        continue
                    # 包含数字/数据
                    if re.search(r'\d+(\.\d+)?%|\d+次|\d+倍|\d+年', sentence):
                        claim_counter += 1
                        claim = Claim(
                            id=f"claim_{claim_counter}",
                            statement=sentence[:200],
                        )
                        claim.add_evidence(Evidence(
                            source_url=url,
                            source_domain=domain,
                            source_title=title,
                            source_author=author,
                            quote=sentence,
                            craap_score=craap_score,
                            published_date=published_date,
                        ))
                        claims.append(claim)

        return claims

    # ------------------------------------------------------------
    # 结论聚合与验证
    # ------------------------------------------------------------

    def verify(self, results: List[Any], query: str = '',
               claims: Optional[List[Claim]] = None) -> VerificationResult:
        """
        执行交叉验证

        Args:
            results: 搜索结果列表
            query: 原始查询
            claims: 预提取的结论列表（如不提供则自动提取）

        Returns:
            VerificationResult
        """
        if claims is None:
            claims = self.extract_claims(results, query)

        # 聚合相似结论（基于关键词重叠）
        claim_groups = self._group_similar_claims(claims)

        # 分类
        verified = []
        single_source = []
        contradictions = []

        for group in claim_groups:
            if len(group) == 1:
                # 单条结论
                claim = group[0]
                if claim.get_independent_source_count() >= self.min_sources:
                    claim.status = 'verified'
                    claim.confidence = min(1.0, 0.5 + 0.1 * claim.get_independent_source_count())
                    verified.append(claim)
                else:
                    claim.status = 'single'
                    claim.confidence = 0.3
                    single_source.append(claim)
            else:
                # 多条相似结论，合并
                merged = self._merge_claims(group)
                if merged.get_independent_source_count() >= self.min_sources:
                    merged.status = 'verified'
                    merged.confidence = min(1.0, 0.5 + 0.15 * merged.get_independent_source_count())
                    verified.append(merged)
                else:
                    merged.status = 'single'
                    merged.confidence = 0.4
                    single_source.append(merged)

        # 检测矛盾点
        contradictions = self._detect_contradictions(verified + single_source)

        # 标记矛盾结论
        for con in contradictions:
            for claim in verified + single_source:
                if claim.id in (con.claim_a_id, con.claim_b_id):
                    claim.status = 'contradicted'
                    if con.claim_a_id == claim.id:
                        claim.contradictions.append(con.claim_b_id)
                    else:
                        claim.contradictions.append(con.claim_a_id)

        # 重新分类（矛盾结论从 verified/single 中移除）
        verified = [c for c in verified if c.status == 'verified']
        single_source = [c for c in single_source if c.status == 'single']
        contradicted = [c for c in verified + single_source if c.status == 'contradicted']

        # 计算验证率
        total_claims = len(verified) + len(single_source) + len(contradicted)
        verification_rate = (len(verified) / total_claims) if total_claims > 0 else 0.0

        return VerificationResult(
            query=query,
            verified_claims=verified,
            single_source_claims=single_source,
            contradictions=contradictions,
            total_results=len(results),
            total_claims=total_claims,
            verification_rate=verification_rate,
        )

    def _group_similar_claims(self, claims: List[Claim]) -> List[List[Claim]]:
        """聚合相似结论（基于关键词重叠）"""
        if not claims:
            return []

        groups = []
        used = set()

        for i, claim_a in enumerate(claims):
            if i in used:
                continue
            group = [claim_a]
            used.add(i)

            for j in range(i + 1, len(claims)):
                if j in used:
                    continue
                claim_b = claims[j]
                if self._are_claims_similar(claim_a, claim_b):
                    group.append(claim_b)
                    used.add(j)

            groups.append(group)

        return groups

    @staticmethod
    def _are_claims_similar(claim_a: Claim, claim_b: Claim, threshold: float = 0.5) -> bool:
        """判断两个结论是否相似（基于字符级 Jaccard 相似度）"""
        # 提取关键词（2-gram）
        def _get_keywords(text: str) -> Set[str]:
            text = text.lower()
            # 英文单词
            words = set(re.findall(r'[a-z]+', text))
            # 中文 2-gram
            chinese = re.findall(r'[\u4e00-\u9fff]', text)
            for i in range(len(chinese) - 1):
                words.add(chinese[i] + chinese[i + 1])
            return words

        kw_a = _get_keywords(claim_a.statement)
        kw_b = _get_keywords(claim_b.statement)
        if not kw_a or not kw_b:
            return False
        intersection = kw_a & kw_b
        union = kw_a | kw_b
        similarity = len(intersection) / len(union)
        return similarity >= threshold

    @staticmethod
    def _merge_claims(claims: List[Claim]) -> Claim:
        """合并相似结论"""
        merged = Claim(
            id=claims[0].id,
            statement=claims[0].statement,
        )
        for c in claims:
            for ev in c.evidence:
                merged.add_evidence(ev)
        return merged

    def _detect_contradictions(self, claims: List[Claim]) -> List[Contradiction]:
        """
        检测矛盾点

        启发式规则：
        - 包含对立词汇（好/坏、优/劣、推荐/不推荐）
        - 数值差异大（如性能数据）
        - 实际矛盾检测由 Claude LLM 完成
        """
        contradictions = []

        # 对立词汇对
        opposite_pairs = [
            ('好', '坏'), ('优', '劣'), ('推荐', '不推荐'), ('适合', '不适合'),
            ('快', '慢'), ('安全', '不安全'), ('稳定', '不稳定'),
            ('good', 'bad'), ('recommend', 'not recommend'),
            ('fast', 'slow'), ('secure', 'insecure'),
        ]

        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                claim_a = claims[i]
                claim_b = claims[j]
                # 检查是否包含对立词汇
                for word_a, word_b in opposite_pairs:
                    if word_a in claim_a.statement and word_b in claim_b.statement:
                        # 进一步检查是否讨论相同主题
                        if self._are_claims_similar(claim_a, claim_b, threshold=0.3):
                            contradictions.append(Contradiction(
                                claim_a_id=claim_a.id,
                                claim_b_id=claim_b.id,
                                claim_a=claim_a.statement,
                                claim_b=claim_b.statement,
                                possible_reason=f'可能因"{word_a}"与"{word_b}"的立场差异',
                                sources_a=list(claim_a.get_sources()),
                                sources_b=list(claim_b.get_sources()),
                            ))
                            break

        return contradictions

    # ------------------------------------------------------------
    # LLM 矛盾检测提示
    # ------------------------------------------------------------

    @staticmethod
    def get_contradiction_detection_prompt(claims: List[Claim]) -> str:
        """生成矛盾检测的 LLM 提示词"""
        claims_text = '\n'.join(
            f"- [{c.id}] {c.statement}"
            for c in claims
        )
        return f"""请分析以下结论列表，找出相互矛盾的结论对：

结论列表：
{claims_text}

请以 JSON 格式返回矛盾对：
{{
  "contradictions": [
    {{
      "claim_a_id": "...",
      "claim_b_id": "...",
      "reason": "矛盾原因说明"
    }}
  ]
}}

注意：
1. 只有真正相互矛盾的结论才算（不能只是"不同视角"）
2. 数值差异大于 20% 的结论视为矛盾
3. 明确的立场对立（推荐 vs 不推荐）视为矛盾
"""


# ============================================================
# 便捷函数
# ============================================================

def verify_results(results: List[Any], query: str = '',
                   min_sources: int = 2) -> VerificationResult:
    """便捷函数：交叉验证搜索结果"""
    verifier = CrossVerifier(min_sources_for_verification=min_sources)
    return verifier.verify(results, query)


# ============================================================
# CLI 入口
# ============================================================

def _main():
    """命令行入口"""
    import json
    import sys

    # 从 stdin 读取结果
    if len(sys.argv) > 1:
        query = sys.argv[1]
    else:
        query = ''

    # 简单测试
    test_results = [
        {'title': 'FastAPI 性能优异', 'url': 'https://example.com/a', 'content': 'FastAPI 性能比 Flask 快 3 倍'},
        {'title': 'FastAPI 性能测试', 'url': 'https://test.com/b', 'content': 'FastAPI 性能比 Flask 快 2.8 倍'},
        {'title': 'Flask 更适合小项目', 'url': 'https://blog.com/c', 'content': 'Flask 简单易用，适合小项目'},
    ]

    verifier = CrossVerifier()
    result = verifier.verify(test_results, query or 'FastAPI 性能')
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
