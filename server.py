"""deep-research-ultra 插件的 MCP server（计划 B：五个业务工具）。

契约来自 docs/specs/2026-09-20-drux-plugin-mcp-design.md 第六节。两条铁律：
- 返回值恒含 ok；失败必须长得像失败（error + hint），绝不返回看起来成功的空结果
- 校验门与盖戳在这里由机器执行，不靠 Agent 自觉

依赖：本机实测 mcp 2.1.1 —— 2.x 里 FastMCP 已改名为 MCPServer，
      import 路径是 mcp.server.mcpserver（写 mcp.server.fastmcp 会直接 ModuleNotFoundError）。
"""
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SKILL_DIR = Path(__file__).resolve().parent / 'skills' / 'deep-research-ultra'
SCRIPTS = SKILL_DIR / 'scripts'


def _load_scripts():
    """把 skill 的 scripts/ 挂进 import 路径（与 research.py 同一套模块，逻辑不复制第二份）。"""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))


def _fail(error: str, hint: str, **extra) -> Dict[str, Any]:
    return {'ok': False, 'error': error, 'hint': hint, **extra}


def _workspace(workspace: str = '') -> Path:
    return Path(workspace or os.getcwd()).expanduser().resolve()


def _session_dir(session_id: str, workspace: str = '') -> Path:
    return _workspace(workspace) / '.research' / session_id


def run_gate(sources: Optional[List[str]] = None) -> Dict[str, Any]:
    """Phase 0 环境闸门：真探一次每个候选引擎，判据是"今天出不出得来数据"。

    单独成一个函数就是为了被替换：单测不联网，端到端跑真探针。
    """
    _load_scripts()
    from probe import probe_engine, probeable_engines, source_gate
    from research import build_registry

    registry = build_registry()
    if sources:
        wanted = {s.strip() for s in sources if s.strip()}
        engines = [e for e in registry.get_all() if e.get_name() in wanted]
    else:
        engines = probeable_engines(registry.get_all())
    reports = [probe_engine(e, max_results=3) for e in engines]
    return source_gate(reports)


def drux_session_start(query: str, effort: str = 'standard',
                       dimensions: Optional[List[str]] = None,
                       sources: Optional[List[str]] = None,
                       allow_degraded: bool = False,
                       workspace: str = '') -> Dict[str, Any]:
    """开一次调研：先过环境闸门，闸门不过就不建 session。

    allow_degraded 只在用户明确说"不配了，直接下一步"时才该为真——Lead 不许代答。
    """
    if not str(query).strip():
        return _fail('query 为空', '把用户的调研主题原话传进来')
    try:
        gate = run_gate(sources)
    except Exception as exc:  # 闸门自身炸了不能变成"看起来没有缺口"
        return _fail(f'环境闸门执行失败：{type(exc).__name__}: {exc}',
                     '检查 scripts/engines 是否完整、依赖是否装好（pip install -r '
                     'requirements.txt），再重试 drux_session_start')
    blockers = list(gate.get('blockers') or [])
    guidance = list(gate.get('guidance') or [])
    usable = list(gate.get('available') or [])
    if blockers and not allow_degraded:
        return {'ok': False, 'error': '环境闸门未过，不建 session',
                'hint': '把 issues 与 config_guide 逐条转述给用户，等他配好后重跑；'
                        '用户明确授权带缺口开跑时才传 allow_degraded=true',
                'issues': blockers, 'config_guide': guidance,
                'usable_engines': usable, 'layers': gate.get('layers') or []}

    session_id = 'drux-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    sess = _session_dir(session_id, workspace)
    _load_scripts()
    from ledger import ResearchLedger
    ResearchLedger(str(sess)).init()
    sess.mkdir(parents=True, exist_ok=True)
    info = {'session_id': session_id, 'started_at': datetime.now().isoformat(timespec='seconds'),
            'query': str(query).strip(), 'effort': effort,
            'dimensions': list(dimensions or [])}
    (sess / 'session.json').write_text(json.dumps(info, ensure_ascii=False, indent=2),
                                       encoding='utf-8')
    return {'ok': True, 'session_id': session_id,
            'ledger_dir': sess.as_posix(), 'usable_engines': usable,
            'layers': gate.get('layers') or [],
            'primary_channels': gate.get('primary_channels') or [],
            'warnings': guidance, 'dimensions': info['dimensions'],
            'degraded': bool(blockers), 'issues': blockers,
            'config_guide': guidance if blockers else []}


