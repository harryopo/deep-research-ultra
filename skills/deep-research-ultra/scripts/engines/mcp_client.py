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
import queue
import signal
import subprocess
import sys
import threading
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


def _load_mcp_sources() -> List[Tuple[Path, Dict[str, Dict]]]:
    """逐个读 MCP 配置文件，返回 [(路径, 该文件的 server 表)]，顺序即优先级。

    坏 JSON 或读不动的文件不进合并，但它照样出现在"查过哪里"的清单里。
    """
    sources: List[Tuple[Path, Dict[str, Dict]]] = []
    for config_path in _get_mcp_config_paths():
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        # 兼容两种格式：{"mcpServers": {...}} 与直接 {server_name: {...}}
        inner = data.get('mcpServers')
        table = inner if isinstance(inner, dict) else data
        sources.append((config_path,
                        {k: v for k, v in table.items() if isinstance(v, dict)}))
    return sources


def load_mcp_config() -> Dict[str, Dict]:
    """合并所有存在的 MCP 配置文件，同名 server 按优先级取项目级那份。

    旧实现读到第一个存在的文件就直接 return：项目里只要放一个只含部分 server 的
    `.mcp.json`，用户级配置里那批就整体消失，自检随之报"未配置"——
    配置明明在，只是没被看见。实测同一个 `--probe` 换个 cwd 跑就时好时坏。
    """
    merged: Dict[str, Dict] = {}
    for _path, table in _load_mcp_sources():
        for name, cfg in table.items():
            merged.setdefault(name, cfg)
    return merged


def describe_mcp_config_search() -> str:
    """把"查过哪些配置文件"写成一句人话，供未配置提示点名路径（"有"＝该文件存在）。"""
    found = {str(p) for p, _ in _load_mcp_sources()}
    return '、'.join(f'{p}（有）' if str(p) in found else str(p)
                     for p in _get_mcp_config_paths()) or '（无候选路径）'


# stdio 会话
# ============================================================

_EOF = object()


def _kill_tree(proc: subprocess.Popen) -> None:
    """杀掉整棵进程树。

    `npx -y tavily-mcp` 起的是 npx → node 两层，只 `proc.kill()` 会留下一个还在
    占端口/占内存的 server 进程；Windows 用 taskkill /T，POSIX 杀进程组。
    """
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                           capture_output=True)
            return
        except OSError:
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


