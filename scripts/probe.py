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
#
# 登记范围＝"脚本层真能拿到结果"的引擎。MCP 类（下表末尾 5 个）自 v6.9 起也纳入：
# 它们不探就等于闸门看不见，实测有用户 5 个 MCP 一个没连还照样开跑。
# 但 skill 封装类（last30days/oss-finder/agent-reach/sciverse/context7/defuddle）
# 与内置类（websearch/webfetch）**不能登记**：它们的 search() 在脚本层恒返回 None
# （数据只有 Lead 调 Skill/内置工具才拿得到），探它们＝往闸门里灌假失败。
PROBE_QUERIES: Dict[str, str] = {
    # Layer 1 学术直连
    'openalex': 'retrieval augmented generation',
    'semantic-scholar': 'retrieval augmented generation',
    'pubmed': 'diabetes',
    'arxiv-fulltext': 'cat:cs.CL',   # 宽查询（如 transformer）实测被 arXiv 判 406，探针用分类查询
    # Layer 1 MCP（要连 server；单次预算见 MCP_PROBE_BUDGET）
    'tavily': 'retrieval augmented generation production',
    'firecrawl': 'python web scraping framework',
    'open-websearch': 'python packaging',
    'arxiv': 'retrieval augmented generation survey',
    'paper-search': 'graph neural network',
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

# MCP 引擎走 npx/uvx 冷启动，不给预算就能把整轮自检拖死（实测旧实现单次调用 60s 起）
MCP_PROBE_BUDGET = 25

DEFAULT_PROBE_QUERY = 'python'


def resolve_probe_query(engine) -> str:
    """引擎自带 probe_query > PROBE_QUERIES 登记 > 通用兜底。"""
    explicit = getattr(engine.metadata, 'probe_query', '') or ''
    return explicit or PROBE_QUERIES.get(engine.get_name()) or DEFAULT_PROBE_QUERY


def probeable_engines(engines: List[Any]) -> List[Any]:
    """默认探针范围＝PROBE_QUERIES 登记过的引擎（脚本层真能出数据的那批）。"""
    return [e for e in engines if e.get_name() in PROBE_QUERIES]


def classify_probe(results: Optional[list]) -> str:
    """None=失败/不可用；[]=可调通但 0 结果；非空=正常。"""
    if results is None:
        return STATUS_FAILED
    return STATUS_OK if results else STATUS_EMPTY


def _meta_fields(engine) -> Dict[str, Any]:
    """闸门要按层与能力判独立性、按通道说指引，报告里必须带上元数据。"""
    meta = engine.metadata
    return {'layer': meta.layer, 'config_keys': list(meta.config_keys),
            'caps': list(meta.capabilities), 'kind': engine_kind(engine)}


def probe_engine(engine, query: str = '', max_results: int = 3) -> Dict[str, Any]:
    """对单个引擎做功能探针。"""
    name = engine.get_name()
    meta = engine.metadata

    if not engine.has_capability('search'):
        return {'engine': name, 'status': STATUS_SKIPPED, 'count': 0,
                'note': '非搜索类引擎（lookup/详情）', **_meta_fields(engine)}

    if not engine.is_available():
        missing = [k for k in meta.config_keys if not os.environ.get(k)]
        note = f'缺少配置: {", ".join(missing)}' if missing else '依赖/服务未就绪'
        return {'engine': name, 'status': STATUS_FAILED, 'count': 0, 'note': note,
                **_meta_fields(engine)}

    q = query or resolve_probe_query(engine)
    kwargs: Dict[str, Any] = {}
    if engine_kind(engine) == 'mcp':
        # MCP 走 npx/uvx 冷启动，不给预算就能把整轮自检拖死
        kwargs['mcp_timeout'] = MCP_PROBE_BUDGET
    try:
        results = engine.search(q, max_results=max_results, **kwargs)
    except Exception as exc:          # 引擎异常不得当成"可用"
        return {'engine': name, 'status': STATUS_FAILED, 'count': 0,
                'note': f'探针异常: {exc}', 'query': q, **_meta_fields(engine)}

    status = classify_probe(results)
    if status == STATUS_OK:
        first = results[0]
        note = (first.title or first.url or '')[:60]
    elif status == STATUS_EMPTY:
        note = '可调通但 0 结果（查询词无命中，或端点契约变更/需授权）'
    else:
        note = f'引擎返回 None（{_failure_reason(engine)}）'
    return {'engine': name, 'status': status, 'count': len(results or []),
            'note': note, 'query': q, **_meta_fields(engine)}


def _failure_reason(engine) -> str:
    """失败要报得出"为什么"：MCP 的原因在 client 手里（握手/超时/起不来），
    直连 HTTP 的原因在 fallback 里——拿错边就会把超时说成服务未就绪。"""
    return (str(getattr(getattr(engine, '_client', None), 'last_error', '') or '')
            or _last_http_error())


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


# ---------------------------------------------------------------------------
# 启动前环境闸门（Phase 0 硬门）
# ---------------------------------------------------------------------------

# 缺配置时要给出「去哪拿 + 解锁什么 + 怎么设」，否则用户只能瞎猜或直接降级开跑
CONFIG_GUIDE: Dict[str, str] = {
    'S2_API_KEY': 'https://www.semanticscholar.org/product/api 申请'
                  '（解锁引用图谱与批量元数据检索；匿名常被限流）',
    'GITHUB_TOKEN': 'https://github.com/settings/tokens 生成 fine-grained 只读 token'
                    '（解锁 github-code-search，并把 github-deep-search 从 60 次/小时提上来）',
    'GITEE_TOKEN': 'https://gitee.com/profile/personal_access_tokens 生成'
                   '（v5 搜索端点匿名请求静默返回 []，不配等于没有这个源）',
    'NCBI_API_KEY': 'https://www.ncbi.nlm.nih.gov/account/settings/ 申请'
                    '（匿名可用但限 3 次/秒，多子 Agent 并发会掉结果）',
    'UNPAYWALL_EMAIL': '填任意常用邮箱即可（解锁 OA 全文定位）',
    'OPENALEX_MAILTO': '填邮箱进 polite pool；不配也能查，但并发时极易 429',
    'TAVILY_API_KEY': 'https://app.tavily.com 申请（1000 次/月免费）',
    'FIRECRAWL_API_KEY': 'https://www.firecrawl.dev 申请（500 credits/月）',
    'CRAWL4AI_URL': '本地起服务后设为 http://localhost:11235',
    'SEARXNG_URL': '自建 SearXNG 实例地址（如 http://localhost:8888）；没有实例就排除该源',
}

# 不可用原因 → 该怎么办。指引必须跟着"这个引擎靠什么通道出数据"走：实测把
# duckduckgo/sogou-zhihu 这类直连 HTTP 源说成"去连 MCP server"是误导。
MCP_NOTE_KEYS = ('MCP', '未连接')
NETWORK_NOTE_KEYS = ('服务未就绪', '探针异常', 'HTTP', 'None', 'URLError')
HTTP_DENY_CODES = ('HTTP 406', 'HTTP 403', 'HTTP 429', 'HTTP 401')
SUBSTITUTE_ADVICE = ('改用同层替代源：arXiv 全文 → arxiv.org/abs 页；国内学术 → '
                     'openalex/pubmed；HTML 降级搜索 → MCP/直连层，别把降级链当兜底')

# 能读到原始制品（论文原文 / 仓库代码）的能力标签：只有二手网页时归属型 claim 无法溯源
PRIMARY_CAPS = {'academic', 'fulltext', 'oa', 'opensource', 'code_search',
                'citation_graph', 'latex'}


def engine_kind(engine) -> str:
    """mcp＝要连 server 才有数据，其余是直连 HTTP。按实现模块判，不靠猜。"""
    return 'mcp' if 'mcp' in type(engine).__module__ else 'direct'


def _advice_for(rep: Dict[str, Any]) -> List[str]:
    """单条不可用报告 → 可执行动作（可能多条：既缺 key 又要连服务时会同时给）。"""
    note = str(rep.get('note') or '')
    lines: List[str] = []
    for key in rep.get('config_keys') or []:
        if os.environ.get(key):
            continue
        guide = CONFIG_GUIDE.get(key)
        lines.append(f'缺 {key}：{guide} → export {key}="<值>" 后重跑 --probe'
                     if guide else f'缺 {key}：export {key}="<值>" 后重跑 --probe')
    if '缺少配置' in note and lines:
        return lines
    # note 里的具体原因上面那张表已经逐行打过，这里只说"该怎么办"，才能按动作合并同源
    if rep.get('status') == STATUS_EMPTY:
        lines.append('可调通但 0 结果：查询词无命中或端点契约变更/需授权 —— 不得当可用源用')
    elif '超时' in note:
        lines.append(f'MCP server 在 {MCP_PROBE_BUDGET}s 预算内没答完：npx/uvx 首次要下载包，'
                     '先手动预热（`bash scripts/setup-mcp.sh --core` 后直接跑一次该 MCP 的工具），'
                     '或干脆改用已连上的 MCP 工具 / 直连引擎')
    elif any(k in note for k in MCP_NOTE_KEYS) or rep.get('kind') == 'mcp':
        lines.append('需在当前会话连上对应 MCP server（`research.py --mcp-check` 看连接态，'
                     '缺的用 `scripts/setup-mcp.sh --core` 配），没连上就等于没有这个源')
    elif any(k in note for k in NETWORK_NOTE_KEYS):
        lines.append('直连端点今天出不来数据（网络被拦/反爬/契约变更）：'
                     '可加 --proxy、换同层替代源，或在规划里排除它')
    if any(code in note for code in HTTP_DENY_CODES):
        lines.append(SUBSTITUTE_ADVICE)
    return lines or [f'未通过功能自检（{note or "原因未知"}）—— 规划时排除该源']


def source_gate(reports: List[Dict[str, Any]], min_sources: int = 3,
                min_layers: int = 2) -> Dict[str, Any]:
    """探针报告 → 环境够不够开工。不够就 blockers，够但有缺口就 guidance。

    判据只认"真的返回了结果"的引擎：实测一次调研 5 个源可用却全挤在同一层、
    且代码/全文通道全缺（GITEE_TOKEN、arXiv 被 406、MCP 没连）——数量够，
    独立性和一手溯源都不够，最后 110 条归属型 claim 全卡在 pending。
    """
    ok = [r for r in reports if r.get('status') == STATUS_OK]
    layers = {r.get('layer') for r in ok if r.get('layer') is not None}
    primary = sorted({r['engine'] for r in ok
                      if set(r.get('caps') or []) & PRIMARY_CAPS})

    blockers: List[str] = []
    if len(ok) < min_sources:
        blockers.append(f'真出数据的引擎只有 {len(ok)} 个（< {min_sources}），'
                        f'证据链无法交叉验证')
    if len(layers) < min_layers:
        blockers.append(f'可用引擎只覆盖 {len(layers)} 层（< {min_layers} 层），'
                        f'多个源很可能只是同一批网页的不同入口')
    if not primary:
        blockers.append('可用源里没有任何一手制品通道（论文库/代码仓库），'
                        '"某仓库/某论文原文说 X"这类归属型 claim 将无法验证')

    unavailable = []
    for r in reports:
        if r.get('status') in (STATUS_OK, STATUS_SKIPPED):
            continue
        unavailable.append({'engine': r['engine'], 'status': r['status'],
                            'note': r.get('note', ''),
                            'advice': '；'.join(_advice_for(r))})
    # 同一条动作常被多个源共用（如都缺 GITHUB_TOKEN），并成一行才不会刷屏
    grouped: Dict[str, List[str]] = {}
    for u in unavailable:
        grouped.setdefault(u['advice'], []).append(u['engine'])
    guidance = [f"{', '.join(names)}: {advice}" for advice, names in grouped.items()]

    return {'ok': not blockers, 'blockers': blockers, 'guidance': guidance,
            'unavailable': unavailable, 'available': [r['engine'] for r in ok],
            'layers': sorted(layers), 'primary_channels': primary}
