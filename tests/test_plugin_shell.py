"""计划 A 探针：本地 Python 能否作为 stdio MCP server 被真握手。"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from engines.mcp_client import McpSession  # noqa: E402


def _session(budget: float = 25.0) -> McpSession:
    # env 用「继承进程环境」而不是 {}：本仓库对 McpSession 的唯一生产用法
    # （scripts/engines/mcp_client.py:384 get_env）就是 os.environ.copy() + 配置项。
    # 实测传 {} 时 Windows 子进程连 `import asyncio` 都过不去
    # （_overlapped → OSError [WinError 10106] WSAStartup 起不来），
    # 那是 fixture 不真实，不是握手失败——不能让探针替操作系统背锅。
    return McpSession([sys.executable, str(ROOT / 'server.py')], dict(os.environ), budget)


def test_server_hands_shake_and_lists_drux_ping():
    with _session() as s:
        assert s.open(), f'stdio 握手失败：{getattr(s, "error", "未知原因")}'
        listed = s.request('tools/list')
        assert listed, f'tools/list 无响应：{getattr(s, "error", "")}'
        names = [t.get('name') for t in (listed.get('result') or {}).get('tools', [])]
        assert 'drux_ping' in names, f'探针工具未注册：{names} / {getattr(s, "error", "")}'
