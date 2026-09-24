"""v6.17.2 回归：`--route` 的 ✅/❌ 要说"配没配好"，不能拿一次实时探测当判决。

同一条判据在 v6.16.2 已经给 `--list` 定过：✅ ＝配置就绪（只查 env，可复现），
"此刻出不出数据"是 `--probe` 的实测范围。但 `cmd_route` 的「推荐引擎链」还在用
`registry.get_available()`（对每个引擎现发一次网络探测）打标记——

实测：openalex 配置就绪、search() 正常出数据，而同一时刻 is_available() 探测超时，
`--route` 就在它前面印 ❌。读的人（Lead）会理解成"这个源坏了/没配"，
于是把它从 --sources 里划掉；而 v6.17.1 刚修掉的那条静默剔除，正是同一种误读。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research  # noqa: E402
from engines.base import EngineMetadata  # noqa: E402


class _Eng:
    def __init__(self, name, available=True, configured=True):
        self.metadata = EngineMetadata(
            name=name, layer=1, description=f'{name} 描述',
            requires_config=not configured, config_keys=[] if configured else ['X_KEY'],
            capabilities=['search'], priority=1)
        self._available = available

    def get_name(self):
        return self.metadata.name

    def get_layer(self):
        return self.metadata.layer

    def has_capability(self, cap):
        return cap in self.metadata.capabilities

    def is_available(self):
        return self._available

    def is_configured(self):
        return not (self.metadata.requires_config
                    and not all(__import__('os').environ.get(k)
                                for k in self.metadata.config_keys))


def _registry(engines):
    from engines.base import EngineRegistry
    reg = EngineRegistry()
    for e in engines:
        reg.register(e)
    return reg


def _chain_names(query):
    from router import QueryRouter
    return QueryRouter().route(query, {}).engine_chain


QUERY = '大模型引用的开源框架架构'


def _route_out(capsys, engines):
    args = argparse.Namespace(query=QUERY)
    research.cmd_route(args, _registry(engines))
    return capsys.readouterr().out


def test_configured_engine_is_not_marked_broken_by_a_failed_probe(capsys):
    """配置就绪 + 探测失败 的引擎，不得被印成 ❌。"""
    names = _chain_names(QUERY)
    assert names, '路由没推荐任何引擎，断言失去意义'
    target = names[0]
    engines = [_Eng(n, available=(n != target)) for n in names]
    out = _route_out(capsys, engines)
    line = next(l for l in out.splitlines() if target in l)
    assert '❌' not in line, (
        f'{target} 配置就绪、只是此刻探测失败，却被标成 ❌：{line!r}')
    assert '✅' in line, f'配置就绪的引擎应打 ✅：{line!r}'


def test_marker_legend_says_live_check_belongs_to_probe(capsys):
    """图例要说清 ✅ 的含义，否则读者会拿它当"今天能出数据"的结论。"""
    names = _chain_names(QUERY)
    engines = [_Eng(n, available=False) for n in names]
    out = _route_out(capsys, engines)
    assert '--probe' in out, (
        f'推荐链打了 ✅/❌ 却没说明实测归 --probe：{out[-500:]}')


def test_genuinely_unconfigured_engine_still_flagged(capsys):
    """反向保护：真没配 key 的源仍要标出来，别把标记改成永远 ✅。"""
    names = _chain_names(QUERY)
    target = names[0]
    engines = [_Eng(n, configured=(n != target)) for n in names]
    out = _route_out(capsys, engines)
    line = next(l for l in out.splitlines() if target in l)
    assert '❌' in line, f'{target} 缺配置却不再被标出，等于取消了这个提示：{line!r}'
