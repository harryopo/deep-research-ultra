"""probe.py — 引擎功能自检。

可用性判定必须是"真拿到结果"，而不是"域名能连通/环境变量在"。

真实故障：gitee 匿名请求恒返回 []、modelscope 搜索端点已 404，但 is_available()
只看 socket 能否连上 443 —— --list 全绿、Phase 0 环境门放行死引擎，
调研跑到后半程才发现没数据。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

STATUS_OK = 'ok'              # 探到结果
STATUS_EMPTY = 'empty'        # 可调通但 0 结果（契约变更/需授权）
STATUS_FAILED = 'failed'      # 引擎不可用或抛异常
STATUS_SKIPPED = 'skipped'    # 非搜索类引擎（lookup/详情）

# 探针查询：按引擎定制（学术/医学引擎用通用词会假阴性），同时充当"可探针注册表"
# —— 不在此表里的引擎（MCP/全局 skill 封装）由各自的 is_available() 负责。
PROBE_QUERIES: Dict[str, str] = {
    # Layer 1 学术直连
    'openalex': 'retrieval augmented generation',
    'semantic-scholar': 'retrieval augmented generation',
    'pubmed': 'diabetes',
    'arxiv-fulltext': 'cat:cs.CL',   # 宽查询（如 transformer）实测被 arXiv 判 406，探针用分类查询
    # Layer 2 平台 / GitHub / 国内源
    'gitee': 'vector database',
    'github-deep-search': 'rag',
    'github-code-search': 'RetrievalQA',
    'baidu-serp': '向量数据库 开源',
    'sogou-weixin': '大模型微调实践',
    'sogou-zhihu': 'LangChain 怎么样',
    'baidu-xueshu': 'transformer 注意力机制',
    # Layer 4 降级
    'duckduckgo': 'python',
    'baidu-html': 'python',
    'bing-html': 'python',
    'searxng': 'python',
}

DEFAULT_PROBE_QUERY = 'python'


def resolve_probe_query(engine) -> str:
    """引擎自带 probe_query > PROBE_QUERIES 登记 > 通用兜底。"""
    explicit = getattr(engine.metadata, 'probe_query', '') or ''
    return explicit or PROBE_QUERIES.get(engine.get_name()) or DEFAULT_PROBE_QUERY


def probeable_engines(engines: List[Any]) -> List[Any]:
    """默认探针范围：登记过的直连引擎（避免把 npx/MCP 拉起来拖慢自检）。"""
    return [e for e in engines if e.get_name() in PROBE_QUERIES]


def classify_probe(results: Optional[list]) -> str:
    """None=失败/不可用；[]=可调通但 0 结果；非空=正常。"""
    if results is None:
        return STATUS_FAILED
    return STATUS_OK if results else STATUS_EMPTY


def probe_engine(engine, query: str = '', max_results: int = 3) -> Dict[str, Any]:
    """对单个引擎做功能探针。"""
    name = engine.get_name()
    meta = engine.metadata

    if not engine.has_capability('search'):
        return {'engine': name, 'status': STATUS_SKIPPED, 'count': 0,
                'note': '非搜索类引擎（lookup/详情）'}

    if not engine.is_available():
        missing = [k for k in meta.config_keys if not os.environ.get(k)]
        note = f'缺少配置: {", ".join(missing)}' if missing else '依赖/服务未就绪'
        return {'engine': name, 'status': STATUS_FAILED, 'count': 0, 'note': note}

    q = query or resolve_probe_query(engine)
    try:
        results = engine.search(q, max_results=max_results)
    except Exception as exc:          # 引擎异常不得当成"可用"
        return {'engine': name, 'status': STATUS_FAILED, 'count': 0,
                'note': f'探针异常: {exc}', 'query': q}

    status = classify_probe(results)
    if status == STATUS_OK:
        first = results[0]
        note = (first.title or first.url or '')[:60]
    elif status == STATUS_EMPTY:
        note = '可调通但 0 结果（查询词无命中，或端点契约变更/需授权）'
    else:
        note = f'引擎返回 None（{_last_http_error()}）'
    return {'engine': name, 'status': status, 'count': len(results or []),
            'note': note, 'query': q}


def _last_http_error() -> str:
    """取底层 HTTP 失败原因（HTTP 406 / URLError / …），让报告说得出"为什么不可用"。"""
    try:
        from engines import fallback as _fb
        return getattr(_fb, 'LAST_HTTP_ERROR', '') or '依赖/服务未就绪'
    except Exception:
        return '依赖/服务未就绪'


def summarize(reports: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in reports:
        out[r['status']] = out.get(r['status'], 0) + 1
    return out
