"""deep-research-ultra 插件的 MCP server（计划 A：只放连通性探针）。

计划 B 会把 drux_ping 换成四个业务工具；本文件其余部分不动。

依赖：本机实测 mcp 2.1.1 —— 2.x 里 FastMCP 已改名为 MCPServer，
      import 路径是 mcp.server.mcpserver（写 mcp.server.fastmcp 会直接 ModuleNotFoundError）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))


def build_server():
    from mcp.server.mcpserver import MCPServer
    srv = MCPServer('deep-research-ultra')

    @srv.tool()
    def drux_ping(text: str) -> str:
        """连通性探针：原样返回入参（含中文）。计划 B 会删除本工具。"""
        return text

    return srv


def main() -> int:
    try:
        build_server().run()
    except ImportError as exc:  # 缺依赖必须显式失败，不许静默
        # 纯 ASCII：宿主按 UTF-8 读子进程 stderr，中文提示会在读取端炸掉并丢失
        print(f'drux-mcp requires the python mcp package: pip install "mcp>=2.1" ({exc})',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
