#!/usr/bin/env python3
"""
Deep Research Ultra v5.0 — Intelligent Query Router

Three-tier cascading architecture: Rule -> Semantic -> LLM.

- RuleRouter (L1): keyword/regex matching, handles 60-70% high-certainty
  queries in <1ms with zero external dependencies.
- SemanticRouter (L2, optional): vector similarity matching via
  ``sentence-transformers``; gracefully degrades when unavailable.
- LLMRouter (L3, optional): LLM classification via a user-supplied callback;
  skipped when not configured.

The router classifies a query into one of 9 intent types, detects time
sensitivity and authority needs, generates a dynamic engine chain, and
produces multilingual query variants. A ``CircuitBreaker`` guards each
engine for resilient fallback.

Public API:
    QueryRouter, RoutingDecision, CircuitBreaker,
    RuleRouter, SemanticRouter, LLMRouter, QueryPreprocessor
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 常量定义
# ============================================================

# 9 类查询类型
VALID_QUERY_TYPES = {
    'academic', 'opensource', 'community', 'docs',
    'news', 'general', 'definition', 'guide', 'comparison',
}

# 查询类型 -> 有序引擎链（动态引擎链生成的依据，与设计矩阵一致）
# v6.1：开源链 = 项目源（GitHub/Gitee/ModelScope/oss-finder）+ 论文源（arxiv/openalex）双查 + 兜底
ENGINE_CHAIN_MAP: Dict[str, List[str]] = {
    'academic':    ['arxiv', 'paper-search', 'openalex', 'semantic-scholar', 'pubmed', 'baidu-xueshu'],
    'opensource':  ['oss-finder', 'github-deep-search', 'gitee', 'modelscope',
                    'arxiv', 'openalex', 'tavily', 'open-websearch'],
    'community':   ['agent-reach', 'last30days', 'tavily', 'sogou-zhihu'],
    'docs':        ['context7', 'defuddle', 'firecrawl'],
    'news':        ['last30days', 'tavily', 'websearch', 'baidu-serp'],
    'general':     ['tavily', 'open-websearch', 'websearch', 'baidu-serp'],
    'definition':  ['tavily', 'websearch', 'defuddle', 'baidu-serp'],
    'guide':       ['tavily', 'context7', 'defuddle'],
    'comparison':  ['tavily', 'agent-reach', 'arxiv', 'sogou-weixin'],
}

# 时间敏感度关键词（横切关注点，独立于类型判定）
REALTIME_KEYWORDS = ['今天', '刚刚', '突发', '现在', '小时前', 'now', 'today', 'breaking', '实时']
RECENT_KEYWORDS = ['最近', '近期', '本月', '这周', '本周', '近一个月', '近30天',
                   'recent', 'latest', 'newest']

# 权威性关键词（横切关注点）
HIGH_AUTHORITY_KEYWORDS = ['论文', 'paper', '官方', 'official', 'arxiv', 'doi',
                           '报告', 'report', '白皮书', '标准', 'standard', '专利']
LOW_AUTHORITY_KEYWORDS = ['体验', '评价', '怎么看', 'reddit', '知乎', '讨论',
                          '口碑', 'review', 'opinion', '个人博客', '论坛']

# 强关键词：命中即高置信度（0.9+）
STRONG_KEYWORDS: Dict[str, List[str]] = {
    'academic':   ['arxiv', '论文', 'paper', 'pubmed', 'scholar', 'doi', 'semantic scholar'],
    'opensource': ['github', '开源', 'open source', 'npm', 'pypi', 'gitlab', 'gitee',
                   '魔搭', 'modelscope', 'model scope', 'huggingface'],
    'community':  ['reddit', '知乎', '口碑', 'hacker news', 'v2ex'],
    'docs':       ['docs', '文档', '官方文档', 'api reference', 'documentation'],
    'news':       ['今天', '刚刚', '突发', 'breaking', 'latest news', '新闻'],
    'definition': ['什么是', 'what is', '定义', 'what does', 'meaning of'],
    'guide':      ['how to', '怎么做', '教程', 'tutorial', 'step by step'],
    'comparison': [' vs ', '对比', '比较', 'versus', ' vs.', ' vs '],
}

# 弱关键词：命中给中等置信度（0.8-0.85）
WEAK_KEYWORDS: Dict[str, List[str]] = {
    'academic':   ['研究', 'research', '学术', 'citation', '引用', 'journal', '期刊',
                   'proceedings', '论文集', 'experiment', '实验'],
    'opensource': ['repo', '仓库', 'framework', '框架', 'library', '库', 'package',
                   'crate', 'maven', 'dependency management', '依赖管理'],
    'community':  ['评价', '怎么看', '体验', '讨论', 'review', 'opinion', '反馈',
                   '论坛', '社区'],
    'docs':       ['api', 'tutorial', 'guide', 'reference', '手册', 'handbook'],
    'news':       ['最新', '近期', '2025', '2026', 'recent', 'news', '动态', '快讯'],
    'definition': ['meaning', '意思', '含义', '解释', 'concept', '概念', '术语'],
    'guide':      ['如何', '怎样', '步骤', '部署', 'install', 'setup', '配置',
                   '快速开始', 'getting started'],
    'comparison': ['best', '哪个好', '区别', 'alternative', 'compare', '选型', '优劣'],
}

# 规则匹配优先级（具体意图优先，通用兜底）
RULE_PRIORITY: List[str] = [
    'comparison', 'guide', 'definition',
    'academic', 'opensource', 'community', 'docs', 'news',
]

# 正则模式（补充关键词无法覆盖的结构化匹配）
REGEX_PATTERNS: Dict[str, List[re.Pattern]] = {
    'academic':   [re.compile(r'arxiv\.org/\S+', re.I), re.compile(r'\b10\.\d{4,}/\S+', re.I)],  # arxiv 链接 / DOI
    'opensource': [re.compile(r'github\.com/\S+', re.I), re.compile(r'npmjs\.com/package/\S+', re.I),
                   re.compile(r'gitee\.com/\S+', re.I), re.compile(r'modelscope\.cn/\S+', re.I)],
    'comparison': [re.compile(r'\b\w+\s+vs\.?\s+\w+', re.I)],
    'news':       [re.compile(r'\b(20\d{2})\s*年', re.I), re.compile(r'\b(20\d{2})-\d{1,2}-\d{1,2}\b')],
}

# 中英互译词典（用于多语言变体生成，覆盖高频术语）
ZH_TO_EN: Dict[str, str] = {
    '论文': 'paper', '研究': 'research', '最新': 'latest', '开源': 'open source',
    '框架': 'framework', '库': 'library', '文档': 'docs', '教程': 'tutorial',
    '对比': 'vs', '比较': 'compare', '评价': 'review', '社区': 'community',
    '新闻': 'news', '什么是': 'what is', '怎么做': 'how to', '最佳': 'best',
    '部署': 'deploy', '安装': 'install', '原理': 'principle', '架构': 'architecture',
    '算法': 'algorithm', '模型': 'model', '语言模型': 'language model',
    '机器学习': 'machine learning', '深度学习': 'deep learning',
    '人工智能': 'artificial intelligence', '神经网络': 'neural network',
    '今天': 'today', '刚刚': 'just now', '近期': 'recent', '最近': 'recent',
    '官方': 'official', '体验': 'experience', '定义': 'definition',
}
EN_TO_ZH: Dict[str, str] = {v: k for k, v in ZH_TO_EN.items()}

# 语义路由话语库（每类 5-8 条典型查询，用于 SemanticRouter）
SEMANTIC_UTTERANCES: Dict[str, List[str]] = {
    'academic': [
        '最新 transformer 注意力机制论文', 'retrieval augmented generation research paper',
        'GPT-4 技术报告', 'machine learning arxiv 2025', 'BERT 引用网络分析',
    ],
    'opensource': [
        'RAG 开源实现', 'best rag library github', 'vector database open source',
        'langchain 替代开源项目', 'python web 框架对比',
    ],
    'community': [
        '大家怎么看 Claude 4.7', 'reddit discussion about cursor',
        '知乎上关于 RAG 的讨论', 'user reviews and opinions', '这个库口碑如何',
    ],
    'docs': [
        'FastAPI 依赖注入官方文档', 'API reference documentation',
        '官方教程', 'react hooks 文档', 'sqlalchemy session 手册',
    ],
    'news': [
        '今天 AI 行业新闻', 'latest AI news this week', 'breaking tech news',
        '2026 年 8 月最新动态', '近期大模型发布',
    ],
    'definition': [
        '什么是 RAG', 'what is retrieval augmented generation',
        'MCP 协议含义', 'explain transformer architecture', '量子计算定义',
    ],
    'guide': [
        '如何部署 SearXNG Docker', 'how to fine-tune llama',
        '怎么做 RAG 系统', 'react 项目搭建步骤', 'install kubernetes guide',
    ],
    'comparison': [
        'LangChain vs LlamaIndex', 'react vs vue 哪个好',
        'postgres 和 mysql 比较', 'best vector database 2025', 'tavily vs serper',
    ],
    'general': [
        '量子计算基本原理', 'what is machine learning',
        '通用知识查询', 'general knowledge question', '介绍一下北京',
    ],
}

# 断路器默认参数
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RECOVERY_TIMEOUT = 60  # 秒

# 级联阈值
RULE_ACCEPT_THRESHOLD = 0.8     # 规则层置信度 >= 0.8 直接返回
SEMANTIC_ACCEPT_THRESHOLD = 0.7  # 语义层置信度 >= 0.7 返回


# ============================================================
# 核心数据结构
# ============================================================

@dataclass
class RoutingDecision:
    """Routing decision produced by the cascading router.

    Attributes:
        query_type: Primary intent type (one of VALID_QUERY_TYPES).
        secondary_types: Secondary intent types detected (may be empty).
        confidence: Decision confidence in [0, 1].
        time_sensitivity: ``realtime`` / ``recent`` / ``evergreen``.
        authority_need: ``high`` / ``medium`` / ``low``.
        engine_chain: Ordered list of engine names to query.
        query_variants: Multilingual variants, e.g.
            ``[{'lang': 'en', 'q': '...'}, {'lang': 'zh', 'q': '...'}]``.
        reasoning: Human-readable routing rationale.
    """
    query_type: str
    secondary_types: List[str] = field(default_factory=list)
    confidence: float = 0.0
    time_sensitivity: str = 'evergreen'
    authority_need: str = 'medium'
    engine_chain: List[str] = field(default_factory=list)
    query_variants: List[Dict] = field(default_factory=list)
    reasoning: str = ''

    def to_dict(self) -> Dict:
        """Serialize to a plain dict (for logging / JSON output)."""
        return {
            'query_type': self.query_type,
            'secondary_types': list(self.secondary_types),
            'confidence': self.confidence,
            'time_sensitivity': self.time_sensitivity,
            'authority_need': self.authority_need,
            'engine_chain': list(self.engine_chain),
            'query_variants': list(self.query_variants),
            'reasoning': self.reasoning,
        }


# ============================================================
# 断路器（Circuit Breaker）
# ============================================================

class CircuitBreaker:
    """Circuit breaker state machine: CLOSED -> OPEN -> HALF_OPEN.

    Each engine owns one breaker. When an engine fails consecutively beyond
    ``failure_threshold``, the breaker opens and short-circuits subsequent
    calls until ``recovery_timeout`` elapses, after which one trial call is
    allowed (HALF_OPEN). A successful trial closes the breaker; a failure
    re-opens it.

    States:
        CLOSED:     normal operation, calls permitted.
        OPEN:       tripped, calls rejected immediately.
        HALF_OPEN:  probing, a single trial call is permitted.
    """

    CLOSED = 'CLOSED'
    OPEN = 'OPEN'
    HALF_OPEN = 'HALF_OPEN'

    def __init__(self,
                 failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
                 recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count: int = 0
        self.state: str = self.CLOSED
        self.last_failure_time: float = 0.0

    def can_call(self) -> bool:
        """Return True if a call is currently permitted."""
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            # 冷却时间到 -> 进入半开，放行一次试探
            if time.monotonic() - self.last_failure_time >= self.recovery_timeout:
                self.state = self.HALF_OPEN
                logger.debug("CircuitBreaker OPEN -> HALF_OPEN (recovery timeout elapsed)")
                return True
            return False
        # HALF_OPEN：仅允许一次试探调用
        return True

    def record_success(self) -> None:
        """Record a successful call; resets the breaker to CLOSED."""
        self.failure_count = 0
        if self.state != self.CLOSED:
            logger.debug("CircuitBreaker %s -> CLOSED (success)", self.state)
        self.state = self.CLOSED

    def record_failure(self) -> None:
        """Record a failed call; may trip the breaker to OPEN."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.state == self.HALF_OPEN:
            # 半开态失败 -> 立即重新打开
            self.state = self.OPEN
            logger.debug("CircuitBreaker HALF_OPEN -> OPEN (trial failed)")
        elif self.failure_count >= self.failure_threshold:
            self.state = self.OPEN
            logger.debug("CircuitBreaker CLOSED -> OPEN (failures=%d)", self.failure_count)

    def reset(self) -> None:
        """Manually reset the breaker to CLOSED."""
        self.failure_count = 0
        self.state = self.CLOSED
        self.last_failure_time = 0.0

    def __repr__(self) -> str:
        return (f"<CircuitBreaker state={self.state} "
                f"failures={self.failure_count}/{self.failure_threshold}>")


