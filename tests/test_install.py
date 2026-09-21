"""计划 C：跨宿主安装器 install.py 的行为契约。

宿主落点是 2026-09-21 本机实测来的，不是文档里的：
- TRAE CN：skills 在 <home>/.trae-cn/skills/<名>/SKILL.md（顶层必须直接是 SKILL.md），
  MCP 配置在 <appdata>/Trae CN/User/mcp.json，格式 {"mcpServers":{名:{command,args,env}}}
- Qoder：skills 在 <home>/.qoder/skills/，MCP 走插件壳的 mcp.json（用 ${QODER_PLUGIN_ROOT}），
  所以 Qoder 侧只装 skill、不动任何用户配置
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills' / 'deep-research-ultra' / 'scripts'))

import install  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path):
    """造一个最小但形状真实的仓库：skill 下沉布局 + 根级 server.py。"""
    repo = tmp_path / 'repo'
    skill = repo / 'skills' / 'deep-research-ultra'
    (skill / 'scripts').mkdir(parents=True)
    (skill / 'SKILL.md').write_text('# Deep Research Ultra\n', encoding='utf-8')
    (skill / 'requirements.txt').write_text('ddgs\n', encoding='utf-8')
    (skill / 'scripts' / 'research.py').write_text('print(1)\n', encoding='utf-8')
    (repo / 'server.py').write_text('print(2)\n', encoding='utf-8')
    return repo


@pytest.fixture
def hosts(tmp_path):
    home = tmp_path / 'home'
    appdata = tmp_path / 'AppData' / 'Roaming'
    home.mkdir(parents=True)
    appdata.mkdir(parents=True)
    return home, appdata


def test_trae_install_puts_skill_md_at_top(tmp_path, fake_repo):
    home = tmp_path / 'home'
    appdata = tmp_path / 'Roaming'
    home.mkdir()
    appdata.mkdir()

    report = install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata)

    top = home / '.trae-cn' / 'skills' / 'deep-research-ultra'
    assert (top / 'SKILL.md').exists(), f'SKILL.md 没在顶层，TRAE 扫不到：{report}'
    assert (top / 'scripts' / 'research.py').exists()
    # server.py 必须跟着进安装位：TRAE 的 mcp.json 只认绝对路径，不认仓库位置
    assert (top / 'server.py').exists(), 'server.py 没被拷进安装位'
    assert report.skill_dest == top


def test_trae_writes_mcp_entry_with_absolute_path(tmp_path, fake_repo):
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    home.mkdir()
    appdata.mkdir()

    install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata)

    cfg_path = appdata / 'Trae CN' / 'User' / 'mcp.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    entry = cfg['mcpServers']['deep-research-ultra']
    server = entry['args'][0]
    assert Path(server).is_absolute(), f'MCP 路径必须是绝对路径：{server}'
    assert Path(server).exists(), f'写进去的 server.py 路径指向空气：{server}'
    # env 一旦出现可能被宿主当完整替换：没有 SYSTEMROOT 时子进程死在 import _overlapped
    # （WinError 10106），那副长相和"握手不可能"一模一样。
    assert 'env' not in entry, 'mcp 条目加了 env：宿主按完整替换处理会丢 SYSTEMROOT'
    assert entry['command'] == 'python'


def test_trae_install_is_idempotent_and_preserves_foreign_servers(tmp_path, fake_repo):
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    home.mkdir()
    appdata.mkdir()
    user_dir = appdata / 'Trae CN' / 'User'
    user_dir.mkdir(parents=True)
    (user_dir / 'mcp.json').write_text(json.dumps({
        'mcpServers': {'context7': {'command': 'npx', 'args': ['-y', 'x'], 'fromGalleryId': 'g'}},
        'someOtherTopLevelKey': 1,
    }), encoding='utf-8')

    first = install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata)
    cfg_path = user_dir / 'mcp.json'
    text_after_first = cfg_path.read_text(encoding='utf-8')
    second = install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata)

    assert cfg_path.read_text(encoding='utf-8') == text_after_first, \
        '第二次安装改动了 mcp.json：不幂等'
    assert second.mcp_action == 'unchanged', f'重复安装应当报 unchanged：{second.mcp_action}'
    assert first.mcp_action == 'added'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    assert cfg['mcpServers']['context7']['fromGalleryId'] == 'g', '别人的 MCP 条目被冲掉了'
    assert cfg['someOtherTopLevelKey'] == 1, 'mcp.json 的未知顶层键被丢'
    assert len(cfg['mcpServers']) == 2


def test_trae_updates_stale_entry_without_losing_its_other_keys(tmp_path, fake_repo):
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    home.mkdir()
    appdata.mkdir()
    user_dir = appdata / 'Trae CN' / 'User'
    user_dir.mkdir(parents=True)
    (user_dir / 'mcp.json').write_text(json.dumps({'mcpServers': {
        'deep-research-ultra': {'command': 'python', 'args': ['D:/旧位置/server.py'],
                                'disabled': False}}}), encoding='utf-8')

    report = install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata)

    entry = json.loads((user_dir / 'mcp.json').read_text(encoding='utf-8'))['mcpServers'][
        'deep-research-ultra']
    assert entry['args'][0] != 'D:/旧位置/server.py', '旧路径没被更新'
    assert entry['disabled'] is False, '更新条目时丢了用户自己的其它键'
    assert report.mcp_action == 'updated'


def test_broken_mcp_json_is_refused_not_overwritten(tmp_path, fake_repo):
    """坏 JSON 必须硬停：把它整体改写成我们的，等于替用户清空白名单。"""
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    home.mkdir()
    appdata.mkdir()
    user_dir = appdata / 'Trae CN' / 'User'
    user_dir.mkdir(parents=True)
    (user_dir / 'mcp.json').write_text('{ 坏掉的 json', encoding='utf-8')

    with pytest.raises(install.InstallError) as exc:
        install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata)
    assert 'mcp.json' in str(exc.value)
    assert (user_dir / 'mcp.json').read_text(encoding='utf-8') == '{ 坏掉的 json'


def test_refuses_to_clobber_a_repo_clone(tmp_path, fake_repo):
    """本机 TRAE 现状：整个仓库被塞进 skills 目录（顶层没有 SKILL.md，带 .git）。

    这种目标可能是用户还在改的仓库，删掉不可逆 → 必须拒绝并交给人判断。
    """
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    dest = home / '.trae-cn' / 'skills' / 'deep-research-ultra'
    (dest / '.git').mkdir(parents=True)
    (dest / 'keep-me.md').write_text('别删我', encoding='utf-8')
    appdata.mkdir()

    with pytest.raises(install.InstallError) as exc:
        install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata)
    assert 'git' in str(exc.value).lower()
    assert (dest / 'keep-me.md').exists(), '拒绝之前已经把目标删了'


def test_replaces_an_ordinary_old_install(tmp_path, fake_repo):
    """普通旧版本（无 .git）就该被覆盖替换——用户明确要的行为。"""
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    dest = home / '.trae-cn' / 'skills' / 'deep-research-ultra'
    (dest / 'scripts').mkdir(parents=True)
    (dest / 'SKILL.md').write_text('# 旧版本\n', encoding='utf-8')
    appdata.mkdir()

    install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata)

    assert 'Deep Research Ultra' in (dest / 'SKILL.md').read_text(encoding='utf-8')


def test_unknown_host_is_rejected_with_the_supported_list(tmp_path, fake_repo):
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    home.mkdir()
    appdata.mkdir()

    with pytest.raises(install.InstallError) as exc:
        install.run_install('cursor', repo_root=fake_repo, home=home, appdata=appdata)
    msg = str(exc.value)
    for host in install.SUPPORTED_HOSTS:
        assert host in msg, f'报错没列出可用宿主：{msg}'


def test_qoder_host_installs_skill_and_touches_no_user_config(tmp_path, fake_repo):
    """Qoder 的 MCP 只在插件壳里（实测写法是 ${QODER_PLUGIN_ROOT}），
    安装器不去改注册表式文件，只把 skill 放好，并告诉用户插件那步怎么做。"""
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    home.mkdir()
    appdata.mkdir()

    report = install.run_install('qoder', repo_root=fake_repo, home=home, appdata=appdata)

    top = home / '.qoder' / 'skills' / 'deep-research-ultra'
    assert (top / 'SKILL.md').exists()
    assert report.mcp_action == 'skipped', 'Qoder 不该被写用户级 mcp 配置'
    assert report.next_step and 'git archive' in report.next_step


def test_dry_run_writes_nothing(tmp_path, fake_repo):
    home, appdata = tmp_path / 'home', tmp_path / 'Roaming'
    home.mkdir()
    appdata.mkdir()

    report = install.run_install('trae', repo_root=fake_repo, home=home, appdata=appdata,
                                 dry_run=True)

    assert not (home / '.trae-cn').exists(), 'dry-run 写了文件'
    assert not (appdata / 'Trae CN').exists(), 'dry-run 写了 mcp.json'
    assert report.dry_run is True


def test_cli_reports_failure_with_nonzero_exit(tmp_path, fake_repo):
    """CLI 失败必须非零退出：安装没成却退 0，会被上游 Agent 当成功继续往下走。"""
    proc = subprocess.run(
        [sys.executable, str(ROOT / 'skills' / 'deep-research-ultra' / 'scripts' / 'install.py'),
         '--host', 'nosuchhost'],
        capture_output=True, text=True, encoding='utf-8')
    assert proc.returncode != 0
    assert 'nosuchhost' in (proc.stdout + proc.stderr)
