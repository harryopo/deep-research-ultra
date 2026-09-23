"""v6.16.4 回归：用户点名 --sources 之后，不许被第一个填满额度的引擎挤掉。

真实故障（2026-09-23 实测）：
  research.py "AI 编码 Agent 的证据溯源做法…" --effort quick \
      --sources openalex,arxiv-fulltext,pubmed,github-deep-search,github-code-search,sogou-weixin
  → 🔍 只搜了 arxiv-fulltext 一个引擎，"数据源数：1"，交叉验证 0 已验证 / 12 单源，验证率 0%。

原因不在引擎可用性（六个引擎 is_available() 当时全 True），而在降级链搜索的
`if len(all_results) >= args.limit: break`——第一个引擎就填满 limit，剩下五个
根本没被叫到。用户显式点名多个源，要的就是多源交叉验证；命中即停的默认策略
在这种情况下恰好把工具的核心价值抹平了。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from engines.base import EngineMetadata, SearchResult  # noqa: E402
import research  # noqa: E402


class _SourceEngine:
    """每个引擎都填满 limit 条——正好触发"命中即停"的早退。"""

    def __init__(self, name, hits):
        self.metadata = EngineMetadata(
            name=name, layer=1, description=f'{name} desc',
            requires_config=False, config_keys=[],
            capabilities=['search', 'academic'], priority=hits)
        self.hits = hits
        self.calls = []

    def get_name(self):
        return self.metadata.name

    def get_layer(self):
        return self.metadata.layer

    def has_capability(self, cap):
        return cap in self.metadata.capabilities

    def is_available(self):
        return True

    def is_configured(self):
        return True

    def search(self, query, max_results=10, **kwargs):
        self.calls.append(query)
        return [SearchResult(title=f'{self.metadata.name} 证据 {i}',
                             url=f'https://src.example/{self.metadata.name}/{i}',
                             content=f'{query} 的相关内容 ' * 6,
                             source=self.metadata.name, score=0.8)
                for i in range(self.hits)]


def _registry(engines):
    from engines.base import EngineRegistry
    reg = EngineRegistry()
    for e in engines:
        reg.register(e)
    return reg


def _args(**over):
    base = dict(query='AI 编码 Agent 的证据溯源做法', sources='alpha,beta,gamma',
                all=False, limit=10, depth='standard', effort='quick', breadth=1,
                dimensions=None, perspectives=None, reflect_rounds=1,
                language='zh', region='cn', ledger=None, auto_claim=False,
                no_cache=True, no_plan=True, min_score=0, min_relevance=0,
                llm_score=False, format='markdown', output=None)
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture
def three_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engines = [_SourceEngine('alpha', 10), _SourceEngine('beta', 10),
               _SourceEngine('gamma', 10)]
    return engines


def test_every_named_source_is_called(three_sources, capsys):
    """点名三个源，就得搜三个源——不能因为第一个就凑够了数。"""
    engines = three_sources
    research.cmd_search(_args(), _registry(engines))
    called = [e.get_name() for e in engines if e.calls]
    assert called == ['alpha', 'beta', 'gamma'], \
        f'点名 3 个源，实际只搜了 {called}'


def test_report_counts_all_named_sources(three_sources, capsys):
    """正向断言：cmd_search 自己报的"来自 N 个引擎"必须是点名的 3 个。"""
    import re
    research.cmd_search(_args(), _registry(three_sources))
    err = capsys.readouterr().err
    m = re.search(r'找到 \d+ 条结果（来自 (\d+) 个引擎）', err)
    assert m, f'没找到"来自 N 个引擎"这行统计，断言失去意义：{err[:200]}'
    assert m.group(1) == '3', f'点名 3 个源，统计却只有 {m.group(1)} 个引擎出了结果'


def test_unnamed_search_still_stops_on_first_hit(capsys, tmp_path, monkeypatch):
    """没点名时保持原样：降级链命中即停，这是省时间的默认策略，不许顺手改掉。"""
    monkeypatch.chdir(tmp_path)
    engines = [_SourceEngine('alpha', 10), _SourceEngine('beta', 10),
               _SourceEngine('gamma', 10)]
    research.cmd_search(_args(sources=None), _registry(engines))
    called = [e.get_name() for e in engines if e.calls]
    assert called and called[0] == 'alpha'
    assert len(called) == 1, f'没点名时也该命中即停，实际搜了 {called}'
