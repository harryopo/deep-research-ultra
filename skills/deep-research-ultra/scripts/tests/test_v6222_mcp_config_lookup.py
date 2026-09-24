"""MCP 配置查找：项目级配置遮蔽用户级配置，导致「配好了却报未配置」。

实测起因：同一条 `research.py --probe --sources arxiv,paper-search`
- 在工作区目录跑 → 两个 server 都连上了（工作区 .mcp.json 里五个都在）；
- 换到 scripts 目录跑 → 「未配置 MCP server 'arxiv'（配置文件里没有，或缺 command）」。

旧 load_mcp_config() 只读**第一个存在的**配置文件就 return，后面的用户级配置根本不参与。
所以项目里只要放了一个只含部分 server 的 .mcp.json，用户级那批就整体消失——
而且提示词只说"配置文件里没有"，不说是哪些配置文件，用户没法定位。

这里锁两件事：① 跨文件合并（项目级同名优先）；② 未配置要点名查过哪些路径。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines import mcp_client  # noqa: E402


def _write(path: Path, servers: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'mcpServers': servers}), encoding='utf-8')


@pytest.fixture()
def two_levels(tmp_path, monkeypatch):
    """项目级只配 tavily，用户级配 tavily + arxiv（arxiv 只在用户级有）。"""
    project = tmp_path / 'proj' / '.mcp.json'
    user = tmp_path / 'home' / '.claude.json'
    _write(project, {'tavily': {'command': 'node', 'args': ['project-tavily.js']}})
    _write(user, {'tavily': {'command': 'node', 'args': ['user-tavily.js']},
                  'arxiv': {'command': 'uvx', 'args': ['arxiv-mcp-server']}})
    monkeypatch.setattr(mcp_client, '_get_mcp_config_paths',
                        lambda: [project, user])
    return project, user


def test_servers_only_in_the_user_config_are_still_visible(two_levels):
    cfg = mcp_client.load_mcp_config()
    assert 'arxiv' in cfg, \
        f'项目级配置一存在就把用户级整份遮住，server 凭空消失：{sorted(cfg)}'


def test_project_level_wins_on_same_server_name(two_levels):
    cfg = mcp_client.load_mcp_config()
    assert cfg['tavily']['args'] == ['project-tavily.js'], \
        '同名 server 应按优先级取项目级那份'


def test_malformed_project_config_does_not_hide_the_user_config(tmp_path, monkeypatch):
    """坏 JSON 早就有 continue 兜底，但合并改造不许把它弄丢。"""
    project = tmp_path / 'proj' / '.mcp.json'
    user = tmp_path / 'home' / '.claude.json'
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text('{ 这不是 JSON', encoding='utf-8')
    _write(user, {'arxiv': {'command': 'uvx', 'args': ['arxiv-mcp-server']}})
    monkeypatch.setattr(mcp_client, '_get_mcp_config_paths', lambda: [project, user])
    assert 'arxiv' in mcp_client.load_mcp_config()


def test_unconfigured_message_names_the_files_that_were_searched(tmp_path, monkeypatch):
    """提示必须说得出"查过哪里"，否则用户不知道该把 server 配到哪个文件。"""
    project = tmp_path / 'proj' / '.mcp.json'
    _write(project, {'tavily': {'command': 'node', 'args': ['t.js']}})
    missing = tmp_path / 'home' / '.claude.json'
    monkeypatch.setattr(mcp_client, '_get_mcp_config_paths', lambda: [project, missing])

    client = mcp_client.McpClient('arxiv')
    assert client.open_session(budget=1) is None
    err = client.last_error
    assert '.mcp.json' in err, f'没说出查过哪个存在的配置：{err}'
    assert str(missing.name) in err, f'没说出还查过这个（不存在的）路径：{err}'
