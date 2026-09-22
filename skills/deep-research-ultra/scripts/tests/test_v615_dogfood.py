"""2026-09-22 一次真跑（5 子研究员 / 61 claim / 过门盖戳）交回的缺陷清单。

每条测试都对应反馈文件里一个可复现动作，判据取用户原话：
「把已有 URL 原样重填一遍就能升 verified，而同一论文的真实不同表示反被拒」。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import ResearchLedger  # noqa: E402

ABS_URL = 'https://arxiv.org/abs/2509.20364'


def _led(tmp_path):
    return ResearchLedger(str(tmp_path / 'ledger')).init()


# ---------------------------------------------------------------------------
# 档 B：反查必须换一个访问通道，不能把已有来源再填一遍
# ---------------------------------------------------------------------------

def test_replaying_an_existing_url_must_not_upgrade(tmp_path, capsys):
    """反馈 #1：verify_primary 做的是 URL 集合成员判断，零验证动作即可自批。"""
    L = _led(tmp_path)
    c = L.add_claim('原文说 X', 'LLM', 'pending')
    L.add_source(c['id'], ABS_URL)
    assert L.verify_primary([c['id']], ABS_URL, method='abs-page') == 0
    err = capsys.readouterr().err
    assert '重填' in err or '另一个通道' in err, '拒绝理由要教 Lead 下一步怎么做'
    assert [x['status'] for x in L.export_json()['claims'] if x['id'] == c['id']] == ['pending']


@pytest.mark.parametrize('alt', [
    'https://arxiv.org/pdf/2509.20364',
    'https://arxiv.org/pdf/2509.20364v1.pdf',
    'https://arxiv.org/html/2509.20364v5',
    'https://export.arxiv.org/api/query?id_list=2509.20364',
])
def test_other_channel_of_the_same_paper_upgrades(tmp_path, alt):
    """反馈 #1 的反面：/abs 与 /pdf、/html、OAI 接口是同一篇论文，必须认。"""
    L = _led(tmp_path)
    c = L.add_claim('原文说 X', 'LLM', 'pending')
    L.add_source(c['id'], ABS_URL)
    assert L.verify_primary([c['id']], alt, method='fulltext-read') == 1


def test_a_different_paper_is_still_not_a_check(tmp_path):
    """跨表示归一不能顺手把"另一篇论文存在"记成本条的凭据（D12 的原有职责）。"""
    L = _led(tmp_path)
    a = L.add_claim('NL2Bash 说了 X', 'LLM', 'pending')
    b = L.add_claim('NaSh 说了 Y', 'LLM', 'pending')
    L.add_source(a['id'], 'https://arxiv.org/abs/1802.08979')
    L.add_source(b['id'], 'https://arxiv.org/abs/2506.13028')
    assert L.verify_primary([a['id'], b['id']],
                            'https://arxiv.org/pdf/1802.08979') == 1
    st = {x['id']: x['status'] for x in L.export_json()['claims']}
    assert st[a['id']] == 'verified' and st[b['id']] == 'pending'


def test_github_api_channel_of_a_blob_source_upgrades(tmp_path):
    """反馈 #4 的正解：同一发布方的两个通道归档 B 管，不去松档 A 的独立域判据。"""
    L = _led(tmp_path)
    c = L.add_claim('该仓库没有 CI 配置', 'skill生态', 'pending')
    L.add_source(c['id'], 'https://github.com/anthropics/skills/blob/main/README.md')
    assert L.verify_primary(
        [c['id']], 'https://api.github.com/repos/anthropics/skills/contents/README.md',
        method='gh-api') == 1


# ---------------------------------------------------------------------------
# 分片协议：照 SKILL.md 写的容器形状必须被 merge 收下
# ---------------------------------------------------------------------------

def test_merge_accepts_the_documented_container_shape(tmp_path):
    """反馈 #2：文档让子 Agent 写 {slug}.json，merge 却只认扁平 type 记录。"""
    L = _led(tmp_path)
    shard = L.root / 'D1-gates.json'
    shard.write_text(json.dumps({
        'claims': [{'id': 'c-one', 'text': '静态门只查结构', 'topic': 'gates',
                    'confidence': 0.7}],
        'sources': [{'claim_id': 'c-one', 'url': 'https://example.test/a',
                     'title': 'A', 'tier': 2}],
    }, ensure_ascii=False), encoding='utf-8')
    claims, sources = L.merge(str(L.root))
    assert (claims, sources) == (1, 1)
    out = L.export_json()
    assert [c['text'] for c in out['claims']] == ['静态门只查结构']
    assert out['claims'][0]['status'] == 'pending', '合并动作不能自己批准结论'