class McpSession:
    """一个进程里跑完「握手 → initialized 通知 → 若干请求」。

    两条实测出来的硬要求，缺一条 MCP 就探不出真实结果：

    1. **同一进程**：旧实现每发一条 JSON-RPC 就新起一个进程，`initialize` 落在第 1 个、
       `tools/call` 落在第 3 个从没握过手的进程，按规范实现的 server 直接回
       `-32002 Server not initialized`——环境全配好也恒拿 0 结果。
    2. **可中断的超时**：旧实现只在 `readline()` 之前判一次时间，读本身卡住就再也判不到，
       2 秒预算实测 14.9 秒不返回。这里把读放进后台线程，主线程从队列取，到点就走。
       `stderr` 同样有线程排空，否则 server 刷日志撑满管道缓冲会把 stdout 一起拖死。
    """

    def __init__(self, command: List[str], env: Dict[str, str], budget: float,
                 handshake_budget: Optional[float] = None, on_spawn=None):
        self.command, self.env = command, env
        self.budget = budget
        self.handshake_budget = handshake_budget if handshake_budget is not None else budget
        self._on_spawn = on_spawn
        self._id = 0
        self._proc: Optional[subprocess.Popen] = None
        self._lines: Optional[queue.Queue] = None
        self._deadline = time.time() + budget
        self.stderr_tail = ''
        self.error = ''
        self._last_method = ''

    # ------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------

    def __enter__(self) -> 'McpSession':
        return self

    def __exit__(self, *exc_info) -> bool:
        self.close()
        return False

    def _spawn(self) -> subprocess.Popen:
        kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, env=self.env, text=True,
                      encoding='utf-8', bufsize=1)
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs['start_new_session'] = True      # 自成进程组，才能整组端掉
        return subprocess.Popen(self.command, **kwargs)

    def open(self) -> bool:
        """起进程并完成 initialize 握手；握手不过就整体判失败（不留下半死的会话）。"""
        try:
            self._proc = self._spawn()
        except OSError as exc:
            self.error = f'进程起不来：{exc}'
            return False
        if self._on_spawn:
            self._on_spawn()
        self._lines = queue.Queue()
        threading.Thread(target=self._pump_out, args=(self._proc.stdout,),
                         daemon=True).start()
        threading.Thread(target=self._pump_err, args=(self._proc.stderr,),
                         daemon=True).start()

        saved = self._deadline
        self._deadline = min(saved, time.time() + self.handshake_budget)
        self._last_method = 'initialize'
        resp = self.request('initialize', {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'deep-research-ultra', 'version': '4.0.0'},
        })
        self._deadline = saved
        if not resp or 'result' not in resp:
            self.error = self.error or '握手失败：initialize 没有返回 result'
            return False
        # initialized 是通知，按规范不该有响应——旧实现在这里等了一整个 CALL_TIMEOUT
        self.notify('notifications/initialized')
        return True

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if not proc:
            return
        if proc.poll() is None:
            _kill_tree(proc)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass

    # ------------------------------------------------------------
    # JSON-RPC
    # ------------------------------------------------------------

    def _pump_out(self, stream) -> None:
        try:
            for line in iter(stream.readline, ''):
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(_EOF)

    def _pump_err(self, stream) -> None:
        tail = ''
        try:
            for line in iter(stream.readline, ''):
                tail = (tail + line)[-4000:]
        except (OSError, ValueError):
            pass
        finally:
            self.stderr_tail = tail[-1500:]

    def _remaining(self) -> float:
        return max(0.0, self._deadline - time.time())

    def _write(self, payload: Dict) -> bool:
        if not self._proc or not self._proc.stdin:
            self.error = '会话已关闭'
            return False
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
            self._proc.stdin.flush()
            return True
        except (OSError, ValueError) as exc:
            self.error = f'写入失败：{exc}'
            return False

    def notify(self, method: str, params: Optional[Dict] = None) -> bool:
        payload: Dict[str, Any] = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            payload['params'] = params
        return self._write(payload)

    def request(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """发一条请求，在剩余预算内等它自己的响应；等不到就返回 None（绝不阻塞）。"""
        if self._proc is None or self._lines is None:
            self.error = '会话未打开'
            return None
        self._last_method = method
        self._id += 1
        rid = self._id
        payload: Dict[str, Any] = {'jsonrpc': '2.0', 'id': rid, 'method': method}
        if params is not None:
            payload['params'] = params
        if not self._write(payload):
            return None
        while True:
            left = self._remaining()
            if left <= 0:
                self.error = (f'超时：整场会话 {self.budget:g}s 预算内没等到 '
                              f'{method} 的响应')
                return None
            try:
                line = self._lines.get(timeout=min(left, 0.5))
            except queue.Empty:
                if self._proc.poll() is not None:
                    self.error = (f'server 进程已退出（code={self._proc.returncode}）'
                                  + (f'；stderr: {self.stderr_tail.strip()[-300:]}'
                                     if self.stderr_tail.strip() else ''))
                    return None
                continue
            if line is _EOF:
                self.error = 'server 关闭了输出（可能启动即失败）' \
                    + (f'；stderr: {self.stderr_tail.strip()[-300:]}'
                       if self.stderr_tail.strip() else '')
                return None
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resp.get('id') == rid:
                if 'error' in resp:
                    err = resp['error']
                    self.error = f"server 报错：{err.get('message', err)}"
                return resp


# ============================================================
# MCP 客户端
# ============================================================

def _rpc_error_text(err: Any) -> str:
    """JSON-RPC 层报错（-32603 之类）→ 一行可读原因。"""
    if isinstance(err, dict):
        msg = str(err.get('message') or err.get('error') or '').strip()
        code = err.get('code')
        return f'{msg} (code {code})' if msg else f'JSON-RPC 错误 code {code}'
    return str(err or 'JSON-RPC 错误').strip()


def _first_text(result: Any) -> str:
    """取工具响应里第一段 text（MCP 的 content[].text）。"""
    if not isinstance(result, dict):
        return ''
    parts = result.get('content')
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and str(part.get('text') or '').strip():
                return str(part['text']).strip()
    return ''


def _error_detail(text: str) -> str:
    """server 把原因写成 JSON（{"status":"error","message":...}）时取 message，否则取首行。"""
    text = (text or '').strip()
    if not text:
        return '工具返回错误但没给原因'
    try:
        parsed = json.loads(text)
    except Exception:
        return text.splitlines()[0][:200]
    if isinstance(parsed, dict):
        for key in ('message', 'error', 'detail'):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:200]
    return text.splitlines()[0][:200]


