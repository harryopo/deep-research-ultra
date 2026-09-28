"""probe.py 单元测试：功能自检的状态判定（不依赖网络）。"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probe import (PROBE_QUERIES, STATUS_EMPTY, STATUS_FAILED, STATUS_OK,
                   STATUS_SKIPPED, classify_probe, probeable_engines,
                   probe_engine, resolve_probe_query, summarize)


@dataclass
class _Meta:
    config_keys: List[str] = field(default_factory=list)
    probe_query: str = ''
    layer: int = 2
    capabilities: List[str] = field(default_factory=lambda: ['search'])
    requires_config: bool = False


class _FakeEngine:
    def __init__(self, name='fake', results=None, available=True, capabilities=('search',),
                 config_keys=(), probe_query='', raises=None, requires_config=None):
        self._name = name
        self._results = results
        self._available = available
        self._capabilities = list(capabilities)
        self._raises = raises
        # 真引擎的写法是"requires_config=True 且列出 key"，替身跟着这个约定走：
        # 给了 config_keys 就按必需项处理，除非调用方显式说明是可选加速项
        self.metadata = _Meta(list(config_keys), probe_query,
                              requires_config=bool(config_keys)
                              if requires_config is None else requires_config)
        self.called_with = None

    def get_name(self):
        return self._name

    def has_capability(self, cap):
        return cap in self._capabilities

    def is_available(self):
        return self._available

    def search(self, query, max_results=10, **kwargs):
        self.called_with = query
        if self._raises:
            raise self._raises
        return self._results


class _Item:
    def __init__(self, title='Vector DB paper', url='https://a.dev', content=''):
        self.title, self.url, self.content = title, url, content


def test_probe_reports_body_completeness():
    """✅ 只证明"出得来条目"，不证明"出得来正文"——逐字引用要的是后者。

    实测缺陷清单 A1（2026-09-28，内核 6.34.5）：open-websearch 探针打 ✅，
    实际每条只有标题、content 全空。Lead 照 ✅ 派"取原文逐字引文"的活，
    一整轮白跑。回执要把这两件事分开印。
    """
    eng = _FakeEngine(results=[_Item(content=''), _Item(content='   ')])
    rep = probe_engine(eng)

    assert rep['status'] == STATUS_OK, '只有标题≠引擎坏了，别改判成不可用（闸门会误停）'
    assert '正文 0/2' in rep['note'], f"没印出正文完整度: {rep['note']}"
    assert '逐字' in rep['note'], '要点醒 Lead：这一档取不到逐字引文'


def test_probe_body_count_when_all_results_have_content():
    """正向对照：条目都带正文时不许出现"正文"字样，别把回执写成长清单。"""
    eng = _FakeEngine(results=[_Item(content='摘要一'), _Item(content='摘要二')])
    rep = probe_engine(eng)

    assert '正文' not in rep['note'], rep['note']


def test_probe_body_count_is_a_ratio_when_partial():
    eng = _FakeEngine(results=[_Item(content='有摘要'), _Item(content='')])
    rep = probe_engine(eng)

    assert '正文 1/2' in rep['note'], rep['note']


class _SeqEngine(_FakeEngine):
    """按脚本回数据的替身：'TIMEOUT' 表示这一发是超时失败（None + client 里的原因）。"""

    def __init__(self, script):
        super().__init__(results=None)
        self.script = list(script)
        self.calls = 0

    def search(self, query, max_results=10, **kwargs):
        self.calls += 1
        out = self.script.pop(0)
        if out == 'TIMEOUT':
            self._client = type('_C', (), {'last_error':
                                           'stub: 超时：整场会话 45s 预算内没等到 tools/call 的响应'})()
            return None
        return out


def _as_mcp(monkeypatch):
    import probe as _probe
    monkeypatch.setattr(_probe, 'engine_kind', lambda e: 'mcp')


def test_mcp_cold_start_timeout_gets_one_reprobe(monkeypatch):
    """npx/uvx 首轮在下包，超一次就判"今天没有"会把配好的源打死。

    实测缺陷清单 A10：MCP server 冷启动在预算内起不来，第二轮才出数据。
    只多给一次，且两次都要在回执里说清——不然 Lead 以为探了两轮坏源。
    """
    _as_mcp(monkeypatch)
    eng = _SeqEngine(['TIMEOUT', [_Item(content='摘要')]])

    rep = probe_engine(eng)

    assert eng.calls == 2, '首轮超时后没有重探'
    assert rep['status'] == STATUS_OK
    assert '冷启动' in rep['note'], f"重探成功要说明首轮是冷启动: {rep['note']}"


def test_mcp_second_timeout_stops_and_tells_the_warmup(monkeypatch):
    """重探只一次；两次都超时就照实判坏，并给预热动作，不许无限重试烧时间。"""
    _as_mcp(monkeypatch)
    eng = _SeqEngine(['TIMEOUT', 'TIMEOUT'])

    rep = probe_engine(eng)

    assert eng.calls == 2, '重探超过一次，整轮自检会被拖死'
    assert rep['status'] == STATUS_FAILED
    assert 'setup-mcp.sh' in rep['note'], f"该给出预热命令: {rep['note']}"


def test_non_mcp_timeout_is_not_double_billed(monkeypatch):
    """正向对照：直连引擎别跟着重探——它的超时是网络问题，翻倍只会拖慢整场自检。"""
    import probe as _probe
    monkeypatch.setattr(_probe, 'engine_kind', lambda e: 'direct')
    eng = _SeqEngine(['TIMEOUT'])

    rep = probe_engine(eng)

    assert eng.calls == 1
    assert rep['status'] == STATUS_FAILED


def test_probe_names_the_capabilities_it_did_not_exercise():
    """声明了全文/引用图谱能力、这次却只打了检索一发 → 回执要写清"未测"。

    实测缺陷清单 A3：`arxiv-fulltext` 的 search() 只回元数据（标题/摘要），
    全文要另一发 download_pdf/fetch_latex。探针 ✅ 会被读成"正文也拿到了"。
    """
    eng = _FakeEngine(name='arxiv-fulltext', results=[_Item(content='摘要')],
                      capabilities=('search', 'academic', 'fulltext', 'latex'))
    rep = probe_engine(eng)

    assert rep['status'] == STATUS_OK
    assert '未测' in rep['note'] and 'fulltext' in rep['note'], rep['note']


def test_search_only_engine_gets_no_unprobed_capability_note():
    """正向对照：没有额外能力的引擎别硬加"未测"一行。"""
    eng = _FakeEngine(results=[_Item(content='摘要')])
    rep = probe_engine(eng)

    assert '未测' not in rep['note'], rep['note']


def test_skill_md_documents_the_cold_start_reprobe_and_unprobed_caps():
    """两条新判据要写在 SKILL.md 的判定表里，否则 Lead 仍按"探一次定生死"行动。"""
    md = SKILL_MD.read_text(encoding='utf-8')

    assert '自动重探一次' in md, 'MCP 超时会自动重探，文档没写就会有人以为探一次定生死'
    row = next((l for l in md.splitlines() if l.startswith('| ✅ N 条')), '')
    assert '未测' in row, f'✅ 那一行没写"未测哪些能力"：{row!r}'


SKILL_MD = Path(__file__).resolve().parents[2] / 'SKILL.md'


def test_skill_md_documents_the_body_completeness_criterion():
    """回执加了新判据，SKILL.md 的判定表必须同步——否则 Lead 仍按"✅＝能取正文"派活。"""
    md = SKILL_MD.read_text(encoding='utf-8')
    row = next((l for l in md.splitlines() if l.startswith('| ✅ N 条')), '')
    assert '正文' in row and '逐字' in row, f'✅ 那一行没写正文完整度：{row!r}'


def test_skill_md_bans_helper_scripts_outside_the_session_dir():
    """派单模板要写死"临时脚本只落会话目录"，护栏才有得可查。

    实测缺陷清单 A11：一个子 Agent 把 helper 写在系统 /tmp，guard 的作用域是会话目录，
    于是那次执行没有任何账跟踪它。
    """
    md = SKILL_MD.read_text(encoding='utf-8')
    assert '/tmp' in md, 'SKILL.md 没点名系统 /tmp 这个逃逸出口'
    assert 'scratch/' in md, '要给出该落在哪儿（会话目录 scratch/），不能只说"不许写 /tmp"'


def test_skill_md_probe_budget_matches_the_code():
    """文档里当作报错示例的那个预算数，要和 MCP_PROBE_BUDGET 一致。

    只锁"示例引号里的数"：SKILL.md 另有一句在讲"预算原先是 25s，所以判成超时"，
    那是历史，不是漂移。
    """
    from probe import MCP_PROBE_BUDGET

    md = SKILL_MD.read_text(encoding='utf-8')
    assert f'{MCP_PROBE_BUDGET}s 预算内没等到响应' in md, \
        f'SKILL.md 引用的超时示例还停在旧预算上（当前 {MCP_PROBE_BUDGET}s）'


def test_classify_probe_distinguishes_empty_from_failed():
    assert classify_probe([_Item()]) == STATUS_OK
    assert classify_probe([]) == STATUS_EMPTY      # 0 结果 ≠ 引擎可用
    assert classify_probe(None) == STATUS_FAILED   # 契约里的"不可用"


def test_probe_uses_engine_probe_query_and_reports_sample():
    eng = _FakeEngine(results=[_Item(), _Item()])
    rep = probe_engine(eng)
    assert eng.called_with == 'python'
    assert rep['status'] == STATUS_OK and rep['count'] == 2
    assert 'Vector DB' in rep['note']


def test_probe_reports_empty_as_not_usable():
    rep = probe_engine(_FakeEngine(results=[]))
    assert rep['status'] == STATUS_EMPTY
    assert '0 结果' in rep['note']


def test_probe_surfaces_missing_config(monkeypatch):
    monkeypatch.delenv('GITEE_TOKEN', raising=False)
    eng = _FakeEngine(available=False, config_keys=['GITEE_TOKEN'])
    rep = probe_engine(eng)
    assert rep['status'] == STATUS_FAILED
    assert 'GITEE_TOKEN' in rep['note']


def test_probe_exception_is_failure():
    rep = probe_engine(_FakeEngine(raises=RuntimeError('boom')))
    assert rep['status'] == STATUS_FAILED and 'boom' in rep['note']


def test_non_search_engine_is_skipped():
    eng = _FakeEngine(capabilities=['lookup', 'model'])
    assert probe_engine(eng)['status'] == STATUS_SKIPPED


def test_registered_engines_use_their_own_probe_query():
    """学术/医学引擎用通用词会假阴性，探针查询必须按引擎定制。"""
    assert resolve_probe_query(_FakeEngine(name='pubmed')) == PROBE_QUERIES['pubmed']
    assert resolve_probe_query(_FakeEngine(name='openalex')) == PROBE_QUERIES['openalex']


def test_explicit_metadata_query_wins_and_unknown_engine_falls_back():
    eng = _FakeEngine(name='pubmed', probe_query='custom')
    assert resolve_probe_query(eng) == 'custom'
    assert resolve_probe_query(_FakeEngine(name='not-registered')) == 'python'


def test_probeable_engines_limited_to_registered_engines():
    """登记过的都探（v6.9 起含 MCP）；未登记的 skill/内置封装类交给 Lead 自查。"""
    engines = [_FakeEngine(name='openalex'), _FakeEngine(name='tavily'),
               _FakeEngine(name='websearch')]
    assert [e.get_name() for e in probeable_engines(engines)] == ['openalex', 'tavily']


def test_summarize_counts_by_status():
    reps = [{'status': STATUS_OK}, {'status': STATUS_EMPTY}, {'status': STATUS_OK}]
    assert summarize(reps) == {STATUS_OK: 2, STATUS_EMPTY: 1}
