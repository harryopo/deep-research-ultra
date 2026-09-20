"""mcp_client 真连接测试：会话不分裂、超时真可中断、跑完不留进程。

写这些测试的实测起因（v6.8 之后排查出来的两处硬伤）：
- 旧 `_send_rpc` 每发一个 JSON-RPC 就新起一个进程，`initialize` 握手在第 1 个进程，
  `tools/call` 打到第 3 个从未握手的进程 → 按规范实现的 server 直接回 -32002，
  **环境全配好也探不出结果**；
- `timeout` 只在 `readline()` 之前判一次，读本身不可中断 → 给 2 秒实测 14.9 秒不返回，
  还叠加 `stderr=PIPE` 从不读取导致的写阻塞、`kill()` 只杀 npx 而泄漏 node 孙进程。

所以这里的每条测试都对应一个必须存在的能力，而不是把现有实现抄一遍。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.mcp_client import McpClient  # noqa: E402

# 一个按 MCP 规范工作的 stdio server：未 initialize 就拒绝工具调用；
# 通知不回响应；可选模式用于验证超时、stderr 洪泛、进程清理。
STUB = r'''
import json, os, sys, time

mode = sys.argv[1] if len(sys.argv) > 1 else 'good'
pid_file = sys.argv[2] if len(sys.argv) > 2 else ''
if pid_file:
    with open(pid_file, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))

if mode == 'silent':          # 活着但永远不回话
    time.sleep(600)

sys.stdout.reconfigure(encoding='utf-8')
ready = False
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue
    method, rid = req.get('method'), req.get('id')
    if method == 'initialize':
        ready = True
        out = {'jsonrpc': '2.0', 'id': rid,
               'result': {'protocolVersion': '2024-11-05', 'capabilities': {},
                          'serverInfo': {'name': 'stub', 'version': '1'}}}
    elif method == 'tools/list':
        out = {'jsonrpc': '2.0', 'id': rid,
               'result': {'tools': [{'name': 'stub-search', 'description': 'd',
                                     'inputSchema': {}}]}}
    elif method == 'tools/call':
        if not ready:
            out = {'jsonrpc': '2.0', 'id': rid,
                   'error': {'code': -32002,
                             'message': 'Server not initialized'}}
        else:
            if mode == 'flood':      # 先刷爆 stderr 管道缓冲再回答
                sys.stderr.write('x' * 400000 + '\n')
                sys.stderr.flush()
            out = {'jsonrpc': '2.0', 'id': rid,
                   'result': {'content': [{'type': 'text', 'text': json.dumps(
                       {'results': [{'url': 'https://a.dev/1', 'title': 'S1'},
                                   {'url': 'https://a.dev/2', 'title': 'S2'}]})}],
                       'isError': False}}
    elif method and method.startswith('notifications/'):
        continue                     # 通知不得有响应
    else:
        continue
    if mode == 'noanswer' and method == 'tools/call':
        continue
    sys.stdout.write(json.dumps(out) + '\n')
    sys.stdout.flush()
'''


@pytest.fixture()
def stub_path(tmp_path):
    p = tmp_path / 'mcp_stub.py'
    p.write_text(STUB, encoding='utf-8')
    return p


def make_client(stub_path, mode='good'):
    """显式传 config，避免测试依赖任何真实 MCP 配置文件。"""
    return McpClient('stub', config={
        'command': sys.executable, 'args': [str(stub_path), mode]})


def titles(result_items):
    out = []
    for item in result_items or []:
        for part in item.get('content', []) or []:
            try:
                payload = json.loads(part.get('text') or '{}')
            except Exception:
                continue
            out.extend(r['title'] for r in payload.get('results', []))
    return out


# ---------------------------------------------------------------------------
# ① 一次会话＝一个进程：握手与工具调用不能分裂
# ---------------------------------------------------------------------------

def test_spec_stub_returns_results(stub_path):
    """规范 server 会拒绝未 initialize 的 tools/call；旧实现因此恒拿 0 结果。"""
    client = make_client(stub_path)
    result = client.call_tool('stub-search', {'query': 'x'})
    assert result, '握手后同一个会话里调用工具必须拿到结果'
    assert titles([result]) == ['S1', 'S2']


def test_initialize_and_tools_call_share_one_process(stub_path):
    pid_file = str(stub_path.parent / 'pid')
    client = McpClient('stub', config={
        'command': sys.executable, 'args': [str(stub_path), 'good', pid_file]})
    assert client.call_tool('stub-search', {'query': 'x'})
    with open(pid_file, encoding='utf-8') as f:
        pid = int(f.read().strip())
    assert pid > 0
    # 一次工具调用只应拉起一个 server 进程（旧实现按 RPC 条数起 3 个）
    spawned = getattr(client, 'spawn_count', None)
    assert spawned == 1, f'一次 call_tool 应只起 1 个进程，实际 {spawned}'


def test_list_tools_works_on_spec_stub(stub_path):
    names = [t.get('name') for t in make_client(stub_path).list_tools()]
    assert names == ['stub-search']


# ---------------------------------------------------------------------------
# ② 超时必须真能中断
# ---------------------------------------------------------------------------

def test_silent_server_fails_within_budget(stub_path):
    client = make_client(stub_path, mode='silent')
    started = time.time()
    assert client.call_tool('stub-search', {'query': 'x'}, timeout=2) is None
    elapsed = time.time() - started
    assert elapsed < 4.5, f'超时没兜住：等了 {elapsed:.1f}s（预算 2s）'


def test_server_that_never_answers_tools_call_fails_within_budget(stub_path):
    client = make_client(stub_path, mode='noanswer')
    started = time.time()
    assert client.call_tool('stub-search', {'query': 'x'}, timeout=2) is None
    assert time.time() - started < 4.5


def test_budget_covers_whole_session_not_just_one_read(stub_path):
    """预算是整场会话的墙钟上限：握手吃掉大头后，剩余请求不得再各等一个 timeout。"""
    client = McpClient('stub', config={
        'command': sys.executable, 'args': [str(stub_path), 'noanswer']})
    client.INIT_TIMEOUT = 2
    started = time.time()
    assert client.call_tool('stub-search', {'query': 'x'}, timeout=3) is None
    assert time.time() - started < 5.0, '超时被叠加成两次独立等待，预算失效'


def test_stderr_flood_does_not_deadlock(stub_path):
    """server 往 stderr 刷日志撑满管道缓冲时，绝不能把 stdout 一起拖死。"""
    client = make_client(stub_path, mode='flood')
    result = client.call_tool('stub-search', {'query': 'x'}, timeout=6)
    assert titles([result]) == ['S1', 'S2']


# ---------------------------------------------------------------------------
# ③ 不留孤儿进程
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    if sys.platform == 'win32':
        out = subprocess.run(['tasklist', '/NH', '/FI', f'PID eq {pid}'],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def test_no_orphan_after_timeout(stub_path, tmp_path):
    """超时后必须把整棵进程树收掉（npx → node 是两层，旧实现只杀父亲）。"""
    pid_file = str(tmp_path / 'pid')
    client = McpClient('stub', config={
        'command': sys.executable, 'args': [str(stub_path), 'silent', pid_file]})
    assert client.call_tool('stub-search', {'query': 'x'}, timeout=2) is None
    time.sleep(0.5)
    pid = int(Path(pid_file).read_text(encoding='utf-8').strip())
    assert not _pid_alive(pid), f'server 进程 {pid} 还活着——超时路径漏杀'


def test_client_surfaces_server_stderr_on_failure(stub_path, tmp_path):
    """失败原因要说得出"为什么"，所以 server 的 stderr 得留着给人看。"""
    pid_file = str(tmp_path / 'pid')
    client = McpClient('stub', config={
        'command': sys.executable, 'args': [str(stub_path), 'silent', pid_file]})
    client.call_tool('stub-search', {'query': 'x'}, timeout=2)
    assert hasattr(client, 'last_error')
    assert client.last_error


# ---------------------------------------------------------------------------
# ④ 闸门端到端：MCP 源配好了就必须被 --probe 看见
# ---------------------------------------------------------------------------

def test_gate_sees_a_configured_mcp_source(stub_path, monkeypatch):
    """真引擎 + 真 JSON-RPC 会话 + 真 probe_engine，缺一环都到不了 STATUS_OK。"""
    import probe
    from engines.mcp_engines import TavilyMcpEngine

    monkeypatch.setenv('TAVILY_API_KEY', 'test-key')
    eng = TavilyMcpEngine()
    eng._client = McpClient('tavily', config={
        'command': sys.executable, 'args': [str(stub_path), 'good'],
        'env': {'TAVILY_API_KEY': 'test-key'}})

    rep = probe.probe_engine(eng, max_results=2)
    assert rep['status'] == probe.STATUS_OK, f"探不到 MCP 源：{rep['note']}"
    assert rep['kind'] == 'mcp' and rep['count'] == 2
