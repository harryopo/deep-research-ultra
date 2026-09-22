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


# ---------------------------------------------------------------------------
# 第 10 条：归一之后"命中了什么"要能解释（反馈原话：有告警行，但归一后
# 命中的是什么已不可解释）
# ---------------------------------------------------------------------------

GH_LONG = 'LLM judge versus execution based evaluation code correctness'


def _gh_engine(monkeypatch, captured):
    """把桶搜索换成假实现，只留归一与记账这条真链路。"""
    from engines.base import SearchResult
    from engines.github_deep_search import GitHubDeepSearchEngine

    def _fake_bucket(query, **kw):
        captured.append(query)
        return [SearchResult(title='some/repo', url='https://github.com/some/repo',
                             content='命中', source='github-deep-search',
                             engine='github-deep-search')]

    eng = GitHubDeepSearchEngine()
    monkeypatch.setattr(eng, '_search_bucket', _fake_bucket)
    monkeypatch.setattr(eng, '_search_dependents', lambda *a, **k: [])
    monkeypatch.setattr(eng, '_search_awesome', lambda *a, **k: [])
    return eng


def test_warning_names_the_dropped_words(monkeypatch, capsys):
    """告警必须说清"哪些词没进查询"，否则 Lead 无从判断命中答不答得上问题。"""
    captured = []
    eng = _gh_engine(monkeypatch, captured)
    eng.search(GH_LONG, max_results=8)
    err = capsys.readouterr().err
    effective = captured[0]
    assert effective in err, '告警要给出实际发出去的查询'
    for word in GH_LONG.split():
        if word.lower() not in effective.split():
            assert word.lower() in err, f'被丢掉的词 {word!r} 没交代'
            break


def test_hit_records_the_query_that_matched(monkeypatch):
    """结果本身要带上命中用的查询词。

    告警行会滚走，JSON/账本才是 Lead 事后读的东西：一条仓库记录如果说不出
    "它是被哪三个词捞上来的"，就没法判断它跟原始问题相不相干。
    """
    captured = []
    eng = _gh_engine(monkeypatch, captured)
    results = eng.search(GH_LONG, max_results=8)
    assert results, '假桶给了 1 条，不该空手回来'
    effective = captured[0]
    for r in results:
        assert r.query == effective, f'结果没记命中查询：{r.query!r} != {effective!r}'
        assert r.to_dict()['query'] == effective, 'to_dict 丢了 query，JSON 里看不见'


# ---------------------------------------------------------------------------
# 第 13 条：六维质量门按"报告里有没有仓库链接"触发，误伤引用型报告
# （反馈原话：建议加显式声明位，如报告写"选型调研: 否"即豁免六维、
#   改查"引用性事实是否带来源"）
# ---------------------------------------------------------------------------

def _sparse_report(extra_line=''):
    """一份只把仓库当证据引用、没有六维要素的报告。"""
    return f'''# 报告
{extra_line}
## 执行摘要
推荐项目X [1] https://github.com/a/b。
## 调研范围与方法
m
## 结论与建议
c
## 来源
[1] https://github.com/a/b [2] https://gitee.com/a/b2
'''


def _ledger_with_repos(tmp_path):
    from ledger import ResearchLedger
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    c1 = L.add_claim('项目X 可用', '开源', 'verified', 'general', 0.9)
    L.add_source(c1['id'], 'https://github.com/a/b', tier=2)
    L.add_source(c1['id'], 'https://gitee.com/a/b2', tier=2)
    return L


def test_declaring_no_selection_survey_exempts_six_dims(tmp_path):
    """写"选型调研: 否"就该免掉六维——方法论报告被要求补许可证/最近提交是误伤。"""
    from validate_report import validate_report
    r = validate_report(_sparse_report('选型调研: 否'), ledger=_ledger_with_repos(tmp_path))
    assert not any('六维' in i for i in r.issues), f'豁免没生效：{r.issues}'
    assert r.passed is True, f'豁免后应真的过门，实际：{r.issues}'


def test_declaring_yes_keeps_the_six_dims(tmp_path):
    from validate_report import validate_report
    r = validate_report(_sparse_report('选型调研: 是'), ledger=_ledger_with_repos(tmp_path))
    assert any('六维' in i for i in r.issues), '声明是选型调研，六维门必须照旧'


