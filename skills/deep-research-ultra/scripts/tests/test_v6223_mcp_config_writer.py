"""setup-mcp.sh 的产物必须能被没有装 Claude Code CLI 的宿主读到。

实测矛盾：`--probe` 的提示让用户"缺就用 scripts/setup-mcp.sh --core 配"，
但该脚本把五个 server 全部写成 `claude mcp add`——宿主没有 claude 命令时脚本直接失败
（本机就是这种环境：Qoder 宿主，无 claude CLI）。也就是说这条指引对多数宿主是死路。

改法是加一个纯本地写入器 mcp_config_writer.py，把 server 写进 McpClient 本来就会读的
`.mcp.json`；claude 那条路保留成可选后端。这里锁写入器的行为（脚本只是调它）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS))

WRITER = SCRIPTS / 'mcp_config_writer.py'


def run_writer(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(WRITER), *args],
                          capture_output=True, text=True, encoding='utf-8')


def test_first_write_creates_the_file_with_mcp_servers(tmp_path):
    out = tmp_path / '.mcp.json'
    p = run_writer('--out', str(out), '--server', 'open-websearch',
                   '--env', 'DEFAULT_SEARCH_ENGINE=bing', '--',
                   'npx', '-y', 'open-websearch@latest')
    assert p.returncode == 0, p.stderr
    data = json.loads(out.read_text(encoding='utf-8'))
    server = data['mcpServers']['open-websearch']
    assert server['command'] == 'npx'
    assert server['args'] == ['-y', 'open-websearch@latest']
    assert server['env'] == {'DEFAULT_SEARCH_ENGINE': 'bing'}


def test_second_write_keeps_other_servers_and_existing_keys(tmp_path):
    """项目里可能已有别的 server 或别的顶层键，写一个不许把它们抹掉。"""
    out = tmp_path / '.mcp.json'
    out.write_text(json.dumps({'mcpServers': {'keepme': {'command': 'x'}},
                               'other': 1}), encoding='utf-8')
    p = run_writer('--out', str(out), '--server', 'arxiv', '--', 'uvx', 'arxiv-mcp-server')
    assert p.returncode == 0, p.stderr
    data = json.loads(out.read_text(encoding='utf-8'))
    assert set(data['mcpServers']) == {'keepme', 'arxiv'}
    assert data['other'] == 1


def test_rewriting_the_same_server_replaces_it_not_duplicates(tmp_path):
    out = tmp_path / '.mcp.json'
    run_writer('--out', str(out), '--server', 'arxiv', '--', 'uvx', 'old')
    run_writer('--out', str(out), '--server', 'arxiv', '--', 'uvx', 'new')
    data = json.loads(out.read_text(encoding='utf-8'))
    assert data['mcpServers']['arxiv']['args'] == ['new']


def test_writer_output_is_readable_by_the_mcp_client(tmp_path, monkeypatch):
    """闭环：写出来的文件要让 McpClient 真能认出这五个 server。"""
    from engines import mcp_client

    out = tmp_path / '.mcp.json'
    for name, cmd, *args in [('tavily', 'npx', '-y', 'tavily-mcp@latest'),
                             ('firecrawl', 'npx', '-y', 'firecrawl-mcp'),
                             ('open-websearch', 'npx', '-y', 'open-websearch@latest'),
                             ('arxiv', 'uvx', 'arxiv-mcp-server'),
                             ('paper-search', 'npx', '-y', 'paper-search-mcp-nodejs')]:
        p = run_writer('--out', str(out), '--server', name, '--', cmd, *args)
        assert p.returncode == 0, p.stderr

    monkeypatch.setattr(mcp_client, '_get_mcp_config_paths', lambda: [out])
    cfg = mcp_client.load_mcp_config()
    assert len(cfg) == 5, f'五个 server 都该被读到：{sorted(cfg)}'
    assert mcp_client.McpClient('paper-search').get_command()[:2] == [
        'npx', '-y'], 'McpClient 拿到的启动命令应与写入的一致'


def test_remove_drops_only_that_server(tmp_path):
    out = tmp_path / '.mcp.json'
    run_writer('--out', str(out), '--server', 'arxiv', '--', 'uvx', 'arxiv-mcp-server')
    run_writer('--out', str(out), '--server', 'open-websearch', '--', 'npx', '-y', 'ows')
    p = run_writer('--out', str(out), '--remove', 'arxiv')
    assert p.returncode == 0, p.stderr
    servers = json.loads(out.read_text(encoding='utf-8'))['mcpServers']
    assert list(servers) == ['open-websearch'], servers


def test_remove_reports_absent_server_with_nonzero_exit(tmp_path):
    """卸载脚本按退出码决定要不要说"已移除"——恒回 0 会报假成功。"""
    out = tmp_path / '.mcp.json'
    run_writer('--out', str(out), '--server', 'arxiv', '--', 'uvx', 'x')
    p = run_writer('--out', str(out), '--remove', 'nope')
    assert p.returncode != 0, '移除一个不存在的 server 不该报成功'


def test_list_shows_configured_servers_and_flags_empty(tmp_path):
    out = tmp_path / '.mcp.json'
    empty = run_writer('--out', str(out), '--list')
    assert empty.returncode != 0, '一个 server 都没有时不该报"已配置"'

    run_writer('--out', str(out), '--server', 'arxiv', '--', 'uvx', 'arxiv-mcp-server')
    p = run_writer('--out', str(out), '--list')
    assert p.returncode == 0, p.stderr
    assert 'arxiv' in p.stdout and 'uvx' in p.stdout, p.stdout


def test_setup_script_end_to_end_needs_no_claude_cli(tmp_path):
    """真跑 setup-mcp.sh（本机就是没有 claude 命令的宿主），产物必须是可启动的 server 表。

    这条是实测抓出来的：`register_server` 里 `--) cmd=("$@")` 会把 `--` 本身也当成命令，
    写出来的 .mcp.json 成了 command="--"、args=["npx",...]——单测打不到那一层。
    """
    out = tmp_path / '.mcp.json'
    p = subprocess.run(['bash', str(SCRIPTS / 'setup-mcp.sh'), '--core',
                        '--out', str(out)],
                       capture_output=True, text=True, encoding='utf-8',
                       cwd=str(tmp_path), timeout=180)
    assert p.returncode == 0, f'setup-mcp.sh 退出 {p.returncode}\n{p.stdout[-600:]}\n{p.stderr[-600:]}'
    servers = json.loads(out.read_text(encoding='utf-8'))['mcpServers']
    assert servers, f'--core 该至少配出一个免费 MCP：{p.stdout[-400:]}'
    for name, cfg in servers.items():
        assert cfg['command'] in ('npx', 'uvx'), f'{name} 的启动命令不对：{cfg}'
        assert cfg['args'], f'{name} 没有参数：{cfg}'
        assert '--' not in [cfg['command'], *cfg['args']], f'{name} 混进了 --：{cfg}'


def test_uninstall_reports_only_the_servers_that_were_actually_removed(tmp_path):
    """--core 只配了 3 个免费 MCP，卸载就不该说"已移除 tavily/firecrawl"。

    实测抓到 remove_server 里挂着 `|| true`，把"这个 server 不在"也吞成成功，
    于是清理日志恒报"移除 5 个"。报假成功的清理比不清理更糟。
    """
    def sh(*args):
        return subprocess.run(['bash', str(SCRIPTS / 'setup-mcp.sh'), *args],
                              capture_output=True, text=True, encoding='utf-8',
                              cwd=str(tmp_path), timeout=180)

    assert sh('--core').returncode == 0
    out = sh('--uninstall')
    assert out.returncode == 0, out.stdout[-500:]
    text = out.stdout
    assert '已移除 arxiv' in text and '已移除 paper-search' in text, text[-600:]
    for never in ('tavily', 'firecrawl'):
        assert f'已移除 {never}' not in text, f'{never} 根本没配过，却报已移除'
    assert '移除 3 个' in text, f'计数应与实际移除数一致：{text[-400:]}'
    assert json.loads((tmp_path / '.mcp.json').read_text(encoding='utf-8'))['mcpServers'] == {}


def test_setup_script_no_longer_requires_the_claude_cli():
    """脚本里 claude 只能作为可选后端，不能是唯一通路。"""
    text = (SCRIPTS / 'setup-mcp.sh').read_text(encoding='utf-8')
    assert 'mcp_config_writer.py' in text, 'setup-mcp.sh 还没接本地写入器'
    assert 'command -v claude' not in text or '可选' in text, \
        '脚本仍把 claude CLI 当硬依赖'