def _tool_error_text(result: Any) -> str:
    """工具自己报的错（isError 或 {"status":"error"}）→ 原因；没报错返回 ''。

    实测两种上游错误都长这样（arXiv 限流时 arxiv / paper-search 两个 server 的原样响应）：
      {"content":[{"text":"{\\"status\\": \\"error\\", \\"message\\":
        \\"arXiv API HTTP error (HTTP 406)\\"}"}], "isError": true}
    以前不看 isError，直接把这段错误文本塞进解析器，条目一条也没有，
    自检于是报"可调通但 0 结果"——把端点故障说成了"这个主题没资料"。
    """
    if not isinstance(result, dict):
        return ''
    text = _first_text(result)
    if result.get('isError'):
        return _error_detail(text)
    try:
        parsed = json.loads(text)
    except Exception:
        return ''
    if isinstance(parsed, dict) and str(parsed.get('status', '')).strip().lower() == 'error':
        return _error_detail(text)
    return ''


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
        self.spawn_count = 0        # 本次进程内拉起过多少个 server 进程（探针据此判"会话没分裂"）
        self.last_error = ''        # 最近一次失败的具体原因，供 --probe 说得出"为什么不可用"

    def _count_spawn(self) -> None:
        self.spawn_count += 1

    def open_session(self, budget: Optional[float] = None) -> Optional['McpSession']:
        """起一个已完成握手的会话；调用方负责 close()（用 `with` 即可）。"""
        command = self.get_command()
        if not command:
            self.last_error = (f"未配置 MCP server '{self.server_name}'"
                               '（配置文件里没有，或缺 command）'
                               f'；查过：{describe_mcp_config_search()}')
            return None
        session = McpSession(command, self.get_env(),
                             budget or self.CALL_TIMEOUT,
                             handshake_budget=min(self.INIT_TIMEOUT, budget or self.CALL_TIMEOUT),
                             on_spawn=self._count_spawn)
        if not session.open():
            self.last_error = f"{self.server_name}: {session.error}"
            session.close()
            return None
        self.last_error = ''
        return session

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
    # 工具调用接口
    # ------------------------------------------------------------

    def list_tools(self, refresh: bool = False,
                   timeout: Optional[float] = None) -> List[Dict]:
        """
        列出 MCP 服务器提供的工具

        Args:
            refresh: 是否刷新缓存

        Returns:
            工具列表，每个工具包含 name, description, inputSchema
        """
        if self._cached_tools is not None and not refresh:
            return self._cached_tools

        session = self.open_session(timeout)
        if session is None:
            return []
        try:
            response = session.request('tools/list', {})
        finally:
            session.close()
        if not response or 'result' not in response:
            self.last_error = f"{self.server_name}: tools/list 无结果" \
                f"（{session.error}）"
            return []
        tools = response['result'].get('tools', [])
        self._cached_tools = tools
        return tools

    def call_tool(self, tool_name: str, arguments: Optional[Dict] = None,
                  timeout: Optional[float] = None) -> Optional[Dict]:
        """
        调用 MCP 工具

        握手与工具调用走同一个会话进程，整体受 `timeout` 的墙钟预算约束。

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            timeout: 整场会话预算（秒）

        Returns:
            工具调用结果，失败返回 None
        """
        session = self.open_session(timeout)
        if session is None:
            return None
        try:
            response = session.request('tools/call', {
                'name': tool_name,
                'arguments': arguments or {},
            })
            error = session.error
        finally:
            session.close()
        if not response:
            self.last_error = f"{self.server_name}: {error or 'tools/call 无响应'}"
            return None
        if 'error' in response:
            self.last_error = f"{self.server_name}: {_rpc_error_text(response['error'])}"
            return None
        result = response.get('result')
        reason = _tool_error_text(result)
        if reason:
            # 工具自己报错＝这个源此刻取不到数据。报成"0 结果"会诱导 Lead 去改查询词，
            # 而真正该做的是等上游限流过去或换通道。
            self.last_error = f"{self.server_name}: {reason}"
            return None
        self.last_error = ''
        return result

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
