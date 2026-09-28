"""Windows 上 MCP server 起不来：裸 `npx` 是 shell 脚本，CreateProcess 认不了。

实测（2026-09-28，插件安装位真跑 `--probe --sources open-websearch,arxiv,paper-search`）：

    ❌ open-websearch  引擎返回 None（open-websearch: 进程起不来：[WinError 2] 系统找不到指定的文件。）
    ❌ paper-search    引擎返回 None（paper-search: 进程起不来：[WinError 2] 系统找不到指定的文件。）
    ❌ arxiv           引擎返回 None（arxiv: arXiv API HTTP error (HTTP 406)）   ← 这条起得来，是上游问题

前两条不是没装：`C:\\Program Files\\nodejs` 里同时有 `npx`（bash 脚本）、`npx.cmd`、`npx.ps1`。
`setup-mcp.sh` 与宿主配置写的都是裸名 `npx`，Python 的 CreateProcess 只会找可执行文件，
于是报"系统找不到指定的文件"——读起来像"这个工具没装"，实际是启动名缺了 `.cmd`。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines import mcp_client  # noqa: E402


@pytest.fixture()
def fake_nodejs(tmp_path, monkeypatch):
    """造一个 bin 目录：里面同时有裸 `npx` 和 `npx.cmd`，像真的 nodejs 安装位。"""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'npx').write_text('#!/bin/sh\n', encoding='utf-8')
    (bin_dir / 'npx.cmd').write_text('@echo off\r\n', encoding='utf-8')
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
    return bin_dir


def test_bare_launcher_resolves_to_the_cmd_form_on_windows(fake_nodejs, monkeypatch):
    """Windows 上 `npx` 必须换成 `npx.cmd`，否则进程根本起不来。"""
    monkeypatch.setattr(mcp_client.os, 'name', 'nt')

    assert Path(mcp_client._resolve_command('npx')).name == 'npx.cmd'


def test_already_suffixed_launcher_is_left_alone(fake_nodejs, monkeypatch):
    """正向对照：写了 npx.cmd 的不许再拼一次后缀。"""
    monkeypatch.setattr(mcp_client.os, 'name', 'nt')

    assert mcp_client._resolve_command('npx.cmd') == 'npx.cmd'


def test_unknown_command_keeps_its_own_name(fake_nodejs, monkeypatch):
    """找不到 .cmd 时保持原样——否则"没装"的报错会被写成另一个命令名，把人带偏。"""
    monkeypatch.setattr(mcp_client.os, 'name', 'nt')

    assert mcp_client._resolve_command('definitely-not-installed') == 'definitely-not-installed'


def test_posix_does_not_rewrite(fake_nodejs, monkeypatch):
    """非 Windows 不动：那边裸 npx 就是可执行的，加后缀反而起不来。"""
    monkeypatch.setattr(mcp_client.os, 'name', 'posix')

    assert mcp_client._resolve_command('npx') == 'npx'


def test_session_uses_the_resolved_launcher(fake_nodejs, monkeypatch):
    """解析要发生在真正起进程的那条路上，不然测试绿了行为没变。"""
    monkeypatch.setattr(mcp_client.os, 'name', 'nt')
    seen = {}

    def fake_popen(argv, **kwargs):
        seen['argv'] = argv
        raise OSError('ENOENT probe only')

    monkeypatch.setattr(mcp_client.subprocess, 'Popen', fake_popen)
    session = mcp_client.McpSession(['npx', '-y', 'pkg'], {}, budget=1)
    session.open()

    assert Path(seen['argv'][0]).name == 'npx.cmd', seen
    assert seen['argv'][1:] == ['-y', 'pkg'], '参数不能被动过'