def test_merge_rejection_names_the_file(tmp_path, capsys):
    """拒收 5 条 = 整份分片没了。计数必须点名到文件与原因，否则没人知道丢了什么。"""
    L = _led(tmp_path)
    (L.root / 'D2-bad.json').write_text(
        json.dumps([{'text': '没有 type 的记录'}]), encoding='utf-8')
    L.merge(str(L.root))
    err = capsys.readouterr().err
    assert 'D2-bad.json' in err and 'type' in err


def test_flat_records_still_work(tmp_path):
    """兼容既有形状：扁平 type 记录不能因为收容器而失效。"""
    L = _led(tmp_path)
    (L.root / 'flat.jsonl').write_text(
        json.dumps({'type': 'claim', 'id': 'c-flat', 'text': '扁平记录'}) + '\n',
        encoding='utf-8')
    assert L.merge(str(L.root))[0] == 1


def test_broken_json_shard_says_so(tmp_path, capsys):
    """语法错的产物不能读成"0 条"就过去——那和丢数据长得一模一样。"""
    L = _led(tmp_path)
    (L.root / 'D3-broken.json').write_text('{"claims": [ 缺右括号', encoding='utf-8')
    L.merge(str(L.root))
    err = capsys.readouterr().err
    assert 'D3-broken.json' in err and 'JSON' in err


# ---------------------------------------------------------------------------
# 反馈 #8：一个引擎挂掉不得把整次查询判 0（锁死语义，防后续改回早停）
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, i):
        self.title = f'静态门研究 {i}'
        self.url = f'https://example.org/{i}'
        self.content = '静态门只查结构，不查质量'
        self.source = 'live'
        self.score = 1.0
        self.craap_score = None
        self.published_date = ''
        self.author = ''
        self.engine = 'live'

    def to_dict(self):
        return {k: getattr(self, k) for k in
                ('title', 'url', 'content', 'source', 'score',
                 'craap_score', 'published_date', 'author', 'engine')}


class _FakeEngine:
    def __init__(self, name, behaviour):
        self.name, self.behaviour = name, behaviour

    def get_name(self):
        return self.name

    def has_capability(self, cap):
        return cap == 'search'

    def search(self, query, max_results=10, **kw):
        if self.behaviour == 'none':       # 基类契约：没取到数据
            return None
        if self.behaviour == 'boom':
            raise RuntimeError('HTTP 406')
        if self.behaviour == 'empty':
            return []
        return [_FakeResult(i) for i in range(max_results)]


class _FakeRegistry:
    def __init__(self, engines):
        self._engines = engines

    def get_fallback_chain(self):
        return list(self._engines)

    def get_engine(self, name):
        return next(e for e in self._engines if e.name == name)

    def list_engines(self, *a, **k):
        return []


def _run_search(monkeypatch, capsys, engines, extra=()):
    import research
    argv = ['research.py', '静态打分门能否当质量验收门', '--sources',
            ','.join(e.name for e in engines), '--format', 'json',
            '--no-plan', '--no-cache', '--min-relevance', '0', *extra]
    monkeypatch.setattr(research, 'build_registry', lambda: _FakeRegistry(engines))
    monkeypatch.setattr(sys, 'argv', argv)
    capsys.readouterr()
    try:
        research.main()
        code = 0
    except SystemExit as e:
        code = e.code or 0
    out = capsys.readouterr()
    return code, out


def test_dead_engine_does_not_zero_out_live_one(monkeypatch, capsys):
    """反馈 #8 报的是"整次查询判 0"，实测三条失败路径都 continue，live 引擎照常出数。

    这条锁的是语义本身：以后谁把降级链改成"遇错即停"，本测试立刻红。
    """
    engines = [_FakeEngine('dead', 'none'), _FakeEngine('boom', 'boom'),
               _FakeEngine('quiet', 'empty'), _FakeEngine('live', 'ok')]
    code, out = _run_search(monkeypatch, capsys, engines)
    assert code == 0, out.err
    data = json.loads(out.out)
    assert 'live' in data['used_engines']
    assert len(data['results']) >= 1


def test_all_engines_dead_exits_1_and_names_cause(monkeypatch, capsys):
    """全挂时才是硬失败，且必须区分"没取到数据"与"调通了但 0 结果"。"""
    engines = [_FakeEngine('dead', 'none'), _FakeEngine('quiet', 'empty')]
    code, out = _run_search(monkeypatch, capsys, engines)
    assert code == 1
    assert '未取到数据: dead' in out.err
    assert '已调通但 0 结果: quiet' in out.err


