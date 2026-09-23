"""X-D1 + X-D2：脚本层取不到数据的引擎（skill 封装 / 宿主内置），闸门两处报错方向相反。

实测（本机真命令行，v6.15.7）：

    research.py "测试" --probe --sources websearch,webfetch,oss-finder
      ❌ oss-finder   0 条  引擎返回 None（依赖/服务未就绪）
      ❌ websearch     0 条  引擎返回 None（依赖/服务未就绪）
      ❌ 没有任何引擎通过功能自检 —— 不要开始调研      rc=1
    research.py "开源向量数据库选型" --route
      1. ✅ oss-finder …（推荐链第一位），给的命令是 --sources oss-finder,github-deep-search,…

同一批结果让子 Agent 另起进程跑，逐项一致——所以缺陷不是"lead / 子 Agent 两档"，
是"脚本进程 vs Agent 进程"这一档没被建模：这些引擎的数据只有 Agent 亲自调工具才拿得到
（skill_engines 基类与 engines/builtin 的 search() 都写死返回 None）。

于是同一个事实被报错了两次：闸门里判成"坏了"（假红，还把整轮拦停），路由里判成"可用"（假绿）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import probe
from engines.builtin import WebSearchEngine
from engines import fallback as _fb

RESEARCH = str(Path(__file__).resolve().parent.parent / 'research.py')

# 新档位的取值先钉死字面量：实现若换了名字，这条会红着提醒，而不是静默绕过
AGENT_ONLY = 'agent_only'


@dataclass
class _Meta:
    config_keys: List[str] = field(default_factory=list)
    probe_query: str = ''
    layer: int = 2
    capabilities: List[str] = field(default_factory=lambda: ['search'])


class _ScriptEngine:
    """住在测试模块里的引擎＝脚本层真能出数据的那一类（探针该照常探它）。"""

    def __init__(self, name='fake', results=(), available=True, trip_http_error=False):
        self._name = name
        self._results = None if results is None else list(results)
        self._available = available
        self._trip = trip_http_error
        self.metadata = _Meta()
        self.called = False

    def get_name(self):
        return self._name

    def has_capability(self, cap):
        return cap == 'search'

    def is_available(self):
        return self._available

    def search(self, query, max_results=10, **kwargs):
        self.called = True
        if self._trip:
            _fb._note_http_error('HTTP 429 rate limited')
        return self._results


class _Item:
    def __init__(self, title='Vector DB', url='https://a.dev'):
        self.title, self.url = title, url


def _run(*args, env=None):
    return subprocess.run([sys.executable, RESEARCH, *args],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=180,
                          cwd=str(Path(RESEARCH).parent), env=env)


# --- 假红：闸门把"脚本层探不到"报成"引擎坏了" -------------------------------

def test_agent_invoked_engine_is_not_judged_broken():
    eng = WebSearchEngine()

    def _boom(*a, **k):
        raise AssertionError('脚本层探不到的引擎不该被调用 search()')

    eng.search = _boom
    rep = probe.probe_engine(eng)
    assert rep['status'] == AGENT_ONLY, f'被判成 {rep["status"]}：{rep["note"]}'
    assert 'Agent' in rep['note'], f'没说清该由谁取数：{rep["note"]}'


def test_script_layer_engine_still_probes_as_usual():
    """正向对照：新档位不能把真能出数据的引擎也一并跳过。"""
    rep = probe.probe_engine(_ScriptEngine(results=[_Item()]))
    assert rep['status'] == probe.STATUS_OK and rep['count'] == 1


def test_probe_cli_does_not_block_on_engines_it_cannot_see():
    r = _run('测试', '--probe', '--sources', 'websearch,webfetch')
    assert r.returncode == 0, f'rc={r.returncode}\n{r.stdout}\n{r.stderr}'
    assert '不要开始调研' not in r.stdout + r.stderr
    assert 'Agent' in r.stdout, f'没说明这几个引擎为什么探不了：\n{r.stdout}'


def test_probe_cli_still_blocks_when_a_probeable_engine_failed():
    """另一向对照：能探的引擎真失败时照样拦停，别借这次改动放水。

    gitee 缺 GITEE_TOKEN 时 is_available() 直接 False（不碰网络），
    和 websearch（探不到）同框——有一档可见且失败，就必须 rc=1。
    """
    env = {**os.environ, 'GITEE_TOKEN': ''}
    r = _run('测试', '--probe', '--sources', 'gitee,websearch', env=env)
    assert r.returncode == 1, f'该拦的没拦住：rc={r.returncode}\n{r.stdout}'
    assert '不要开始调研' in r.stdout + r.stderr
    assert 'GITEE_TOKEN' in r.stdout, f'没点名缺的配置：\n{r.stdout}'


# --- 假绿：路由把恒真的 is_available() 当成"这条命令能出数据" ----------------

def test_route_does_not_mark_agent_only_engine_available():
    r = _run('开源向量数据库选型', '--route')
    lines = [ln for ln in r.stdout.splitlines() if 'oss-finder' in ln]
    assert lines, f'路由输出里没有 oss-finder：\n{r.stdout}'
    assert not any('✅' in ln for ln in lines), f'仍报成可用：{lines}'
    assert any('Agent' in ln for ln in lines), f'没说明它要怎么才拿得到数据：{lines}'


def test_route_suggested_command_drops_agent_only_engine():
    r = _run('开源向量数据库选型', '--route')
    suggested = [ln.strip() for ln in r.stdout.splitlines()
                 if ln.strip().startswith('python research.py') and '--sources' in ln]
    assert suggested, '没有给出建议命令'
    assert not any('oss-finder' in ln for ln in suggested), \
        f'建议命令还让脚本层去调它，跑了就是 0 条：{suggested}'


def test_source_gate_does_not_turn_agent_only_into_guidance_noise():
    reps = [probe.probe_engine(WebSearchEngine()),
            probe.probe_engine(_ScriptEngine(results=[_Item()]))]
    gate = probe.source_gate(reps)
    assert 'websearch' not in ' '.join(gate['guidance']), \
        f'探不到的引擎被列进"没配好"：{gate["guidance"]}'


def test_theme_preflight_does_not_call_it_a_broken_channel():
    """同类清扫：主题预演拿实际查询词逐条打，探不到的引擎会被判"通道问题"。

    那句"通道问题，不是没资料"用在这里同样是错的——脚本层就没通道可言。
    """
    rows = probe.theme_probe([WebSearchEngine()], ['向量数据库 开源 选型'])
    assert rows[0]['verdict'] == AGENT_ONLY, f"判成 {rows[0]['verdict']}：{rows[0]}"


# --- 顺带：失败原因会串到下一个引擎身上 ------------------------------------

def test_failure_reason_does_not_leak_from_previous_engine(monkeypatch):
    monkeypatch.setattr(_fb, 'LAST_HTTP_ERROR', 'HTTP 429 rate limited', raising=False)
    rep = probe.probe_engine(_ScriptEngine(results=None))
    assert rep['status'] == probe.STATUS_FAILED
    assert '429' not in rep['note'], f'上一条引擎的限流被安到这条头上：{rep["note"]}'


def test_failure_reason_still_reports_this_engines_own_http_error(monkeypatch):
    """正向对照：清台不能清成"永远查不到原因"。"""
    monkeypatch.setattr(_fb, 'LAST_HTTP_ERROR', '', raising=False)
    rep = probe.probe_engine(_ScriptEngine(results=None, trip_http_error=True))
    assert '429' in rep['note'], f'引擎自己踩的 429 没报出来：{rep["note"]}'
