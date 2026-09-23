"""probe.py — 引擎功能自检。

可用性判定必须是"真拿到结果"，而不是"域名能连通/环境变量在"。

真实故障：gitee 匿名请求恒返回 []、modelscope 搜索端点已 404，但 is_available()
只看 socket 能否连上 443 —— --list 全绿、Phase 0 环境门放行死引擎，
调研跑到后半程才发现没数据。

反向故障（v6.16.3 修的那半）：闸门也不能让"连通性猜的 False"抢在功能探针前面。
实测 openalex 因 is_available() 超时被记成"依赖/服务未就绪"，真正的探针根本没跑，
环境于是少算一个源（7 而非 8）；semantic-scholar 同样超时，却因为 config_keys 里
挂着可选的 S2_API_KEY 而被报成"缺少配置"，把用户支去申请一个不需要的 key。
所以这里只按"必需配置齐不齐"拦人（missing_required_config），拦不住的统统真探一次，
失败原因取自实际 HTTP 状态。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from engines.base import missing_required_config

STATUS_OK = 'ok'              # 探到结果
STATUS_EMPTY = 'empty'        # 可调通但 0 结果（契约变更/需授权）
STATUS_FAILED = 'failed'      # 引擎不可用或抛异常
STATUS_SKIPPED = 'skipped'    # 非搜索类引擎（lookup/详情）
STATUS_AGENT_ONLY = 'agent_only'  # 脚本层根本取不到数据，只有 Agent 调工具才有

# 探针查询：按引擎定制（学术/医学引擎用通用词会假阴性），同时充当"可探针注册表"
# —— 不在此表里的引擎（MCP/全局 skill 封装）由各自的 is_available() 负责。
#
# 登记范围＝"脚本层真能拿到结果"的引擎。MCP 类（下表末尾 5 个）自 v6.9 起也纳入：
# 它们不探就等于闸门看不见，实测有用户 5 个 MCP 一个没连还照样开跑。
# 但 skill 封装类（last30days/oss-finder/agent-reach/sciverse/context7/defuddle）
# 与内置类（websearch/webfetch）**不能登记**：它们的 search() 在脚本层恒返回 None
# （数据只有 Lead 调 Skill/内置工具才拿得到），探它们＝往闸门里灌假失败。
# 这类引擎由 agent_invoked() 单独认档（🤖），--sources 点名它们也不判"坏了"——
# 实测未分档前，--probe --sources websearch,oss-finder 回的是 rc=1「不要开始调研」。
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


# 数据只有 Agent 亲自调工具才拿得到的引擎：skill 封装层 + 宿主内置层。按实现模块判
# （与 engine_kind 同一手法）——这两层的 search() 写死返回 None，探它们等于把
# "脚本看不见" 报成 "引擎坏了"。
AGENT_ONLY_MODULES = ('skill_engines', 'builtin')


def agent_invoked(engine) -> bool:
    return any(m in (type(engine).__module__ or '') for m in AGENT_ONLY_MODULES)


def _reset_http_error() -> None:
    """每个引擎开探前清台：LAST_HTTP_ERROR 是模块全局，不清就会把上一个引擎的
    429/406 安到下一个（实测 oss-finder 被报成 HTTP 429 rate limited）。"""
    try:
        from engines import fallback as _fb
        _fb._clear_http_error()
    except Exception:
        pass


def _meta_fields(engine) -> Dict[str, Any]:
    """闸门要按层与能力判独立性、按通道说指引，报告里必须带上元数据。"""
    meta = engine.metadata
    return {'layer': meta.layer, 'config_keys': list(meta.config_keys),
            'requires_config': meta.requires_config,
            'caps': list(meta.capabilities), 'kind': engine_kind(engine)}


def probe_engine(engine, query: str = '', max_results: int = 3) -> Dict[str, Any]:
    """对单个引擎做功能探针。"""
    name = engine.get_name()
    meta = engine.metadata

    if not engine.has_capability('search'):
        return {'engine': name, 'status': STATUS_SKIPPED, 'count': 0,
                'note': '非搜索类引擎（lookup/详情）', **_meta_fields(engine)}

    if agent_invoked(engine):
        return {'engine': name, 'status': STATUS_AGENT_ONLY, 'count': 0,
                'note': '脚本层取不到数据：只有 Agent 亲自调用对应工具才有结果',
                **_meta_fields(engine)}

    missing = missing_required_config(meta)
    if missing:
        return {'engine': name, 'status': STATUS_FAILED, 'count': 0,
                'note': f'缺少配置: {", ".join(missing)}', **_meta_fields(engine)}

    q = query or resolve_probe_query(engine)
    kwargs: Dict[str, Any] = {}
    if engine_kind(engine) == 'mcp':
        # MCP 走 npx/uvx 冷启动，不给预算就能把整轮自检拖死
        kwargs['mcp_timeout'] = MCP_PROBE_BUDGET
    _reset_http_error()
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
# 主题级预演：--probe 答的是"引擎今天活着吗"，本函数答的是"这个主题它到得到数据吗"
# ---------------------------------------------------------------------------

THEME_USABLE = 'usable'      # 至少一条真实查询词取到数据
THEME_NO_HIT = 'no_hit'      # 每条都调通了，全是 0 命中
THEME_BLOCKED = 'blocked'    # 每条都没取到数据（被拦 / 服务挂 / 异常）
THEME_SKIPPED = 'skipped'    # 非搜索类引擎，不进预演
THEME_AGENT_ONLY = 'agent_only'  # 脚本层取不到数据，预演判不了它

THEME_MARKS = {THEME_USABLE: '✅', THEME_NO_HIT: '⚠️',
               THEME_BLOCKED: '❌', THEME_SKIPPED: '⏭ ',
               THEME_AGENT_ONLY: '🤖'}

THEME_HEADLINES = {
    THEME_USABLE: '本主题到得了数据',
    THEME_NO_HIT: '引擎活着，本主题一条都没命中',
    THEME_BLOCKED: '本主题每条查询都没取到数据（通道问题，不是没资料）',
    THEME_SKIPPED: '非搜索类引擎，未进预演',
    THEME_AGENT_ONLY: '脚本层取不到数据（要 Agent 亲自调工具），预演判不了它',
}


def theme_probe(engines: List[Any], queries: List[str],
                max_results: int = 3) -> List[Dict[str, Any]]:
    """拿 Lead 派给子 Agent 的实际查询词逐条打一次。

    探针词是登记死的通用词（'cat:cs.CL' / 'python'），它 ✅ 不代表那条长英文查询
    打得进去——实测同一引擎探针通过、实跑每个查询都 HTTP 406，5 个子研究员里 4 个
    被迫改道。这里把两种"没数据"分开：调通但 0 命中（词的问题）／根本没取到（通道的问题）。
    """
    rows: List[Dict[str, Any]] = []
    for engine in engines:
        name = engine.get_name()
        if not engine.has_capability('search'):
            rows.append({'engine': name, 'verdict': THEME_SKIPPED, 'hit': 0,
                         'total': len(queries), 'matched': [], 'queries': [],
                         **_meta_fields(engine)})
            continue
        if agent_invoked(engine):
            rows.append({'engine': name, 'verdict': THEME_AGENT_ONLY, 'hit': 0,
                         'total': len(queries), 'matched': [], 'queries': [],
                         **_meta_fields(engine)})
            continue
        kwargs: Dict[str, Any] = {'max_results': max_results}
        if engine_kind(engine) == 'mcp':
            kwargs['mcp_timeout'] = MCP_PROBE_BUDGET
        per: List[Dict[str, Any]] = []
        matched: List[str] = []
        for q in queries:
            try:
                results = engine.search(q, **kwargs)
            except Exception as exc:
                per.append({'query': q, 'count': 0, 'status': STATUS_FAILED,
                            'note': f'异常: {exc}'})
                continue
            status = classify_probe(results)
            if status == STATUS_OK:
                matched.append(q)
                note = (results[0].title or results[0].url or '')[:60]
            elif status == STATUS_EMPTY:
                note = '调通了但 0 命中'
            else:
                note = f'未取到数据（{_failure_reason(engine)}）'
            per.append({'query': q, 'count': len(results or []),
                        'status': status, 'note': note})
        if matched:
            verdict = THEME_USABLE
        elif any(p['status'] == STATUS_EMPTY for p in per):
            verdict = THEME_NO_HIT
        else:
            verdict = THEME_BLOCKED
        rows.append({'engine': name, 'verdict': verdict, 'hit': len(matched),
                     'total': len(per), 'matched': matched, 'queries': per,
                     **_meta_fields(engine)})
    return rows


def theme_advice_for(row: Dict[str, Any]) -> List[str]:
    """一个预演结论 → Lead 下一步能做的动作。"""
    if row['verdict'] == THEME_USABLE:
        return [f"命中的查询词：{' ／ '.join(row['matched'])} —— 派单照这个形状写"]
    if row['verdict'] == THEME_SKIPPED:
        return ['非搜索类引擎，不能派检索任务']
    notes = ' '.join(q['note'] for q in row['queries'])
    lines: List[str] = []
    if row['verdict'] == THEME_NO_HIT:
        lines.append('引擎活着，只是这批词一条都没命中：把整句长查询拆成 2-3 个短词组'
                     '或换分类式查询再预演一次；0 命中不等于这个主题没资料')
    else:
        lines.append('每条查询都没取到数据：这是通道问题（被拦/服务挂/要授权），'
                     '不是主题没资料')
    if any(code in notes for code in HTTP_DENY_CODES) or _transport_degraded():
        # 裸 urllib 那轮常连状态码都留不下（实测回"依赖/服务未就绪"），
        # 只按 4xx 判就会在最该提示的时候一声不出
        lines.extend(_4xx_advice())
    return lines


def _transport_degraded() -> bool:
    """这一轮的失败该不该算在传输层头上：curl_cffi 没装时请求全是裸 urllib 出去的。"""
    try:
        from engines import fallback as _fb
        return bool(getattr(_fb, 'TRANSPORT_DEGRADED', False))
    except Exception:
        return False


def _4xx_advice() -> List[str]:
    """被拒有两种成因，指向的修复完全不同，不能一句话糊过去。"""
    if _transport_degraded():
        return ['本轮所有请求都没有 TLS 指纹（curl_cffi 未装）：406/403 很可能由此起，'
                '这不是源不行。补装一次即可，全部引擎共用：pip install curl_cffi，装好重跑预演']
    return ['已带 TLS 指纹仍被拒：这个源今天确实到不了，换同层替代源'
            '（--list --caps 看候选），别把它记成"本主题没资料"']


def format_theme_rows(rows: List[Dict[str, Any]]) -> List[str]:
    """预演结果 → 可打印行（逐条查询都要看得见，命中的是哪个词得能抄进派单）。"""
    lines: List[str] = []
    for row in rows:
        lines.append(f"{THEME_MARKS.get(row['verdict'], '?')} {row['engine']:<20} "
                     f"{row['hit']}/{row['total']} 条查询出数据  "
                     f"{THEME_HEADLINES.get(row['verdict'], row['verdict'])}")
        for q in row['queries']:
            lines.append(f"      · [{q['status']}] {q['query']} → "
                         f"{q['count']} 条 ｜ {q['note']}")
        for advice in theme_advice_for(row):
            lines.append(f"   → {advice}")
    return lines


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
    'TAVILY_API_KEY': 'https://app.tavily.com 申请（1000 次/月免费；注册前确认免绑卡——要绑银行卡就放弃这个源）',
    'FIRECRAWL_API_KEY': 'https://www.firecrawl.dev 申请（500 credits/月；注册前确认免绑卡——要绑银行卡就放弃这个源）',
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
    # 可选 key（requires_config=False）不参与"去申请"清单：缺它不是这个源用不了的原因。
    # 字段缺失时按"必需"处理，兼容手工构造的报告。
    if rep.get('requires_config', True):
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
        if r.get('status') in (STATUS_OK, STATUS_SKIPPED, STATUS_AGENT_ONLY):
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
