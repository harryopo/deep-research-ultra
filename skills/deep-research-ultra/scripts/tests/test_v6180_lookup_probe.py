"""v6.18.0：给"查详情类"引擎补功能探针，补掉 --probe 的最后两块空白。

实测盲区（2026-09-24 量过，不是猜的）：32 个源里探针登记 21 个，剩下 11 个中
1 个（crawl4ai）本来就要先配 key，8 个是"只有 Agent 亲自调工具才取到数据"的封装源
（`agent_invoked()` 判 True，探针如实标 🤖）——**真正的盲区只有 2 个**：
`unpaywall`（DOI→OA 解析）与 `modelscope`（模型卡详情）。它们没有 `search` 能力，
`probe_engine` 一律回 SKIPPED，于是 --probe 报"跳过 2"，这两个源今天到底出不导出数据，
闸门一个字都不知道。

修法不是把跳过取消就完事：得真发一次"给已知 id 应当回数据"的请求。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probe import (LOOKUP_PROBES, STATUS_FAILED, STATUS_OK, STATUS_SKIPPED,  # noqa: E402
                   probe_engine)
from engines.base import EngineMetadata  # noqa: E402


class _Lookup:
    """没有 search 能力、只有一个详情查询入口的引擎。"""

    def __init__(self, name, method='search_by_doi', result=None):
        self.metadata = EngineMetadata(
            name=name, layer=1, description=f'{name} 查详情',
            requires_config=False, config_keys=[],
            capabilities=['academic', 'lookup'], priority=1)
        self._result = {} if result is None else result
        self.calls = []
        if result is not None:
            setattr(self, method, self._fake)

    def _fake(self, arg, **kw):
        self.calls.append(arg)
        return self._result

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


def test_lookup_engines_have_real_probe_arguments():
    """两个已知盲区都得登记"给什么 id 该回数据"，不能留在跳过里。"""
    assert set(LOOKUP_PROBES) >= {'unpaywall', 'modelscope'}, \
        f'查详情类探针登记表缺项：{sorted(LOOKUP_PROBES)}'
    for name, (method, arg) in LOOKUP_PROBES.items():
        assert method and arg, f'{name} 的探针参数没填全：{method!r}, {arg!r}'


def test_lookup_probe_actually_calls_the_engine():
    """登记过的查详情引擎：探针要真调一次并给出条数，不再是 SKIPPED。"""
    eng = _Lookup('unpaywall', method='search_by_doi', result={'isOpenAccess': True})
    rep = probe_engine(eng)
    assert rep['status'] != STATUS_SKIPPED, '仍被判跳过，盲区没补上'
    assert rep['status'] == STATUS_OK, f'查详情回数据了却没记成功：{rep}'
    assert eng.calls, '探针根本没调用引擎的查询入口'


def test_lookup_probe_reports_failure_honestly():
    """反向保护：查不到数据要说"没取到"，不许因为"不是 search 类"就蒙混成跳过。"""
    eng = _Lookup('unpaywall', method='search_by_doi', result=None)
    rep = probe_engine(eng)
    assert rep['status'] == STATUS_FAILED, \
        f'取不到数据应如实报 failed，实际 {rep["status"]}：{rep.get("note")}'


def test_unregistered_lookup_engine_is_still_skipped():
    """没登记的查详情源继续如实跳过——不许为了清零跳过数随便编个 id 去请求。"""
    eng = _Lookup('some-lookup-engine', method='search_by_doi', result={'a': 1})
    rep = probe_engine(eng)
    assert rep['status'] == STATUS_SKIPPED, (
        f'未登记的引擎被瞎猜着探了：{rep["status"]} / {rep.get("note")}')