def drux_claim_add(session_id: str, text: str, topic: str = 'general',
                   sources: Optional[List[Dict[str, Any]]] = None,
                   perspective: str = 'general', confidence: float = 0.5,
                   status: str = 'pending', workspace: str = '') -> Dict[str, Any]:
    """写一条 claim 并挂来源。不可溯源的 URL 拒收，自标 verified 一律忽略。"""
    sess = _session_dir(session_id, workspace)
    if not (sess / 'ledger.jsonl').exists():
        return _fail(f'账本不存在：{sess.as_posix()}/ledger.jsonl',
                     f'先调 drux_session_start 拿 session_id（当前值 {session_id!r} 找不到目录）')
    if not str(text).strip():
        return _fail('claim 正文为空', '传要记录的那句结论原文，别传章节标题')

    _load_scripts()
    from ledger import ResearchLedger, _is_traceable
    led = ResearchLedger(str(sess))
    warnings: List[str] = []
    if str(status).strip().lower() == 'verified':
        # verified 只能由交叉验证或一手反查赋予；放过去就是账本覆盖率虚高
        warnings.append('已忽略自标 status=verified：verified 只能由交叉验证/一手反查赋予，'
                        '本条按 pending 入库')
        status = 'pending'

    entry = led.add_claim(str(text).strip(), topic=topic, status=status,
                          perspective=perspective, confidence=confidence)
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for src in sources or []:
        url = str((src or {}).get('url') or '').strip()
        if not _is_traceable(url):
            rejected.append({'url': url,
                             'reason': '点不回原文（站内跳转/空/非 http 都不算来源），已拒收'})
            continue
        added = led.add_source(entry['id'], url, title=str((src or {}).get('title') or ''),
                               tier=(src or {}).get('tier'))
        accepted.append({'url': url, 'tier': added['tier']})
    if not accepted:
        warnings.append('本条 claim 一个来源都没挂上，过门时会按无溯源计入缺口')
    return {'ok': True, 'claim_id': entry['id'], 'status': entry['status'],
            'accepted': accepted, 'rejected_sources': rejected,
            'warnings': warnings, 'ledger_dir': sess.as_posix()}


