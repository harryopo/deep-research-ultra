#!/usr/bin/env python3
"""读写 .mcp.json 里的 MCP server —— 不依赖任何宿主 CLI。

为什么要有这个：`setup-mcp.sh` 原先只走 `claude mcp add`，而 `--probe` 的提示又让用户
"缺就用 setup-mcp.sh 配"。宿主没装 Claude Code CLI 时（Qoder / TRAE / 纯 Python 宿主）
那条指引就是死路——本机实测如此。本工具直接产出 McpClient 会读的 .mcp.json：

    # 注册一个 server（命令与参数写在 -- 之后）
    python mcp_config_writer.py --out ./.mcp.json --server open-websearch \
        --env DEFAULT_SEARCH_ENGINE=bing -- npx -y open-websearch@latest

    python mcp_config_writer.py --out ./.mcp.json --list      # 看现在配了哪些
    python mcp_config_writer.py --out ./.mcp.json --remove arxiv

已有的 mcpServers 与其他顶层键一律保留；同名 server 覆盖（重复跑即幂等）。
配置文件本身坏了会报错退出——不许把用户写崩的配置静默覆盖掉。
--remove 移除不存在的 server 时回非零：调用方靠退出码决定报不报"已移除"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def parse_argv(argv: List[str]) -> Tuple[Path, str, Optional[str], Dict[str, str], List[str]]:
    """解析出 (输出路径, 模式, server 名, env 表, 命令与参数)。"""
    out = Path('.mcp.json')
    mode = 'add'
    server: Optional[str] = None
    env: Dict[str, str] = {}
    cmd: List[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == '--out':
            i += 1
            out = Path(argv[i])
        elif token == '--server':
            i += 1
            server = argv[i]
        elif token == '--env':
            i += 1
            pair = argv[i]
            if '=' not in pair:
                raise SystemExit(f'--env 要写成 K=V，收到 {pair!r}')
            key, _, value = pair.partition('=')
            env[key] = value
        elif token == '--remove':
            i += 1
            mode, server = 'remove', argv[i]
        elif token == '--list':
            mode = 'list'
        elif token == '--':
            cmd = list(argv[i + 1:])
            break
        else:
            raise SystemExit(f'不认识参数 {token!r}（用法见 --help）')
        i += 1

    if mode == 'add':
        if not server:
            raise SystemExit('缺少 --server <名字>')
        if not cmd:
            raise SystemExit('命令与参数要写在 -- 之后，例如 -- npx -y open-websearch@latest')
    elif mode == 'remove' and not server:
        raise SystemExit('--remove 后面要跟 server 名')
    return out, mode, server, env, cmd


def read_config(out: Path) -> Dict:
    """整份配置读出来（文件不存在回 {}）。格式不对就退出——不猜，也不覆盖用户文件。"""
    if not out.exists():
        return {}
    raw = out.read_text(encoding='utf-8').strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f'{out} 不是合法 JSON（{exc}），不改写它')
    if not isinstance(data, dict):
        raise SystemExit(f'{out} 顶层必须是对象')
    servers = data.get('mcpServers')
    if servers is not None and not isinstance(servers, dict):
        raise SystemExit(f'{out} 里的 mcpServers 不是对象，拒绝改写')
    return data


def read_servers(out: Path) -> Dict[str, Dict]:
    return read_config(out).get('mcpServers') or {}


def _write(out: Path, data: Dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                   encoding='utf-8')


def merge_server(out: Path, server: str, env: Dict[str, str], cmd: List[str]) -> None:
    """读旧配置（若有）、写入这一个 server、回写，其余内容一律不动。"""
    data = read_config(out)
    data.setdefault('mcpServers', {})
    entry: Dict = {'command': cmd[0], 'args': cmd[1:]}
    if env:
        entry['env'] = env
    data['mcpServers'][server] = entry
    _write(out, data)


def remove_server(out: Path, server: str) -> bool:
    """从配置里移除一个 server；它本来不在（或文件不在）回 False。"""
    if server not in read_servers(out):
        return False
    data = read_config(out)
    del data['mcpServers'][server]
    _write(out, data)
    return True


def main(argv: List[str]) -> int:
    if argv and argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    out, mode, server, env, cmd = parse_argv(argv)

    if mode == 'list':
        servers = read_servers(out)
        if not servers:
            print(f'（{out} 里没有任何 MCP server）', file=sys.stderr)
            return 1
        for name, cfg in servers.items():
            argv_line = ' '.join([str(cfg.get('command', ''))] +
                                 [str(a) for a in cfg.get('args', [])]).strip()
            print(f'{name}: {argv_line}')
        return 0

    if mode == 'remove':
        if remove_server(out, server or ''):
            print(f'✅ 已从 {out} 移除 {server}')
            return 0
        print(f'❌ {out} 里没有 {server}，未改动', file=sys.stderr)
        return 1

    merge_server(out, server or '', env, cmd)
    print(f'✅ 已写入 {out} → mcpServers.{server} = {" ".join(cmd)}')
    return 0


if __name__ == '__main__':
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
        try:
            from console import force_utf8
            force_utf8()
        except Exception:      # 独立可用：没带 console 也能跑
            pass
    sys.exit(main(sys.argv[1:]))
