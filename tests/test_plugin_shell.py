"""计划 A 探针：本地 Python 能否作为 stdio MCP server 被真握手。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from engines.mcp_client import McpSession  # noqa: E402


def _session(budget: float = 25.0) -> McpSession:
    # env 用「继承进程环境」而不是 {}：本仓库对 McpSession 的唯一生产用法
    # （scripts/engines/mcp_client.py:384 get_env）就是 os.environ.copy() + 配置项。
    # 实测传 {} 时 Windows 子进程连 `import asyncio` 都过不去
    # （_overlapped → OSError [WinError 10106] WSAStartup 起不来），
    # 那是 fixture 不真实，不是握手失败——不能让探针替操作系统背锅。
    # 只摘 PYTHON* 键：PYTHONPATH 会决定子进程 import 哪个 mcp，
    # 路径上随便一个 mcp.py/mcp/ 就能把本测试测的东西换掉。SYSTEMROOT/PATH 必须留着。
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    return McpSession([sys.executable, str(ROOT / 'server.py')], env, budget)


def test_server_hands_shake_and_lists_drux_ping():
    with _session() as s:
        assert s.open(), f'stdio 握手失败：{getattr(s, "error", "未知原因")}'
        listed = s.request('tools/list')
        assert listed, f'tools/list 无响应：{getattr(s, "error", "")}'
        # JSON-RPC 的 error 信封在 mcp_client 里照样是真值，只判「非空」的话
        # 这条断言会放它过去，让失败落到 names 上、信息指不到真正的原因。
        err = listed.get('error')
        assert not err, f'tools/list 返回 JSON-RPC error：{err} / {getattr(s, "error", "")}'
        # `or []`：server 若回 "tools": null，.get('tools', []) 给的是 None 而不是 []，
        # 推导式会抛 TypeError 并把上面攒下的 error 上下文一起弄丢。
        tools = (listed.get('result') or {}).get('tools') or []
        names = [t.get('name') for t in tools]
        assert 'drux_ping' in names, f'探针工具未注册：{names} / {getattr(s, "error", "")}'


def test_cjk_argument_round_trips():
    probe = '边缘推理·调研 2026 年—含全角？'
    with _session() as s:
        assert s.open(), f'stdio 握手失败：{getattr(s, "error", "未知原因")}'
        got = s.request('tools/call', {'name': 'drux_ping', 'arguments': {'text': probe}})
        assert got, f'tools/call 无响应：{getattr(s, "error", "")}'
        err = got.get('error')
        assert not err, f'tools/call 返回 JSON-RPC error：{err} / {getattr(s, "error", "")}'
        payload = got.get('result') or {}
        text = (payload.get('content') or [{}])[0].get('text') or ''
        damaged = f'中文往返损坏：收到 {text!r}（isError={payload.get("isError")}）'
        assert probe in text, f'{damaged} / {getattr(s, "error", "")}'
