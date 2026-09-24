"""v6.17.1 回归：用户点名的引擎，不许被一次瞬时的实时可用性探测静默否决。

实测（2026-09-24，接 v6.17.0 的真跑验证）：

  research.py "AI 编码 Agent 的证据溯源做法…" --sources openalex --limit 6
    → 第 1 次 rc=0，正常出 5 条
    → 第 2 次（两分钟后，换了 --source-query）rc=1，"❌ 未找到结果"

两次之间 openalex 端点没变，变的是 `registry.get_fallback_chain()`：它对每个引擎现调一次
`is_available()`（真发网络请求），那一刻探测失败，openalex 就整个从链里消失。
连查三次实测 `'openalex' in chain == False`，链长稳定 19。

用户显式 `--sources openalex` 要的就是这个源。它被剔除后既不进 `unavailable` 也不进
`empty_engines`，界面上只剩一句"未找到结果"——把"你的源今天探测失败"说成了"这个主题没资料"。
而 `search()` 本身回 None 时，管线已经有"没取到数据"的如实出口，这层否决纯属重复且有害。

判据按 v6.16.2 定下的口径：链的候选集用**配置就绪**（确定性、可复现），
实时行不行交给真正那次 `search()` 调用报出来。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from engines.base import EngineMetadata, SearchResult  # noqa: E402
import research  # noqa: E402


class _FlakyEngine:
    """is_available() 探测失败、但 search() 完全能出数据——真实端点的常见状态。"""

    def __init__(self, name, available=True):
        self.metadata = EngineMetadata(
            name=name, layer=1, description=f'{name} desc',
            requires_config=False, config_keys=[],
            capabilities=['search', 'academic'], priority=1)
        self.available = available
        self.calls = []

    def get_name(self):
        return self.metadata.name

    def get_layer(self):
        return self.metadata.layer

    def has_capability(self, cap):
        return cap in self.metadata.capabilities

    def is_available(self):
        return self.available

    def is_configured(self):
        return True

    def search(self, query, max_results=10, **kwargs):
        self.calls.append(query)
        return [SearchResult(title='Retrieval-Augmented Generation for LLMs',
                             url=f'https://openalex.org/W123{self.metadata.name}',
                             content='evidence provenance claim source',
                             source=self.metadata.name)]


def _registry(engines):
    from engines.base import EngineRegistry
    reg = EngineRegistry()
    for e in engines:
        reg.register(e)
    return reg


def _args(**over):
    base = dict(query='AI 编码 Agent 的证据溯源做法', sources='flaky',
                source_query=None, all=False, limit=6, depth='standard',
                effort='quick', breadth=1, dimensions=None, perspectives=None,
                reflect_rounds=1, language='zh', region='cn', ledger=None,
                auto_claim=False, no_cache=True, no_plan=True, min_score=0,
                min_relevance=0, llm_score=False, format='markdown', output=None)
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture
def cwd_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_named_source_is_called_even_when_probe_says_unavailable(cwd_tmp):
    """点名了它就得真调一次 search()——不能凭一次探测就把它从链里抹掉。"""
    eng = _FlakyEngine('flaky', available=False)
    research.cmd_search(_args(), _registry([eng]))
    assert eng.calls, ('is_available() 探测失败导致引擎根本没被调用：'
                       '用户点名的源被静默剔除，界面只剩一句"未找到结果"')


def test_its_results_reach_the_report(cwd_tmp, capsys):
    """真出了数据就要如实报出来，条数不能是 0。"""
    eng = _FlakyEngine('flaky', available=False)
    research.cmd_search(_args(), _registry([eng]))
    err = capsys.readouterr().err
    assert '找到 1 条结果' in err, f'引擎出了 1 条却没被统计：{err[-400:]}'


def test_engine_that_really_returns_none_is_still_reported_as_unavailable(cwd_tmp, capsys):
    """反向保护：拆掉否决层之后，"真的没取到数据"仍要照实分开报，不许混成 0 结果。"""
    class _Dead(_FlakyEngine):
        def search(self, query, max_results=10, **kwargs):
            self.calls.append(query)
            return None

    dead = _Dead('dead')
    with pytest.raises(SystemExit):
        research.cmd_search(_args(sources='dead'), _registry([dead]))
    err = capsys.readouterr().err
    assert '未取到数据' in err and 'dead' in err, \
        f'None（没取到数据）没被如实归类：{err[-400:]}'