def drux_claim_verify(session_id: str, claim_ids: List[str], method: str = 'cross',
                      check_url: str = '', check_title: str = '',
                      verify_method: str = '', note: str = '',
                      workspace: str = '') -> Dict[str, Any]:
    """机器判定 verified 升级：档 A 数独立注册域，档 B 走一手反查。

    为什么是第五个工具而不是放宽判据：spec 第六节只给了四个工具，那样 MCP 侧没有
    任何一条路能把 claim 升到 verified —— 发布门永远不过、戳永远盖不上。
    补一条机械升级通道，而不是让 Lead 自报"我已交叉验证"（那正是账本一直拦的东西）。

    档 A 比发布门 2b 更严：2b 只做转载去重后计数，两条同域来源在门里算 2，
    在 SKILL.md 的档 A 定义（≥2 个不同注册域）里只算 1。升级取严不取宽。
    """
    sess = _session_dir(session_id, workspace)
    if not (sess / 'ledger.jsonl').exists():
        return _fail(f'账本不存在：{sess.as_posix()}/ledger.jsonl',
                     f'先调 drux_session_start 拿 session_id（当前值 {session_id!r} 找不到目录）')
    wanted = [str(c).strip() for c in (claim_ids or []) if str(c).strip()]
    if not wanted:
        return _fail('claim_ids 为空', '传入 drux_claim_add 返回的 claim_id 列表')
    # 升级是整文件重写，锁在说明另有人在写账本 —— 覆盖比失败更糟
    lock = sess / 'ledger.lock'
    if lock.exists():
        return _fail(f'另一处正在改账本：{lock.as_posix()} 存在',
                     '等写入方退出后重试，不要绕过锁直接改（set-status 整文件重写）')

    _load_scripts()
    from ledger import ResearchLedger, _registered_domain
    from similarity import effective_independent_count

    led = ResearchLedger(str(sess))
    claims = {c['id']: c for c in led.claims() if c.get('id')}
    unknown = [c for c in wanted if c not in claims]
    if unknown:
        return _fail(f'账本里没有这些 claim：{"、".join(unknown)}',
                     'claim_id 必须是本次 session 里 drux_claim_add 返回的原值，'
                     '子 Agent 自己编的 id 不在账本上')

    if str(method).strip().lower() == 'primary':
        if not check_url.strip():
            return _fail('method=primary 缺 check_url',
                         '档 B 要传 Lead 真正反查过的那个制品 URL（与既有来源同域同路径）')
        changed = led.verify_primary(wanted, check_url.strip(), check_title,
                                     method=verify_method)
        after = {c['id']: c for c in led.claims() if c.get('id')}
        promoted = [cid for cid in wanted if after.get(cid, {}).get('status') == 'verified']
        refused = [{'claim_id': cid,
                    'reason': '反查 URL 与该 claim 既有来源不指向同一制品，或该 claim 无来源'
                              '（档 B 要求 blob/raw 同制品，不同分支/文件算不同制品）'}
                   for cid in wanted if cid not in promoted]
        return {'ok': True, 'session_id': session_id, 'method': 'primary',
                'verified': promoted, 'refused': refused, 'promoted': changed,
                'ledger_dir': sess.as_posix()}

    promoted, refused = [], []
    for cid in wanted:
        if claims[cid].get('status') == 'verified':
            promoted.append(cid)      # 已证实的不重写：重写会动账本指纹，让旧戳白失效
            continue
        srcs = led.sources_for_claim(cid)
        packed = [{'title': s.get('title', ''), 'url': s.get('url', ''),
                   'tier': s.get('tier')} for s in srcs]
        domains = sorted({d for d in (_registered_domain(s['url']) for s in packed) if d})
        groups = effective_independent_count(packed)
        if len(domains) >= 2 and groups >= 2:
            promoted.append(cid)
            continue
        if not packed:
            reason = '该 claim 没有任何来源，无从交叉验证'
        elif len(domains) < 2:
            reason = (f'独立注册域只有 {len(domains)} 个（{"、".join(domains) or "无"}），'
                      f'档 A 要求 ≥2 个不同注册域；归属型断言改走 method=primary')
        else:
            reason = f'{len(packed)} 条来源去重后只剩 {groups} 组（疑似同一通稿转载），不算独立证据'
        refused.append({'claim_id': cid, 'reason': reason})

    # 一次整文件重写：逐条调用会让 n 条 claim 触发 n 次全量落盘
    to_write = [c for c in promoted if claims[c].get('status') != 'verified']
    if to_write:
        led.set_status(to_write, 'verified',
                       note=note or '机器交叉验证：每条 ≥2 个不同注册域且转载去重后 ≥2 组',
                       extra={'verified_via': 'cross_validation'})
    return {'ok': True, 'session_id': session_id, 'method': 'cross',
            'verified': promoted, 'refused': refused, 'promoted': len(to_write),
            'warnings': ([] if promoted else
                         ['一条都没升上去：报告里的引用仍会被发布门按未验证拦截']),
            'ledger_dir': sess.as_posix()}


def _gate_of(sess: Path, report_path: str) -> Dict[str, Any]:
    _load_scripts()
    from validate_report import validate_report
    md = Path(report_path).read_text(encoding='utf-8', errors='ignore')
    rep = validate_report(md, ledger_dir=str(sess))
    return {'passed': rep.passed, 'issues': list(rep.issues),
            'warnings': list(rep.warnings), 'stats': dict(rep.stats)}


