"""v6.16.2 回归：把「配置就绪」与「实时可达」拆成两件事报。

缺陷原貌：`--list` 结尾的「N 个可用」在同一台机器上连跑两次给出过 19 和 20 两个数。
根因不是数据变了，而是免配置引擎（openalex / semantic-scholar / pubmed /
arxiv-fulltext / s2-citation-graph / github-deep-search）的 is_available() 没有
配置项可查，于是发一次真实 HTTP 请求探连通性，超时即判「不可用」。

边界：is_available() 一个字都不改——unpaywall / s2-citation-graph / crawl4ai 不在
PROBE_QUERIES 里，它们的实时可达信号目前只剩这条路径。改的是**报告**：
--list 换成确定性的 is_configured()，实时可达仍归 --probe 独家负责。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from engines.base import SearchEngine  # noqa: E402
from research import build_registry, cmd_list  # noqa: E402

# 各引擎模块的网络出口。--list 走到的网络面就这些。
NET_EXPORTS = {
    'engines.academic_engines': ('_http_get',),
    'engines.academic_fulltext': ('_http_get',),
    'engines.github_deep_search': ('_http_get',),
    'engines.crawl4ai_engine': ('_http_get',),
    'engines.fallback': ('_http_get',),
    'engines.platform_engines': ('_host_reachable',),
}

# 一个开关同时喂两种网络状态，保证两次 --list 之间只有"通不通"这一个变量
NET_UP = True


def _fake_net(*args, **kwargs):
    return '{"works": [{"id": "stub"}], "total": 1}' if NET_UP else None


@pytest.fixture
def net_dispatch(monkeypatch):
    """把全部网络出口换成受开关控制的桩（绝不打真网络）。"""
    import importlib
    for mod_name, names in NET_EXPORTS.items():
        mod = importlib.import_module(mod_name)
        for n in names:
            if hasattr(mod, n):
                monkeypatch.setattr(mod, n, _fake_net)
    global NET_UP
    NET_UP = True
    yield lambda up: _set_up(up)
    NET_UP = True


def _set_up(up):
    global NET_UP
    NET_UP = up


@pytest.fixture
def net_forbidden(monkeypatch):
    """任何越界网络调用立刻抛错——用来证明某个函数是纯静态的。"""
    import importlib

    def _boom(*a, **kw):
        raise AssertionError('不该发网络请求')

    for mod_name, names in NET_EXPORTS.items():
        mod = importlib.import_module(mod_name)
        for n in names:
            if hasattr(mod, n):
                monkeypatch.setattr(mod, n, _boom)
    return monkeypatch


def _summary_line(text):
    return next(l for l in text.splitlines() if l.startswith('总计:'))


def _line_for(text, name):
    return next(l for l in text.splitlines() if name in l)


# ------------------------------------------------------------
# is_configured()：确定性判据，零网络
# ------------------------------------------------------------

class TestIsConfigured:

    def test_exists_on_base_class(self):
        assert hasattr(SearchEngine, 'is_configured'), \
            '基类没有配置就绪判据，--list 只能拿实时可达凑数'

    def test_keyless_engine_is_ready_without_network(self, net_forbidden):
        from engines.academic_engines import OpenAlexEngine
        assert OpenAlexEngine().is_configured() is True

    def test_missing_required_key_is_not_ready(self, net_forbidden, monkeypatch):
        from engines.platform_engines import GiteeEngine
        monkeypatch.delenv('GITEE_TOKEN', raising=False)
        assert GiteeEngine().is_configured() is False

    def test_required_key_present_makes_it_ready(self, net_forbidden, monkeypatch):
        from engines.platform_engines import GiteeEngine
        monkeypatch.setenv('GITEE_TOKEN', 'stub-token')
        assert GiteeEngine().is_configured() is True

    def test_optional_key_absence_does_not_downgrade(self, net_forbidden):
        # s2-citation-graph：requires_config=False，S2_API_KEY 只是可选加速
        from engines.academic_fulltext import CitationGraphEngine
        assert CitationGraphEngine().is_configured() is True

    def test_whole_registry_is_configurable_with_zero_network(self, net_forbidden):
        """横扫同类：32 个引擎逐个问"配置齐不齐"，一个网络包都不许发出去。"""
        for engine in build_registry().get_all():
            engine.is_configured()


# ------------------------------------------------------------
# --list：结果与"此刻网络好不好"无关
# ------------------------------------------------------------

class TestListIsDeterministic:

    def test_summary_count_is_the_same_up_and_down(self, capsys, net_dispatch):
        registry = build_registry()
        net_dispatch(True)
        up = _summary_line(capture(capsys, registry))
        net_dispatch(False)
        down = _summary_line(capture(capsys, registry))
        assert up == down, '同一套引擎，网络通与不通给出两个数：%r vs %r' % (up, down)

    def test_per_engine_marks_are_the_same_up_and_down(self, capsys, net_dispatch):
        registry = build_registry()
        net_dispatch(True)
        up = capture(capsys, registry)
        net_dispatch(False)
        down = capture(capsys, registry)
        assert up == down, '--list 的逐源标记随网络浮动，等于没有基线'

    def test_dead_network_does_not_make_a_keyless_source_look_broken(
            self, capsys, net_dispatch):
        """可达性失败不得折算成"这个源不能用"——那是 --probe 的活。"""
        registry = build_registry()
        net_dispatch(False)
        # 先立住前提：实时判据此刻确实是 False（网络不通）
        assert registry.get('openalex').is_available() is False
        out = capture(capsys, registry)
        assert '✅' in _line_for(out, 'openalex'), \
            '免配置源因为网络超时被标成不可用：%r' % _line_for(out, 'openalex')

    def test_says_what_the_number_means_and_where_to_measure_liveness(
            self, capsys, net_dispatch):
        out = capture(capsys, build_registry())
        assert '配置就绪' in out, '光写"可用"会被读成实测结论'
        assert '--probe' in out, '要同时指出实时可达去哪儿测'


def capture(capsys, registry):
    cmd_list(registry)
    return capsys.readouterr().out