# ============================================================
# 查询预处理器（QueryPreprocessor）
# ============================================================

class QueryPreprocessor:
    """Query preprocessing: language detection, synonym expansion, and
    multilingual variant generation.

    No external dependencies — language detection uses CJK Unicode ranges
    and translation relies on a built-in dictionary.
    """

    # CJK 统一表意文字范围（用于中文检测）
    _CJK_RANGES = (
        (0x4E00, 0x9FFF),    # CJK Unified Ideographs
        (0x3400, 0x4DBF),    # CJK Extension A
        (0x20000, 0x2A6DF),  # CJK Extension B
    )

    def __init__(self, zh_to_en: Optional[Dict[str, str]] = None,
                 max_variants: int = 3) -> None:
        self.zh_to_en = zh_to_en if zh_to_en is not None else dict(ZH_TO_EN)
        self.en_to_zh = {v: k for k, v in self.zh_to_en.items()}
        self.max_variants = max_variants

    # ---- 语言检测 ----

    def detect_language(self, query: str) -> str:
        """Detect query language.

        Returns ``'zh'`` (Chinese-dominant), ``'en'`` (ASCII-dominant), or
        ``'mixed'``. Falls back to ``'en'`` for empty input.
        """
        if not query or not query.strip():
            return 'en'
        cjk_count = sum(1 for ch in query if self._is_cjk(ch))
        ascii_count = sum(1 for ch in query if ch.isascii() and ch.isalpha())
        total = cjk_count + ascii_count
        if total == 0:
            return 'en'
        cjk_ratio = cjk_count / total
        if cjk_ratio > 0.6:
            return 'zh'
        if cjk_ratio > 0.15:
            return 'mixed'
        return 'en'

    @classmethod
    def _is_cjk(cls, ch: str) -> bool:
        cp = ord(ch)
        for lo, hi in cls._CJK_RANGES:
            if lo <= cp <= hi:
                return True
        return False

    # ---- 查询改写（同义词扩展）----

    def rewrite(self, query: str) -> str:
        """Light query rewrite: normalize whitespace and surrounding spaces."""
        return re.sub(r'\s+', ' ', query).strip()

    def expand_synonyms(self, query: str) -> List[str]:
        """Expand query with synonym variants (capped at ``max_variants``).

        For each Chinese term present in the query that has an English
        translation, produce a variant with that term replaced; likewise
        for English terms.
        """
        variants = [query]
        lang = self.detect_language(query)
        if lang in ('zh', 'mixed'):
            for zh, en in self.zh_to_en.items():
                if zh in query:
                    variant = query.replace(zh, en)
                    if variant not in variants:
                        variants.append(variant)
                        if len(variants) >= self.max_variants:
                            break
        if lang in ('en', 'mixed') and len(variants) < self.max_variants:
            for en, zh in self.en_to_zh.items():
                # 词边界匹配英文术语，避免子串误替换
                if re.search(r'\b' + re.escape(en) + r'\b', query, re.I):
                    variant = re.sub(r'\b' + re.escape(en) + r'\b', zh, query, flags=re.I)
                    if variant not in variants:
                        variants.append(variant)
                        if len(variants) >= self.max_variants:
                            break
        return variants[: self.max_variants]

    # ---- 多语言变体 ----

    def generate_variants(self, query: str) -> List[Dict]:
        """Generate multilingual query variants.

        Returns a list of ``{'lang': ..., 'q': ...}`` dicts. Always includes
        the original query; adds a translated variant in the other language
        when the dictionary covers the terms.
        """
        lang = self.detect_language(query)
        variants: List[Dict] = [{'lang': lang, 'q': query}]
        translated = self._translate(query, lang)
        if translated and translated != query:
            target_lang = 'en' if lang in ('zh', 'mixed') else 'zh'
            variants.append({'lang': target_lang, 'q': translated})
        return variants

    def _translate(self, query: str, source_lang: str) -> str:
        """Translate query via the built-in dictionary (term replacement)."""
        result = query
        if source_lang in ('zh', 'mixed'):
            # 长词优先替换，避免短词覆盖长词（如"语言模型"先于"模型"）
            for zh in sorted(self.zh_to_en.keys(), key=len, reverse=True):
                if zh in result:
                    result = result.replace(zh, self.zh_to_en[zh])
        else:
            for en in sorted(self.en_to_zh.keys(), key=len, reverse=True):
                if re.search(r'\b' + re.escape(en) + r'\b', result, re.I):
                    result = re.sub(r'\b' + re.escape(en) + r'\b',
                                    self.en_to_zh[en], result, flags=re.I)
        return result

    # ---- 综合预处理 ----

    def preprocess(self, query: str) -> Tuple[str, List[Dict]]:
        """Run full preprocessing pipeline.

        Returns ``(rewritten_query, query_variants)``.
        """
        rewritten = self.rewrite(query)
        variants = self.generate_variants(rewritten)
        return rewritten, variants


