"""跨宿主安装器：一条命令把本包装进 Qoder / TRAE。

形态依据 2026-09-21 本机实测（见 docs/specs/2026-09-20-drux-plugin-mcp-design.md 第十五节）：
两家的 skill 都是 `<home>/.<宿主>/skills/<名>/SKILL.md`（顶层必须直接放 SKILL.md），
TRAE 的 MCP 配置 `%APPDATA%/Trae CN/User/mcp.json` 与插件的 mcp.json 同构。

MCP 命令一律写绝对路径：`${QODER_PLUGIN_ROOT}` 只有 Qoder 认，换宿主就找不到脚本。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SKILL_NAME = 'deep-research-ultra'
SUPPORTED_HOSTS = ('qoder', 'trae')


class InstallError(Exception):
    """安装做不下去。必须显式抛出，不许静默降级——半装状态比不装更难查。"""


@dataclass
class Report:
    host: str
    skill_dest: Path
    mcp_action: str  # added / updated / unchanged / skipped
    mcp_path: Optional[Path] = None
    dry_run: bool = False
    next_step: str = ''


def _host_dirs(host: str, home: Path, appdata: Optional[Path]):
    """返回 (skill 落点父目录, MCP 配置文件或 None)。"""
    if host == 'qoder':
        return home / '.qoder' / 'skills', None
    if host == 'trae':
        base = Path(appdata) if appdata else (Path(os.environ['APPDATA'])
                                              if os.environ.get('APPDATA')
                                              else home / 'Library' / 'Application Support')
        return home / '.trae-cn' / 'skills', base / 'Trae CN' / 'User' / 'mcp.json'
    raise InstallError(
        f'不支持的宿主：{host}。已实测的宿主只有 {", ".join(SUPPORTED_HOSTS)}；'
        f'其它宿主直接把 skills/{SKILL_NAME}/ 拷进它的 skill 目录即可，无需注册。')


def _merge_mcp_config(cfg: dict, entry: dict) -> tuple[dict, str]:
    """幂等合并：只动我们那一条，别人的条目和未知顶层键原样保留。"""
    servers = cfg.setdefault('mcpServers', {})
    if not isinstance(servers, dict):
        raise InstallError('mcp.json 的 mcpServers 不是对象，拒绝猜测结构')
    old = servers.get(SKILL_NAME)
    if old is None:
        servers[SKILL_NAME] = dict(entry)
        return cfg, 'added'
    if old == entry:
        return cfg, 'unchanged'
    # 保留用户自己加的键（disabled、headers 等），只覆盖定位脚本所必需的字段
    servers[SKILL_NAME] = {**old, **entry}
    return cfg, 'updated'


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        # 坏 JSON 直接硬停：把整份配置改写成我们的，等于顺手清掉了用户的白名单
        raise InstallError(f'{path} 不是合法 JSON（{exc}），拒绝覆盖写入') from exc
    if not isinstance(data, dict):
        raise InstallError(f'{path} 顶层不是对象，拒绝改写')
    return data


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def run_install(host: str, *, repo_root: Path, home: Path,
                appdata: Optional[Path] = None, dry_run: bool = False) -> Report:
    repo_root = Path(repo_root)
    skill_src = repo_root / 'skills' / SKILL_NAME
    if not (skill_src / 'SKILL.md').exists():
        raise InstallError(f'{skill_src} 里没有 SKILL.md：--repo-root 指错了吗')
    server_src = repo_root / 'server.py'
    if not server_src.exists():
        server_src = skill_src / 'server.py'
    if not server_src.exists():
        raise InstallError('找不到 server.py，MCP 那条没法写绝对路径')

    skills_dir, mcp_path = _host_dirs(host, Path(home), appdata)
    dest = skills_dir / SKILL_NAME
    if dest.exists():
        # 整个仓库被塞进 skills 目录（本机 TRAE 现状）：带 .git 的目录可能是用户还在改的
        # 仓库，删掉不可逆 → 交给人判断，安装器不动手。
        if (dest / '.git').exists():
            raise InstallError(
                f'{dest} 像一个 git 仓库（存在 .git），拒绝覆盖。'
                f'请人工确认后再把它换成 {skill_src} 的内容。')
    if mcp_path is not None and mcp_path.exists():
        # 先验配置再动文件：避免 skill 已经拷完、却在写 MCP 时炸在半路
        _load_json(mcp_path)

    entry = {'command': 'python', 'args': [(dest / 'server.py').as_posix()]}

    if not dry_run:
        if dest.exists():
            shutil.rmtree(dest)
        skills_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_src, dest)
        shutil.copy2(server_src, dest / 'server.py')

    if mcp_path is None:
        mcp_action = 'skipped'
        next_step = ('Qoder 的 MCP 由插件壳提供：把整个仓库导出到插件缓存位 '
                     '(mkdir -p ~/.qoder/plugins/cache/local/deep-research-ultra/7.0.0 && '
                     'git archive HEAD | tar -x -C 该目录) 再登记启用，见 README 方式二')
    else:
        cfg = _load_json(mcp_path) if mcp_path.exists() else {}
        cfg, mcp_action = _merge_mcp_config(cfg, entry)
        if mcp_action in ('added', 'updated') and not dry_run:
            mcp_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(mcp_path, cfg)
        next_step = '新开一个会话才会看到 drux_* 工具（宿主工具表是启动时的快照）'

    if dry_run:
        return Report(host, dest, mcp_action, mcp_path, True, next_step)

    if not (dest / 'SKILL.md').exists():
        raise InstallError(f'安装后 {dest / "SKILL.md"} 不存在，拷贝没成功')
    return Report(host, dest, mcp_action, mcp_path, False, next_step)


def default_repo_root() -> Path:
    """从脚本自身位置回推仓库根：兼容「从克隆装」和「从已装位再装一次」。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / 'server.py').exists() and (parent / 'skills' / SKILL_NAME / 'SKILL.md').exists():
            return parent
    return here.parents[2].parent


def main(argv=None) -> int:
    # 中文提示经管道时默认按 cp936 编码，调用方（宿主/pytest）按 UTF-8 读会炸在解码上，
    # 报错看起来像"安装器崩了"而不是"控制台编码不对"。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description=f'把 {SKILL_NAME} 装进指定宿主')
    parser.add_argument('--host', required=True, help=f'{" | ".join(SUPPORTED_HOSTS)}')
    parser.add_argument('--dry-run', action='store_true', help='只报将要做什么，不写任何文件')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认从脚本位置回推）')
    args = parser.parse_args(argv)

    try:
        report = run_install(args.host,
                             repo_root=Path(args.repo_root) if args.repo_root else default_repo_root(),
                             home=Path.home(), dry_run=args.dry_run)
    except InstallError as exc:
        print(f'安装失败：{exc}', file=sys.stderr)
        return 2
    print(f"宿主 {report.host}：skill → {report.skill_dest}")
    print(f'MCP：{report.mcp_action}' + (f' → {report.mcp_path}' if report.mcp_path else ''))
    if report.dry_run:
        print('（dry-run，未写任何文件）')
    if report.next_step:
        print(f'下一步：{report.next_step}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