def drux_gate_check(session_id: str, report_path: str = '',
                    workspace: str = '') -> Dict[str, Any]:
    """只读跑发布门，并顺带验一次防伪戳与正文/账本是否仍一致。"""
    sess = _session_dir(session_id, workspace)
    if not (sess / 'ledger.jsonl').exists():
        return _fail(f'账本不存在：{sess.as_posix()}/ledger.jsonl',
                     '确认 session_id 与 workspace 指向 drux_session_start 建出的那次调研')
    if not report_path or not Path(report_path).exists():
        return _fail(f'报告文件不存在：{report_path or "(未传 report_path)"}',
                     '把写好的 report.md 绝对路径传进来')
    _load_scripts()
    from validate_report import verify_stamp
    try:
        gate = _gate_of(sess, report_path)
    except Exception as exc:
        return _fail(f'校验执行失败：{type(exc).__name__}: {exc}',
                     '确认 report_path 是 UTF-8 文本、账本目录没被手改坏')
    stamp_ok, stamp_reason = verify_stamp(
        Path(report_path).read_text(encoding='utf-8', errors='ignore'), str(sess))
    return {'ok': True, 'session_id': session_id, 'report_path': str(Path(report_path)),
            'ledger_dir': sess.as_posix(), 'stamp_valid': stamp_ok,
            'stamp_reason': stamp_reason, **gate}


def drux_stamp_issue(session_id: str, report_path: str = '',
                     workspace: str = '') -> Dict[str, Any]:
    """内部先跑一遍门，过了才盖戳并落 gate.json；不过门一条字节都不写。"""
    checked = drux_gate_check(session_id, report_path, workspace)
    if not checked.get('ok'):
        return checked
    if not checked.get('passed'):
        return _fail('发布门未通过，不产出校验戳',
                     '按 issues 逐条补证据或改正文，改完重跑 drux_stamp_issue',
                     issues=checked['issues'], warnings=checked['warnings'],
                     ledger_dir=checked['ledger_dir'])

    _load_scripts()
    from validate_report import _ledger_fingerprint, _parse_stamp, write_stamp
    sess = Path(checked['ledger_dir'])
    line = write_stamp(report_path, str(sess), checked['stats'])
    md = Path(report_path).read_text(encoding='utf-8', errors='ignore')
    stamp = _parse_stamp(md)
    receipt = {'report_sha': stamp.get('body', ''),
               'ledger_sha': stamp.get('ledger', ''),
               'passed': True,
               'issues_hash': _hash_issues(checked['issues']),
               'issued_at': datetime.now().isoformat(timespec='seconds'),
               'skill_version': _skill_version()}
    (sess / 'gate.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2),
                                    encoding='utf-8')
    return {'ok': True, 'stamp_line': line, 'body_sha': receipt['report_sha'],
            'ledger_sha': receipt['ledger_sha'], 'gate_path': (sess / 'gate.json').as_posix(),
            'ledger_dir': sess.as_posix(), 'stats': checked['stats']}


def _hash_issues(issues: List[str]) -> str:
    import hashlib
    return hashlib.sha256('|'.join(issues).encode('utf-8')).hexdigest()[:16]


def _skill_version() -> str:
    _load_scripts()
    from research import skill_version
    return skill_version()


TOOLS = [drux_session_start, drux_claim_add, drux_claim_verify,
         drux_gate_check, drux_stamp_issue]


def build_server():
    from mcp.server.mcpserver import MCPServer
    srv = MCPServer('deep-research-ultra')
    for fn in TOOLS:
        srv.tool()(fn)
    return srv


def main() -> int:
    try:
        srv = build_server()
    except ImportError as exc:  # 缺依赖必须显式失败，不许静默
        # 纯 ASCII：宿主按 UTF-8 读子进程 stderr，中文提示会在读取端炸掉并丢失
        print(f'drux-mcp requires the python mcp package: pip install "mcp>=2.1" ({exc})',
              file=sys.stderr)
        return 1
    srv.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
