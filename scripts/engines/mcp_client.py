"""
Deep Research Ultra v4.0 — MCP 客户端封装

提供统一的 MCP 服务器调用接口：
- 配置检测（~/.claude.json / mcp.json）
- subprocess + JSON-RPC 调用 MCP 服务器
- 工具列表查询、工具调用
- 超时控制与错误处理

支持两种调用模式：
1. 独立模式：Python 脚本通过 subprocess 直接调用 MCP 服务器
2. Claude 模式：Claude 通过 run_mcp 工具调用（本类仅做可用性检测）

使用示例：
    client = McpClient("tavily")
    if client.is_configured():
        tools = client.list_tools()
        result = client.call_tool("tavily-search", {"query": "AI", "max_results": 5})
"""

import json
import os
import subprocess
import sys
import time
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# MCP 配置文件位置（按优先级）
# ============================================================

def _get_mcp_config_paths() -> List[Path]:
    """
    返回所有可能的 MCP 配置文件路径

    按优先级：
    1. 项目级 .mcp.json
    2. 项目级 .claude/mcp.json
    3. 用户级 ~/.claude.json（Claude Code 全局配置）
    4. 用户级 ~/.config/claude/mcp.json
    5. 项目级 .agents/mcp.json
    """
    home = Path.home()
    cwd = Path.cwd()
    return [
        cwd / ".mcp.json",
        cwd / ".claude" / "mcp.json",
        home / ".claude.json",
        home / ".config" / "claude" / "mcp.json",
        cwd / ".agents" / "mcp.json",
    ]


def load_mcp_config() -> Dict[str, Dict]:
    """
    加载 MCP 配置

    Returns:
        Dict[server_name, server_config]
        server_config 包含 command, args, env 等字段
    """
    for config_path in _get_mcp_config_paths():
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text(encoding='utf-8'))
            # 兼容两种格式：
            # 1. {"mcpServers": {...}}
            # 2. {server_name: {...}}
            if "mcpServers" in data:
                return data["mcpServers"]
            return data
        except (json.JSONDecodeError, OSError):
            continue
    return {}


# ============================================================
# MCP 客户端
# ============================================================