# ---------------------------------------------------------------------------
# 反馈 #6 / #7：命令行为与文档不符的两处
# ---------------------------------------------------------------------------

def test_json_output_honors_dash_o(tmp_path, monkeypatch, capsys):
    """`--format json -o x.json` 过去只打 stdout、不落盘，逼人改用 shell 重定向。"""
    dest = tmp_path / 'out.json'
    engines = [_FakeEngine('live', 'ok')]
    code, out = _run_search(monkeypatch, capsys, engines,
                            extra=['-o', str(dest)])
    assert code == 0
    assert dest.exists(), '-o 指定了就必须落盘'
    assert json.loads(dest.read_text(encoding='utf-8'))['used_engines'] == ['live']
    assert out.out.strip() == '', '落盘后不再往 stdout 灌整份 JSON'


def test_set_status_can_amend_text_without_a_new_status(tmp_path, capsys):
    """反馈 #6：想就地更正一句写错的原文，却被迫先送一个 status。"""
    from ledger import _main
    L = _led(tmp_path)
    c = L.add_claim('κ 只有 0.21（抄错）', 'LLM', 'pending')
    rc = _main(['set-status', '--session', str(L.root),
                '--claim-id', c['id'], '--text', 'κ=0.21（Java，逐字核对全文）'])
    assert rc == 0, capsys.readouterr().err
    got = [x for x in L.export_json()['claims'] if x['id'] == c['id']][0]
    assert '逐字核对' in got['text']
    assert got['status'] == 'pending', '只改文字不该顺手把状态也定了'


def test_set_status_still_names_what_is_missing(tmp_path, capsys):
    """两个都没有时才报错，且要说清缺哪个。"""
    from ledger import _main
    L = _led(tmp_path)
    c = L.add_claim('结论', 'LLM', 'pending')
    rc = _main(['set-status', '--session', str(L.root), '--claim-id', c['id']])
    assert rc == 2
    err = capsys.readouterr().err
    assert '--status' in err and '--text' in err


def test_unverified_claims_do_not_become_placeholders(tmp_path):
    """反馈 #16：一次实跑 61 条 claim 逼出 40 处【待写】，逐条处置超出单轮产能，
    最后只能拿模板句把标记刷没——那正是骨架要避免的"看起来完成"。"""
    from skeleton import PLACEHOLDER, build_skeleton
    L = _led(tmp_path)
    for i in range(30):
        c = L.add_claim(f'未验证结论{i}', 'LLM', 'pending')
        L.add_source(c['id'], f'https://example.org/{i}')
    c = L.add_claim('冲突结论', 'LLM', 'conflict')
    L.add_source(c['id'], 'https://example.org/x')
    md = build_skeleton(str(L.root))
    assert sum(1 for ln in md.splitlines()
               if ln.startswith('- ⚠️ 仅作线索')) == 30
    assert md.count(PLACEHOLDER) <= 5, \
        f'待写标记 {md.count(PLACEHOLDER)} 处：必须与 claim 条数解耦，只留机器写不了的几处'


# ---------------------------------------------------------------------------
# 传输层降级要看得见（反馈 #5 的现场根因）
# ---------------------------------------------------------------------------

def test_missing_curl_cffi_says_so_once(monkeypatch, capsys):
    """curl_cffi 没装 → 所有引擎裸走 urllib，反爬站点的 4xx 由此而来。

    静默降级等于让 Lead 拿一套没有 TLS 指纹的传输层去判"这个源不行"，
    判据本身就脏了。缺什么、怎么补，必须在第一次请求时说一次。
    """
    import urllib.error

    import engines.fallback as fb
    monkeypatch.setitem(sys.modules, 'curl_cffi', None)
    monkeypatch.setattr(fb, '_TRANSPORT_NOTICE_SHOWN', False)

    class _Opener:
        def open(self, *a, **kw):
            raise urllib.error.URLError('no route')

    monkeypatch.setattr(fb.urllib.request, 'build_opener', lambda *a, **kw: _Opener())

    assert fb._http_get('https://example.invalid/q', max_retries=1) is None
    assert fb._http_get('https://example.invalid/q2', max_retries=1) is None
    err = capsys.readouterr().err
    assert err.count('curl_cffi 未安装') == 1, '降级要说，但每次请求刷一行会把日志埋掉'
    assert 'pip install curl_cffi' in err