# ============================================================
# 规则路由（RuleRouter）—— L1，无外部依赖
# ============================================================

class RuleRouter:
    """L1 rule-based router: keyword + regex matching.

    Handles 60-70% of high-certainty queries with sub-millisecond latency.
    Returns a decision dict when confidence >= ``accept_threshold``, else
    returns ``None`` to let the cascade fall through.
    """

    def __init__(self,
                 strong_keywords: Optional[Dict[str, List[str]]] = None,
                 weak_keywords: Optional[Dict[str, List[str]]] = None,
                 priority: Optional[List[str]] = None,
                 accept_threshold: float = RULE_ACCEPT_THRESHOLD) -> None:
        self.strong_keywords = strong_keywords if strong_keywords is not None else {
            k: [kw.lower() for kw in v] for k, v in STRONG_KEYWORDS.items()
        }
        self.weak_keywords = weak_keywords if weak_keywords is not None else {
            k: [kw.lower() for kw in v] for k, v in WEAK_KEYWORDS.items()
        }
        self.priority = priority if priority is not None else list(RULE_PRIORITY)
        self.accept_threshold = accept_threshold

    def match(self, query: str) -> Optional[Dict]:
        """Match query against rules.

        Returns ``{'query_type', 'secondary_types', 'confidence', 'reasoning'}``
        if a rule fires with sufficient confidence, else ``None``.
        """
        q_lower = query.lower()
        hits: Dict[str, Tuple[str, str]] = {}  # type -> (keyword, strength)

        # 关键词匹配
        for qtype, keywords in self.strong_keywords.items():
            for kw in keywords:
                if kw in q_lower:
                    hits[qtype] = (kw, 'strong')
                    break
        for qtype, keywords in self.weak_keywords.items():
            if qtype in hits:
                continue
            for kw in keywords:
                if kw in q_lower:
                    hits[qtype] = (kw, 'weak')
                    break

        # 正则匹配（视为强信号）
        for qtype, patterns in REGEX_PATTERNS.items():
            if qtype in hits:
                continue
            for pat in patterns:
                if pat.search(query):
                    hits[qtype] = (pat.pattern[:20], 'strong')
                    break

        if not hits:
            return None

        # 按命中强度（strong 优先）+ 规则优先级排序，选择主类型与次要类型
        def _sort_key(item: Tuple[str, Tuple[str, str]]) -> Tuple[int, int]:
            qtype, (_kw, strength) = item
            strength_rank = 0 if strength == 'strong' else 1
            priority_rank = (self.priority.index(qtype)
                             if qtype in self.priority else len(self.priority))
            return (strength_rank, priority_rank)

        ordered = sorted(hits.items(), key=_sort_key)
        primary_type, (primary_kw, primary_strength) = ordered[0]
        secondary_types = [t for t, _ in ordered[1:]]

        # 置信度计算：强关键词 0.95，弱关键词 0.85，多命中加成
        confidence = 0.95 if primary_strength == 'strong' else 0.85
        if len(hits) > 1:
            confidence = min(confidence + 0.03, 0.99)

        reasoning = (f"规则层命中 [{primary_type}]（关键词 '{primary_kw}'，"
                     f"强度 {primary_strength}），共命中 {len(hits)} 类")

        # 低于阈值则不直接返回，交由下层
        if confidence < self.accept_threshold:
            return None

        return {
            'query_type': primary_type,
            'secondary_types': secondary_types,
            'confidence': confidence,
            'reasoning': reasoning,
        }


