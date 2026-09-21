"""计划 B1：server.py 四个业务工具的契约测试（不起进程，直接 import）。

契约逐条来自 spec 第六节，判据都是"这一条不成立会导致什么后果"：
- 返回值恒含 ok，失败必须长得像失败（不许返回看起来成功的空结果）
- 不可溯源 URL 拒收；调用方自称 verified 一律忽略
- drux_stamp_issue 内部先跑 gate，不过门不产出戳
- 戳与正文/账本指纹绑定；gate.json 与戳一致（hook 靠这个交叉比对）
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'deep-research-ultra' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


GATE_OK = {
    'available': ['openalex', 'arxiv-mcp', 'github-deep-search'],
    'layers': [1, 2],
    'primary_channels': ['openalex'],
    'blockers': [],
    'guidance': ['baidu-serp 未配置 BAIDU_SERP_KEY'],
}

GATE_BLOCKED = {
    'available': [],
    'layers': [],
    'primary_channels': [],
    'blockers': ['真出数据的引擎只有 0 个（< 3），证据链无法交叉验证',
                 '可用源里没有任何一手制品通道（论文库/代码仓库）'],
    'guidance': ['TAVILY_API_KEY 未配置：去哪配 …'],
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """工作区 + 默认放行闸门（网络探针不在单测里跑，见 run_gate 的注入点）。"""
    workspace = tmp_path / '项目 目录'   # 带空格：路径处理不许靠 shell 分词
    workspace.mkdir()
    monkeypatch.setattr(server, 'run_gate', lambda sources=None: dict(GATE_OK))
    return workspace


def _start(ws, **kw):
    r = server.drux_session_start('边缘推理现状', workspace=ws, **kw)
    assert r['ok'], f'开局失败：{r}'
    return r


# ---------------------------------------------------------------- session_start

def test_session_start_creates_writable_ledger_dir(ws):
    r = _start(ws, effort='standard', dimensions=['技术', '市场'])
    sess = ws / '.research' / r['session_id']
    assert (sess / 'ledger.jsonl').exists(), '账本没建出来，claim_add 之后会无处可写'
    info = json.loads((sess / 'session.json').read_text(encoding='utf-8'))
    assert info['query'] == '边缘推理现状' and info['effort'] == 'standard'
    assert info['started_at'], 'hook 要靠 started_at 认"哪次调研"，缺它只能猜 mtime'
    assert Path(r['ledger_dir']) == sess
    assert r['usable_engines'] == GATE_OK['available']
    assert r['dimensions'] == ['技术', '市场']


def test_blocked_gate_refuses_session_and_gives_config_guide(ws, monkeypatch):
    """环境闸门不过就不建 session —— 这是用户第一条硬要求（先配环境再开跑）。"""
    monkeypatch.setattr(server, 'run_gate', lambda sources=None: dict(GATE_BLOCKED))
    r = server.drux_session_start('x', workspace=ws)
    assert not r['ok']
    assert r['issues'] == GATE_BLOCKED['blockers']
    assert r['config_guide'], '只说"不够"不给"去哪配"，用户没法动手'
    assert not (ws / '.research').exists(), '闸门没过却建了 session，Lead 会当成功继续跑'


def test_allow_degraded_only_when_user_says_so(ws, monkeypatch):
    """用户明确"不配了，直接下一步"才放行，且回执必须把缺口继续挂着，不许洗白。"""
    monkeypatch.setattr(server, 'run_gate', lambda sources=None: dict(GATE_BLOCKED))
    r = server.drux_session_start('x', workspace=ws, allow_degraded=True)
    assert r['ok'], '用户已授权降级，工具不该替他拒绝'
    assert r['degraded'] and r['issues'] == GATE_BLOCKED['blockers']


def test_session_start_gate_failure_is_not_swallowed(ws, monkeypatch):
    """闸门自身抛异常必须报成 ok:false，不能让它在 MCP 里变成握手层的莫名失败。"""
    def boom(sources=None):
        raise RuntimeError('engines 目录缺失')
    monkeypatch.setattr(server, 'run_gate', boom)
    r = server.drux_session_start('x', workspace=ws)
    assert not r['ok'] and 'engines 目录缺失' in r['error'] and r['hint']


# ------------------------------------------------------------------- claim_add

def test_claim_add_stores_chinese_text_verbatim(ws):
    sid = _start(ws)['session_id']
    text = '某论文声称「端侧推理延迟 < 20ms」——含全角？'
    r = server.drux_claim_add(sid, text, topic='性能', workspace=ws,
                              sources=[{'url': 'https://arxiv.org/abs/2501.00001',
                                        'title': 'Edge Inference'}])
    assert r['ok'] and r['claim_id'], r
    lines = (Path(r['ledger_dir']) / 'ledger.jsonl').read_text(encoding='utf-8').splitlines()
    claim = json.loads([ln for ln in lines if '"claim"' in ln][-1])
    assert claim['text'] == text, '中文入库被转义/截断，报告里的引文就对不上原文'
    assert claim['status'] == 'pending'


def test_untraceable_sources_rejected_with_reason(ws):
    """站内跳转 / 空 / 非 http 都点不回原文，记进账本等于伪造溯源。"""
    sid = _start(ws)['session_id']
    r = server.drux_claim_add(sid, '归属型结论', workspace=ws, sources=[
        {'url': '/link?url=abc123', 'title': '百度跳转'},
        {'url': '', 'title': '空'},
        {'url': 'javascript:void(0)', 'title': '伪链接'},
        {'url': 'https://example.com/a', 'title': '真链接'},
    ])
    assert [x['url'] for x in r['rejected_sources']] == ['/link?url=abc123', '',
                                                         'javascript:void(0)'], r
    assert [a['url'] for a in r['accepted']] == ['https://example.com/a']
    assert all(isinstance(a['tier'], int) for a in r['accepted']), 'tier 没自动分级，来源权重就得手写'
    assert all(x['reason'] for x in r['rejected_sources']), '拒收必须说清为什么拒'


def test_self_declared_verified_is_ignored(ws):
    """verified 只能由交叉验证/一手反查赋予：调用方自标一律忽略并回注 warning。"""
    sid = _start(ws)['session_id']
    r = server.drux_claim_add(sid, '未验证结论', workspace=ws, status='verified',
                              sources=[{'url': 'https://example.com/one'}])
    lines = (Path(r['ledger_dir']) / 'ledger.jsonl').read_text(encoding='utf-8').splitlines()
    claim = json.loads([ln for ln in lines if '"claim"' in ln][-1])
    assert claim['status'] == 'pending', '自标 verified 被照收，账本覆盖率就是虚高的'
    assert any('verified' in w for w in r['warnings']), '忽略了却不说，调用方会以为已升级'


def test_claim_add_on_unknown_session_fails_loudly(ws):
    r = server.drux_claim_add('drux-不存在', 'x', workspace=ws,
                              sources=[{'url': 'https://example.com'}])
    assert not r['ok'] and 'drux-不存在' in r['error'] and r['hint'], \
        '路径错了却建出空账本，正是 D8 那条老坑的翻版'


# --------------------------------------------------------- gate_check / stamp

# 一份"真能过门"的报告要同时满足：四章节齐、每个被引 claim 已 verified、
# 每条 verified 有 ≥2 独立注册域、正文引用能映射回账本编号。
# 造不出来就说明工具链有断点 —— 下面的 drux_claim_verify 正是那个断点的补法。
GOOD_REPORT = """# 边缘推理调研

