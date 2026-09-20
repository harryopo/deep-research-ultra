"""计划 A 探针：本地 Python 能否作为 stdio MCP server 被真握手。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills' / 'deep-research-ultra' / 'scripts'))

from engines.mcp_client import McpSession  # noqa: E402


def _session(budget: float = 25.0) -> McpSession:
    # env 用「继承进程环境」而不是 {}：本仓库对 McpSession 的唯一生产用法
    # （scripts/engines/mcp_client.py:384 get_env）就是 os.environ.copy() + 配置项。
    # 实测传 {} 时 Windows 子进程连 `import asyncio` 都过不去
    # （_overlapped → OSError [WinError 10106] WSAStartup 起不来），
    # 那是 fixture 不真实，不是握手失败——不能让探针替操作系统背锅。
    # 只摘 PYTHON* 键：PYTHONPATH 会决定子进程 import 哪个 mcp，
    # 路径上随便一个 mcp.py/mcp/ 就能把本测试测的东西换掉。SYSTEMROOT/PATH 必须留着。
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    return McpSession([sys.executable, str(ROOT / 'server.py')], env, budget)


def test_server_hands_shake_and_lists_drux_ping():
    with _session() as s:
        assert s.open(), f'stdio 握手失败：{getattr(s, "error", "未知原因")}'
        listed = s.request('tools/list')
        assert listed, f'tools/list 无响应：{getattr(s, "error", "")}'
        # JSON-RPC 的 error 信封在 mcp_client 里照样是真值，只判「非空」的话
        # 这条断言会放它过去，让失败落到 names 上、信息指不到真正的原因。
        err = listed.get('error')
        assert not err, f'tools/list 返回 JSON-RPC error：{err} / {getattr(s, "error", "")}'
        # `or []`：server 若回 "tools": null，.get('tools', []) 给的是 None 而不是 []，
        # 推导式会抛 TypeError 并把上面攒下的 error 上下文一起弄丢。
        tools = (listed.get('result') or {}).get('tools') or []
        names = [t.get('name') for t in tools]
        assert 'drux_ping' in names, f'探针工具未注册：{names} / {getattr(s, "error", "")}'


def test_cjk_argument_round_trips():
    probe = '边缘推理·调研 2026 年—含全角？'
    with _session() as s:
        assert s.open(), f'stdio 握手失败：{getattr(s, "error", "未知原因")}'
        got = s.request('tools/call', {'name': 'drux_ping', 'arguments': {'text': probe}})
        assert got, f'tools/call 无响应：{getattr(s, "error", "")}'
        err = got.get('error')
        assert not err, f'tools/call 返回 JSON-RPC error：{err} / {getattr(s, "error", "")}'
        payload = got.get('result') or {}
        text = (payload.get('content') or [{}])[0].get('text') or ''
        # isError 是 MCP 的**工具执行层**状态，与上面的 JSON-RPC error 信封是两条正交通道：
        # 后者管协议，前者管工具自己失败。工具内部报错却把入参回显出来时
        # （mcp 2.1.1：ToolError → content=[text=str(exc)]、isError=True），
        # 只有本行能拦住这种「看起来成功的失败」——它不许靠下一条 in 断言蒙过去。
        assert not payload.get('isError'), f'工具层执行失败：收到 {text!r} / {getattr(s, "error", "")}'
        # 空 text 不是编码坏了，label 按 text 分流，别给「工具没返回内容」扣上损坏的帽子。
        damaged = '工具无返回内容' if text == '' else '中文往返损坏'
        assert probe in text, f'{damaged}：收到 {text!r} / {getattr(s, "error", "")}'


import json


def test_plugin_shell_files_exist():
    for rel in ('.qoder-plugin/plugin.json', 'mcp.json', 'hooks/hooks.json'):
        assert (ROOT / rel).exists(), f'缺 {rel}'
    manifest = json.loads((ROOT / '.qoder-plugin' / 'plugin.json').read_text(encoding='utf-8'))
    assert manifest['name'] == 'deep-research-ultra'
    assert manifest['version'].startswith('7.')
    declared = json.loads((ROOT / 'mcp.json').read_text(encoding='utf-8'))
    assert 'deep-research-ultra' in declared['mcpServers']
    cfg = declared['mcpServers']['deep-research-ultra']
    # env 一旦出现就可能被宿主当成「完整替换」子进程环境：没有 SYSTEMROOT 时
    # server.py 会死在 import _overlapped（WinError 10106 Winsock 起不来），
    # 那副长相和「stdio 握手根本不可能」一模一样，会误杀整个插件方案。
    assert 'env' not in cfg, 'mcp.json 加了 env：宿主按完整替换处理会丢 SYSTEMROOT → WinError 10106'
    # args[0] 必须走插件根变量：裸 server.py 由宿主 cwd 决定，装到别处就找不到。
    assert cfg['args'][0].startswith('${QODER_PLUGIN_ROOT}'), \
        'mcp.json 的脚本路径退回相对/cwd 解析：换安装位置或宿主 cwd 就找不到 server.py'
    assert (ROOT / 'skills' / 'deep-research-ultra' / 'SKILL.md').exists(), 'skill 未下沉'