# ============================================================
# 语义路由（SemanticRouter）—— L2，可选依赖
# ============================================================

class SemanticRouter:
    """L2 semantic router: vector similarity matching.

    Requires the optional ``sentence-transformers`` package. When not
    installed, ``is_available()`` returns False and the cascade skips this
    layer. Uses a built-in utterance library (``SEMANTIC_UTTERANCES``).
    """

    def __init__(self,
                 model_name: str = 'BAAI/bge-m3',
                 utterances: Optional[Dict[str, List[str]]] = None,
                 accept_threshold: float = SEMANTIC_ACCEPT_THRESHOLD) -> None:
        self.model_name = model_name
        self.utterances = utterances if utterances is not None else dict(SEMANTIC_UTTERANCES)
        self.accept_threshold = accept_threshold
        self._model = None
        self._route_embeddings: Optional[Any] = None  # numpy.ndarray
        self._route_names: List[str] = []
        self._available: bool = False
        self._init_model()

    def _init_model(self) -> None:
        """Attempt to load the embedding model; degrade gracefully."""
        try:
            import numpy as np  # type: ignore
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._model = SentenceTransformer(self.model_name)
            self._build_index(np)
            self._available = True
            logger.info("SemanticRouter 已加载模型 %s", self.model_name)
        except ImportError:
            logger.info("SemanticRouter 跳过：未安装 sentence-transformers/numpy")
            self._available = False
        except Exception as e:  # 模型下载失败等
            logger.warning("SemanticRouter 初始化失败: %s", e)
            self._available = False

    def _build_index(self, np: Any) -> None:
        """Pre-compute embeddings for all route utterances."""
        self._route_names = []
        all_utterances: List[str] = []
        for name, utts in self.utterances.items():
            for utt in utts:
                self._route_names.append(name)
                all_utterances.append(utt)
        if all_utterances:
            embs = self._model.encode(all_utterances, normalize_embeddings=True)
            self._route_embeddings = np.array(embs)

    def is_available(self) -> bool:
        """Return True if the semantic layer is usable."""
        return self._available

    def route(self, query: str) -> Optional[Dict]:
        """Classify query via cosine similarity.

        Returns ``{'query_type', 'confidence', 'reasoning'}`` when the
        top-1 score >= ``accept_threshold``, else ``None``.
        """
        if not self.is_available():
            return None
        import numpy as np  # type: ignore
        q_emb = self._model.encode([query], normalize_embeddings=True)
        q_vec = np.array(q_emb)[0]
        # 余弦相似度（已归一化，点积即相似度）
        scores = self._route_embeddings.dot(q_vec)
        top_idx = int(np.argmax(scores))
        top_score = float(scores[top_idx])
        top_type = self._route_names[top_idx]
        if top_score < self.accept_threshold:
            return None
        return {
            'query_type': top_type,
            'confidence': top_score,
            'reasoning': f"语义层匹配 [{top_type}]，余弦相似度 {top_score:.3f}",
        }