## 执行摘要
量化后端侧推理延迟低于 20ms [1][2]；移动端需专用算子支持 [3][4]。

## 调研范围与方法
覆盖论文库与学术索引两类一手来源，每条结论要求两个独立注册域交叉验证。

## 结论与建议
建议在端侧采用量化模型并配专用算子 [3]。

## 参考资料
[1] https://arxiv.org/abs/2501.00001 —— Edge Inference Latency
[2] https://www.openreview.net/forum?id=abc123 —— Rebuttal on same measurement
[3] https://dl.acm.org/doi/10.1145/35.36 —— Mobile Operators
[4] https://www.semanticscholar.org/paper/9f8e7d6c —— Operators survey
"""

# 四组来源分属两条 claim，写入顺序决定账本编号 [1][2] → 第一条，[3][4] → 第二条
GOOD_CLAIMS = [
    ('端侧推理在量化后延迟低于 20ms',
     ['https://arxiv.org/abs/2501.00001', 'https://www.openreview.net/forum?id=abc123']),
    ('量化模型在移动端需专用算子支持',
     ['https://dl.acm.org/doi/10.1145/35.36',
      'https://www.semanticscholar.org/paper/9f8e7d6c']),
]


def _session_with_verified_claims(ws, claims=GOOD_CLAIMS):
    """建 session → 灌 claim+来源 → 走机器判定的交叉验证升级。"""
    sid = _start(ws)['session_id']
    ids = []
    for text, urls in claims:
        r = server.drux_claim_add(sid, text, topic='性能', workspace=ws,
                                  sources=[{'url': u, 'title': u.rsplit('/', 1)[-1]}
                                           for u in urls])
        assert r['ok'], r
        ids.append(r['claim_id'])
    v = server.drux_claim_verify(sid, ids, workspace=ws)
    assert v['ok'] and len(v['verified']) == len(ids), f'该升上去的没升：{v}'
    return sid, ids


def _report(ws, tmp_path, text=GOOD_REPORT):
    p = tmp_path / 'report.md'
    p.write_text(text, encoding='utf-8')
    return p


def test_gate_check_reports_pass_and_fail(ws, tmp_path):
    sid, _ = _session_with_verified_claims(ws)
    good = server.drux_gate_check(sid, str(_report(ws, tmp_path)), workspace=ws)
    assert good['ok'] and good['passed'], f"该过的没过：{good['issues']}"
    assert good['stats'], '没有 stats，报告里的 claims/sources 数就无从核对'

    bad = server.drux_gate_check(sid, str(_report(ws, tmp_path, '# 只有标题\n')),
                                 workspace=ws)
    assert bad['ok'] and not bad['passed'] and bad['issues'], '不过门却没给 issues'


def test_stamp_issue_refuses_when_gate_fails(ws, tmp_path):
    """不过门拿不到戳：戳是"机器门过了"的唯一凭据，给了就等于放行假报告。"""
    sid, _ = _session_with_verified_claims(ws)
    path = _report(ws, tmp_path, '# 缺章节的报告\n')
    before = Path(path).read_text(encoding='utf-8')
    r = server.drux_stamp_issue(sid, str(path), workspace=ws)
    assert not r['ok'] and r['issues'] and r['hint']
    assert Path(path).read_text(encoding='utf-8') == before, '没过门却被写入了戳'
    assert not (Path(r['ledger_dir']) / 'gate.json').exists()


def test_stamp_binds_body_and_ledger(ws, tmp_path):
    sid, _ = _session_with_verified_claims(ws)
    path = _report(ws, tmp_path)
    got = server.drux_stamp_issue(sid, str(path), workspace=ws)
    assert got['ok'], got
    assert 'drux:validated' in Path(path).read_text(encoding='utf-8')

    gate = json.loads((Path(got['ledger_dir']) / 'gate.json').read_text(encoding='utf-8'))
    assert gate['report_sha'] == got['body_sha'], 'gate.json 与戳不一致，hook 会误判'
    assert gate['ledger_sha'] == got['ledger_sha'] and gate['passed'] is True
    assert gate['skill_version'], '没记版本，事后无法判断是哪一版放行的'

    # 盖戳之后改正文 → 戳必须失效（这正是防伪戳存在的理由）
    Path(path).write_text(Path(path).read_text(encoding='utf-8').replace(
        '端侧推理延迟低于 20ms', '端侧推理延迟低于 5ms（自创数据）'), encoding='utf-8')
    check = server.drux_gate_check(sid, str(path), workspace=ws)
    assert check['ok'] and not check['stamp_valid'], '正文改了戳还有效，戳就是装饰品'


def test_second_claim_after_stamp_invalidates_ledger_match(ws, tmp_path):
    """盖戳后又加 claim → 账本指纹变了，旧戳不再算数。"""
    sid, _ = _session_with_verified_claims(ws)
    path = _report(ws, tmp_path)
    assert server.drux_stamp_issue(sid, str(path), workspace=ws)['ok']
    late = server.drux_claim_add(sid, '事后追加的一条', topic='性能', workspace=ws,
                                 sources=[{'url': 'https://example.com/late'},
                                          {'url': 'https://arxiv.org/abs/2501.99999'}])
    assert late['ok']
    check = server.drux_gate_check(sid, str(path), workspace=ws)
    assert not check['stamp_valid'], '账本变了戳仍有效 = 补数据不用重过门'


# ------------------------------------------------------------------- claim_verify

def test_cross_validation_promotes_only_with_two_independent_domains(ws):
    """verified 由机器判：两个独立注册域才升，单源的一律留在 pending 并说清原因。"""
    sid = _start(ws)['session_id']
    strong = server.drux_claim_add(sid, '两源结论', workspace=ws, sources=[
        {'url': 'https://arxiv.org/abs/2501.00001'},
        {'url': 'https://dl.acm.org/doi/10.1145/35.36'}])
    weak = server.drux_claim_add(sid, '单源结论', workspace=ws,
                                 sources=[{'url': 'https://arxiv.org/abs/2501.00002'},
                                          {'url': 'https://arxiv.org/abs/2501.00003'}])
    r = server.drux_claim_verify(sid, [strong['claim_id'], weak['claim_id']], workspace=ws)
    assert r['ok'] and r['verified'] == [strong['claim_id']]
    assert [x['claim_id'] for x in r['refused']] == [weak['claim_id']]
    assert r['refused'][0]['reason'], '拒了却不说什么原因，Lead 无从补救'


def test_verify_refuses_unknown_claim_and_reports_count(ws):
    sid = _start(ws)['session_id']
    r = server.drux_claim_verify(sid, ['c-不存在'], workspace=ws)
    assert not r['ok'] and 'c-不存在' in r['error'] and r['hint']


def test_verify_respects_ledger_lock(ws):
    """整文件重写类操作必须有并发门：锁在就失败，不排队也不覆盖别人的写入。"""
    sid = _start(ws)['session_id']
    r = server.drux_claim_add(sid, '两源结论', workspace=ws, sources=[
        {'url': 'https://arxiv.org/abs/2501.00001'}, {'url': 'https://dl.acm.org/doi/1.2'}])
    sess = Path(r['ledger_dir'])
    (sess / 'ledger.lock').write_text('subagent-x', encoding='utf-8')
    out = server.drux_claim_verify(sid, [r['claim_id']], workspace=ws)
    assert not out['ok'] and 'ledger.lock' in out['error']
    assert (sess / 'ledger.lock').exists(), 'hook 侧的锁不该被工具顺手删掉'


# ------------------------------------------------------------------- 注册表

def test_business_tools_registered_and_probe_gone():
    names = [f.__name__ for f in server.TOOLS]
    assert names == ['drux_session_start', 'drux_claim_add', 'drux_claim_verify',
                     'drux_gate_check', 'drux_stamp_issue'], names
    assert 'drux_ping' not in names, '探针工具该在计划 B 删除；留着会被当成业务能力'
