"""超时提示里的秒数，必须是真正生效的那一个。

实测（v6.23.0，本机）：`--probe --sources open-websearch` 11 秒就回
"超时：整场会话 25s 预算内没等到 initialize 的响应"。数对不上——
握手走的是 `handshake_budget = min(INIT_TIMEOUT, budget)`（默认 10s），
根本没用满 25s。报错把 25s 说出来，用户就会去调 `--timeout`／MCP_PROBE_BUDGET，
而真正该动的是 INIT_TIMEOUT。指错旋钮的报错比没报错更费时间。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.mcp_client import McpClient  # noqa: E402

# 活着但对 initialize 永远不回话的 server：任何预算都必然超时
STUB = '''
import sys, time
mode = sys.argv[1] if len(sys.argv) > 1 else 'silent'
if mode == 'slowhand':
    time.sleep(5)          # 握手要 5 秒：慢，但在放宽后的预算内能过
import json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue
    rid = req.get('id')
    meth = req.get('method')
    if meth != 'initialize':
        continue                       # 工具调用一律不回（slowtool 靠这个卡住）
    if mode == 'silent':
        continue                       # 连 initialize 也不回（装死）
    out = {'jsonrpc': '2.0', 'id': rid,
           'result': {'protocolVersion': '2024-11-05', 'capabilities': {},
                      'serverInfo': {'name': 'stub', 'version': '1'}}}
    sys.stdout.write(json.dumps(out) + chr(10))
    sys.stdout.flush()
'''


@pytest.fixture()
def stub_path(tmp_path):
    p = tmp_path / 'mcp_stub.py'
    p.write_text(STUB, encoding='utf-8')
    return p


def make_client(stub_path, mode):
    return McpClient('stub', config={
        'command': sys.executable, 'args': [str(stub_path), mode]})


def test_handshake_timeout_names_the_handshake_budget_not_the_session_one(stub_path):
    client = make_client(stub_path, 'silent')
    client.INIT_TIMEOUT = 1
    started = time.time()
    assert client.open_session(budget=20) is None
    took = time.time() - started
    assert took < 4, f'握手预算 1s 却等了 {took:.1f}s，说明限流没生效'
    err = client.last_error
    assert '1s' in err, f'提示该说真正卡住的 1s 握手预算：{err}'
    assert '20s' not in err, f'把整场预算 20s 写进提示会误导用户去调错的旋钮：{err}'
    assert '握手' in err, f'要说清卡在哪一段（握手／工具调用），才知道该动哪个旋钮：{err}'


def test_tool_call_timeout_still_names_the_session_budget(stub_path):
    """反过来也一样：握手过了、卡在工具调用时，报的就得是整场预算。"""
    client = make_client(stub_path, 'slowtool')
    client.INIT_TIMEOUT = 5
    err = ''
    if client.open_session(budget=2) is None:
        err = client.last_error
    else:
        client.call_tool('x', {}, timeout=2)
        err = client.last_error
    assert '2s' in err and '握手' not in err, f'工具调用超时应报整场预算：{err}'


def test_slow_server_passes_once_the_handshake_budget_is_its_own(stub_path):
    """握手慢（5s）不等于坏：预算给够就该连上——这条锁住"别把慢判成死"。"""
    client = make_client(stub_path, 'slowhand')
    client.INIT_TIMEOUT = 12
    session = client.open_session(budget=30)
    assert session is not None, f'5s 能握手成功却被判失败：{client.last_error}'
    session.close()