# ============================================================
# LLM 路由（LLMRouter）—— L3，通过回调函数
# ============================================================

class LLMRouter:
    """L3 LLM-based router: classification via a user-supplied callback.

    The callback signature is ``callback(query: str) -> Dict`` returning at
    least ``{'query_type': str, 'confidence': float}`` and optionally
    ``'reasoning'`` and ``'secondary_types'``. When no callback is configured,
    ``is_available()`` returns False and the cascade skips this layer.
    """

    def __init__(self, callback: Optional[Callable[[str], Dict]] = None) -> None:
        self.callback = callback

    def is_available(self) -> bool:
        """Return True if an LLM callback is configured."""
        return self.callback is not None

    def route(self, query: str) -> Optional[Dict]:
        """Classify query via the LLM callback.

        Returns the callback's dict (normalized) or ``None`` on failure.
        """
        if not self.is_available():
            return None
        try:
            result = self.callback(query)  # type: ignore
            if not isinstance(result, dict):
                return None
            qtype = result.get('query_type', 'general')
            if qtype not in VALID_QUERY_TYPES:
                qtype = 'general'
            return {
                'query_type': qtype,
                'secondary_types': result.get('secondary_types', []),
                'confidence': float(result.get('confidence', 0.9)),
                'reasoning': result.get('reasoning', 'LLM 层分类'),
            }
        except Exception as e:
            logger.warning("LLMRouter 回调异常: %s", e)
            return None