def test_exemption_still_requires_each_repo_to_be_sourced(tmp_path):
    """豁免六维不等于豁免溯源：被当证据引用的仓库仍要到账本里找得到。"""
    from validate_report import validate_report
    L = _ledger_with_repos(tmp_path)
    r = validate_report(
        _sparse_report('选型调研: 否') + '另见 https://github.com/zzz/untracked。\n',
        ledger=L)
    bad = [i for i in r.issues if 'untracked' in i]
    assert bad, f'没账本的仓库链接该被点名，实际：{r.issues}'


def test_gate_without_declaration_tells_how_to_declare(tmp_path):
    """没声明时仍然拦，但要把豁免口写给 Lead 看，别让人以为只能去补六维。"""
    from validate_report import validate_report
    r = validate_report(_sparse_report(), ledger=_ledger_with_repos(tmp_path))
    hits = [i for i in r.issues if '六维' in i]
    assert hits, '未声明时六维门应照旧生效'
    assert '选型调研' in hits[0], f'拦截语要给出声明位：{hits[0]}'


def test_skeleton_offers_the_declaration_slot_only_for_repo_reports(tmp_path):
    """骨架要把声明位递到人手上；默认必须是"是"（从严），不能白送豁免。"""
    from ledger import ResearchLedger
    from skeleton import build_skeleton

    with_repo = ResearchLedger(str(tmp_path / 'l1')).init()
    c = with_repo.add_claim('仓库 X 能做这事', '开源', 'verified', 'general', 0.9)
    with_repo.add_source(c['id'], 'https://github.com/a/b', tier=2)
    body = build_skeleton(str(tmp_path / 'l1'))
    assert '选型调研: 是' in body, '含仓库来源的骨架要给出自带默认从严的声明位'

    no_repo = ResearchLedger(str(tmp_path / 'l2')).init()
    c2 = no_repo.add_claim('论文说这事有效', '学术', 'verified', 'general', 0.9)
    no_repo.add_source(c2['id'], 'https://arxiv.org/abs/2401.00001', tier=1)
    assert '选型调研' not in build_skeleton(str(tmp_path / 'l2')), '与仓库无关的报告别塞这行'


# ---------------------------------------------------------------------------
# 反馈 #15：CLI 这条链要给 Stop 钩子留下会话身份证
# ---------------------------------------------------------------------------

def test_cli_ledger_init_leaves_a_session_marker(tmp_path):
    """钩子靠 session.json 找到会话并定位账本在哪一层；缺它则 CLI 跑一轮，钩子一条都看不见。"""
    from datetime import datetime

    sess = tmp_path / '.research' / 'drux-cli-run'
    ResearchLedger(str(sess / 'ledger')).init()
    marker = sess / 'session.json'
    assert marker.exists(), 'CLI 账本 init 后没有 session.json，Stop 钩子会一条会话都找不到'
    info = json.loads(marker.read_text(encoding='utf-8'))
    assert info['ledger_dir'] == 'ledger', f'账本在下一层，身份证要写清：{info}'
    assert info['session_id'] == 'drux-cli-run', f'会话名是那一轮调研，不是账本目录：{info}'
    # 存不成时间戳就别怪钩子把整轮判成遗留
    assert datetime.fromisoformat(info['started_at'])


def test_re_running_init_does_not_move_the_session_start(tmp_path):
    """init 幂等：已有身份证就不覆盖。重跑把 started_at 刷成"刚刚"，旧报告会被判成本轮新交付。

    取一个远处的时间戳当锚点，而不是连着 init 两次比字符串——两次都在同一秒里，
    覆盖与否都相等，那条断言就白给。
    """
    sess = tmp_path / '.research' / 'drux-cli-run'
    (sess / 'ledger').mkdir(parents=True)
    marker = sess / 'session.json'
    marker.write_text(json.dumps({'session_id': 'old', 'started_at': '2020-01-01T00:00:00',
                                  'query': '别丢掉我'}, ensure_ascii=False), encoding='utf-8')
    L = ResearchLedger(str(sess / 'ledger')).init()
    info = json.loads(marker.read_text(encoding='utf-8'))
    assert info['started_at'] == '2020-01-01T00:00:00', f'重跑 init 改写了会话起点：{info}'
    assert info['query'] == '别丢掉我', f'重跑 init 覆盖了 MCP 写的字段：{info}'
    assert L.entries_path.exists(), '不覆盖身份证不等于跳过建账本'