class McpClient:
    """
    MCP 服务器客户端

    封装 MCP 协议的 JSON-RPC 调用，提供：
    - is_configured(): 检测服务器是否已配置
    - is_available(): 检测服务器是否可达（启动 + initialize 握手）
    - list_tools(): 列出服务器提供的工具
    - call_tool(): 调用特定工具
    """

    # 初始化超时（秒）
    INIT_TIMEOUT = 10
    # 工具调用超时（秒）
    CALL_TIMEOUT = 60

    def __init__(self, server_name: str, config: Optional[Dict] = None):
        """
        Args:
            server_name: MCP 服务器名称（如 'tavily', 'open-websearch'）
            config: 显式配置（覆盖自动检测）
        """
        self.server_name = server_name
        self._config = config
        self._cached_tools: Optional[List[Dict]] = None
        self._process: Optional[subprocess.Popen] = None

    # ------------------------------------------------------------
    # 配置检测
    # ------------------------------------------------------------

    @property
    def config(self) -> Optional[Dict]:
        """获取服务器配置"""
        if self._config is not None:
            return self._config
        all_config = load_mcp_config()
        return all_config.get(self.server_name)

    def is_configured(self) -> bool:
        """检测 MCP 服务器是否已在配置文件中注册"""
        return self.config is not None

    def get_command(self) -> Optional[List[str]]:
        """获取启动命令"""
        cfg = self.config
        if not cfg:
            return None
        command = cfg.get("command")
        args = cfg.get("args", [])
        if not command:
            return None
        return [command] + list(args)

    def get_env(self) -> Dict[str, str]:
        """获取环境变量"""
        cfg = self.config
        if not cfg:
            return {}
        env = os.environ.copy()
        env.update(cfg.get("env", {}))
        return env

    # ------------------------------------------------------------
    # 可达性检测
    # ------------------------------------------------------------

    def is_available(self) -> bool:
        """
        检测 MCP 服务器是否可用

        检测策略：
        1. 配置存在性检查
        2. 命令可执行性检查（command 是否在 PATH 中）
        3. 不主动启动服务器（避免阻塞），仅做静态检查
        """
        if not self.is_configured():
            return False
        command_list = self.get_command()
        if not command_list:
            return False
        # 检查命令是否可执行
        cmd = command_list[0]
        # npx/uvx/node/python 等常见命令
        if shutil.which(cmd) is None:
            # 检查是否为绝对路径
            if not (Path(cmd).exists() and os.access(cmd, os.X_OK)):
                return False
        # 检查环境变量是否齐全
        cfg = self.config
        required_env = list(cfg.get("env", {}).keys())
        for key in required_env:
            if not os.environ.get(key) and key not in os.environ:
                # 环境变量未设置，但配置中可能有值
                env_value = cfg.get("env", {}).get(key)
                if not env_value:
                    return False
        return True

    # ------------------------------------------------------------
    # JSON-RPC 调用
    # ------------------------------------------------------------

    def _send_rpc(self, method: str, params: Optional[Dict] = None,
                  timeout: Optional[int] = None) -> Optional[Dict]:
        """
        发送 JSON-RPC 请求（通过 stdio）

        Args:
            method: RPC 方法名（如 'initialize', 'tools/list', 'tools/call'）
            params: 参数
            timeout: 超时（秒）

        Returns:
            响应结果，失败返回 None
        """
        command_list = self.get_command()
        if not command_list:
            return None
        env = self.get_env()
        timeout = timeout or self.CALL_TIMEOUT

        # 构建 JSON-RPC 请求
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
        }
        if params:
            request["params"] = params

        try:
            # 启动 MCP 服务器进程
            process = subprocess.Popen(
                command_list,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                encoding='utf-8',
                bufsize=1,
            )
            self._process = process

            # 发送请求
            request_str = json.dumps(request) + "\n"
            process.stdin.write(request_str)
            process.stdin.flush()

            # 读取响应（带超时）
            start_time = time.time()
            while True:
                if time.time() - start_time > timeout:
                    process.kill()
                    return None
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        return None
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    response = json.loads(line)
                    if response.get("id") == request["id"]:
                        return response
                except json.JSONDecodeError:
                    continue
        except (subprocess.SubprocessError, OSError):
            return None
        finally:
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None

    def _initialize(self) -> bool:
        """执行 MCP 初始化握手"""
        response = self._send_rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "deep-research-ultra",
                    "version": "4.0.0",
                },
            },
            timeout=self.INIT_TIMEOUT,
        )
        if not response or "result" not in response:
            return False
        # 发送 initialized 通知
        self._send_rpc("notifications/initialized", {})
        return True

    # ------------------------------------------------------------
    # 工具调用接口
    # ------------------------------------------------------------

    def list_tools(self, refresh: bool = False) -> List[Dict]:
        """
        列出 MCP 服务器提供的工具

        Args:
            refresh: 是否刷新缓存

        Returns:
            工具列表，每个工具包含 name, description, inputSchema
        """
        if self._cached_tools is not None and not refresh:
            return self._cached_tools

        if not self._initialize():
            return []

        response = self._send_rpc("tools/list", {})
        if not response or "result" not in response:
            return []
        tools = response["result"].get("tools", [])
        self._cached_tools = tools
        return tools

    def call_tool(self, tool_name: str, arguments: Optional[Dict] = None,
                  timeout: Optional[int] = None) -> Optional[Dict]:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            timeout: 超时（秒）

        Returns:
            工具调用结果，失败返回 None
        """
        if not self._initialize():
            return None

        response = self._send_rpc(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments or {},
            },
            timeout=timeout or self.CALL_TIMEOUT,
        )
        if not response:
            return None
        if "error" in response:
            return {"error": response["error"]}
        return response.get("result")

    # ------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------

    def has_tool(self, tool_name: str) -> bool:
        """检查是否提供特定工具"""
        tools = self.list_tools()
        return any(t.get("name") == tool_name for t in tools)

    def get_tool_names(self) -> List[str]:
        """获取所有工具名"""
        tools = self.list_tools()
        return [t.get("name", "") for t in tools]

    def __repr__(self) -> str:
        return f"<McpClient server={self.server_name} configured={self.is_configured()} available={self.is_available()}>"


# ============================================================
# 便捷函数
# ============================================================

def list_all_configured_mcps() -> Dict[str, Dict]:
    """列出所有已配置的 MCP 服务器"""
    return load_mcp_config()


def check_mcp_health(server_name: str) -> Dict[str, Any]:
    """
    检查 MCP 服务器健康状态

    Returns:
        {
            'configured': bool,
            'available': bool,
            'tools': List[str],
            'error': Optional[str],
        }
    """
    client = McpClient(server_name)
    result = {
        'configured': client.is_configured(),
        'available': False,
        'tools': [],
        'error': None,
    }
    if not result['configured']:
        result['error'] = f"MCP 服务器 '{server_name}' 未在配置文件中注册"
        return result
    if not client.is_available():
        result['error'] = f"MCP 服务器 '{server_name}' 命令不可执行或环境变量缺失"
        return result
    try:
        tools = client.list_tools(refresh=True)
        result['available'] = True
        result['tools'] = [t.get('name', '') for t in tools]
    except Exception as e:
        result['error'] = str(e)
    return result


# ============================================================
# CLI 入口
# ============================================================

def _main():
    """命令行入口：python mcp_client.py [server_name]"""
    if len(sys.argv) < 2:
        # 列出所有已配置的 MCP
        print("已配置的 MCP 服务器：")
        for name, cfg in load_mcp_config().items():
            cmd = cfg.get('command', '')
            print(f"  - {name}: {cmd}")
        return
    server_name = sys.argv[1]
    health = check_mcp_health(server_name)
    print(json.dumps(health, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