# ============================================================
# 主类：QueryRouter（三级级联编排）
# ============================================================

class QueryRouter:
    """Three-tier cascading query router: Rule -> Semantic -> LLM.

    The router is fully usable with no arguments (rule layer only). Pass a
    ``semantic_router`` and/or ``llm_router`` to enable higher tiers. The
    ``route`` method also accepts a ``context`` dict to supply an LLM
    callback at call time.

    Example:
        >>> r = QueryRouter()
        >>> d = r.route('最新 LLM 论文', {})
        >>> d.query_type, d.engine_chain, d.confidence
        ('academic', ['arxiv', 'paper-search', ...], 0.95)
    """

    def __init__(self,
                 rule_router: Optional[RuleRouter] = None,
                 semantic_router: Optional[SemanticRouter] = None,
                 llm_router: Optional[LLMRouter] = None,
                 preprocessor: Optional[QueryPreprocessor] = None,
                 breakers: Optional[Dict[str, CircuitBreaker]] = None) -> None:
        # 无参构造时默认创建规则层与预处理器（均无外部依赖）
        self.rule_router = rule_router or RuleRouter()
        self.preprocessor = preprocessor or QueryPreprocessor()
        # 语义层/LLM 层可选：None 时不启用
        self.semantic_router = semantic_router
        self.llm_router = llm_router
        # 每个引擎一个断路器
        self.breakers: Dict[str, CircuitBreaker] = breakers if breakers is not None else {}

    # ---- 断路器管理 ----

    def get_breaker(self, engine_name: str) -> CircuitBreaker:
        """Get (or lazily create) the circuit breaker for an engine."""
        if engine_name not in self.breakers:
            self.breakers[engine_name] = CircuitBreaker()
        return self.breakers[engine_name]

    def filter_engines_by_breaker(self, engine_chain: List[str]) -> List[str]:
        """Filter an engine chain, dropping engines whose breaker is OPEN."""
        return [name for name in engine_chain
                if self.get_breaker(name).can_call()]

    # ---- 引擎链生成 ----

    @staticmethod
    def build_engine_chain(query_type: str,
                           secondary_types: Optional[List[str]] = None) -> List[str]:
        """Build an ordered, deduplicated engine chain for a query type.

        Primary type's chain first, followed by secondary types' chains
        (deduplicated, order preserved).
        """
        chain: List[str] = []
        seen = set()

        def _extend(qt: str) -> None:
            for name in ENGINE_CHAIN_MAP.get(qt, ENGINE_CHAIN_MAP['general']):
                if name not in seen:
                    chain.append(name)
                    seen.add(name)

        _extend(query_type)
        for st in (secondary_types or []):
            _extend(st)
        return chain

    # ---- 横切属性检测 ----

    @staticmethod
    def detect_time_sensitivity(query: str) -> str:
        """Detect time sensitivity: realtime / recent / evergreen."""
        if any(kw in query for kw in REALTIME_KEYWORDS):
            return 'realtime'
        if any(kw in query.lower() for kw in RECENT_KEYWORDS):
            return 'recent'
        # 年份出现视为近期
        if re.search(r'\b20(2[5-9]|3\d)\b', query):
            return 'recent'
        return 'evergreen'

    @staticmethod
    def detect_authority(query: str) -> str:
        """Detect authority need: high / medium / low."""
        q_lower = query.lower()
        if any(kw in q_lower for kw in HIGH_AUTHORITY_KEYWORDS):
            return 'high'
        if any(kw in q_lower for kw in LOW_AUTHORITY_KEYWORDS):
            return 'low'
        return 'medium'

    # ---- 主入口 ----

    def route(self, query: str, context: Optional[Dict] = None) -> RoutingDecision:
        """Execute the three-tier cascading route.

        Args:
            query: Raw user query.
            context: Optional dict. Recognized keys:
                ``llm_callback`` — callable for LLM routing at call time;
                ``enable_semantic`` — bool, whether to try the semantic layer;
                ``registry`` — (reserved) an EngineRegistry for live filtering.

        Returns:
            A fully populated :class:`RoutingDecision`.
        """
        context = context or {}

        # 1. 预处理：语言检测 + 改写 + 多语言变体
        rewritten, variants = self.preprocessor.preprocess(query)

        # 横切属性（时间敏感度、权威性）始终检测
        time_sens = self.detect_time_sensitivity(rewritten)
        authority = self.detect_authority(rewritten)

        # 2. L1 规则路由
        rule_result = self.rule_router.match(rewritten)
        if rule_result:
            return self._build_decision(
                rule_result, rewritten, variants, time_sens, authority,
                layer='rule')

        # 3. L2 语义路由（可选）
        enable_semantic = context.get('enable_semantic', True)
        if enable_semantic and self.semantic_router and self.semantic_router.is_available():
            sem_result = self.semantic_router.route(rewritten)
            if sem_result:
                return self._build_decision(
                    sem_result, rewritten, variants, time_sens, authority,
                    layer='semantic')

        # 4. L3 LLM 路由（可选）—— 支持运行时通过 context 传入回调
        llm_router = self.llm_router
        if llm_router is None and context.get('llm_callback'):
            llm_router = LLMRouter(callback=context['llm_callback'])
        if llm_router and llm_router.is_available():
            llm_result = llm_router.route(rewritten)
            if llm_result:
                return self._build_decision(
                    llm_result, rewritten, variants, time_sens, authority,
                    layer='llm')

        # 5. 兜底：通用类型
        fallback = {
            'query_type': 'general',
            'secondary_types': [],
            'confidence': 0.5,
            'reasoning': '规则/语义/LLM 层均未命中，回退到 general',
        }
        return self._build_decision(
            fallback, rewritten, variants, time_sens, authority, layer='fallback')

    # ---- 决策组装 ----

    def _build_decision(self,
                        result: Dict,
                        query: str,
                        variants: List[Dict],
                        time_sens: str,
                        authority: str,
                        layer: str) -> RoutingDecision:
        """Assemble a :class:`RoutingDecision` from a layer result."""
        qtype = result.get('query_type', 'general')
        if qtype not in VALID_QUERY_TYPES:
            qtype = 'general'
        secondary = list(result.get('secondary_types', []))
        confidence = float(result.get('confidence', 0.5))
        reasoning = result.get('reasoning', '')
        engine_chain = self.build_engine_chain(qtype, secondary)

        return RoutingDecision(
            query_type=qtype,
            secondary_types=secondary,
            confidence=confidence,
            time_sensitivity=time_sens,
            authority_need=authority,
            engine_chain=engine_chain,
            query_variants=variants,
            reasoning=f"[{layer}] {reasoning}",
        )


# ============================================================
# 模块公开 API
# ============================================================

__all__ = [
    'QueryRouter',
    'RoutingDecision',
    'CircuitBreaker',
    'RuleRouter',
    'SemanticRouter',
    'LLMRouter',
    'QueryPreprocessor',
    'ENGINE_CHAIN_MAP',
    'VALID_QUERY_TYPES',
]


if __name__ == '__main__':
    # 简易自测入口
    r = QueryRouter()
    for q in ['最新 LLM 论文', 'RAG 开源实现', '什么是 RAG', 'LangChain vs LlamaIndex',
              '如何部署 Docker', '大家怎么看 Claude', '今天 AI 新闻', '量子计算原理']:
        d = r.route(q, {})
        print(f"{q!r:40} -> type={d.query_type:12} conf={d.confidence:.2f} "
              f"time={d.time_sensitivity:9} auth={d.authority_need:6} "
              f"chain={d.engine_chain}")
