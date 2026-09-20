# 插件壳与连通性（计划 A）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用最小代价证明「Qoder 插件能带一个本地 Python MCP server + Stop hook 并真被宿主调用」；证明不了就按作废路径退回 CLI。

**Architecture:** 仓库从「skill 目录」升为「插件包」：插件根放 `server.py` / `mcp.json` / `hooks/`，现有 skill 整体下沉到 `skills/deep-research-ultra/`。本计划只做壳与连通性，不做四个业务工具（那在计划 B）。

**Tech Stack:** Python 3.10+、`mcp` 包（stdio server 侧）、仓库自带 `scripts/engines/mcp_client.py`（stdio 客户端侧，用于真握手）、pytest。

**Spec:** `docs/specs/2026-09-20-drux-plugin-mcp-design.md`（本计划实现它的第二、四、十三节；§2 的未验证项 U1–U4 由本计划变成事实）

## Global Constraints

- 只加一个新依赖：Python `mcp` 包。除此之外不引第三方库。
- 支持 Windows 为主战场：控制台 GBK、路径含空格（`D:\ai\claude code\...`）、中文目录名。
- 失败必须像失败：任何探针/工具不得返回"看起来成功的空结果"（spec §9）。
- 两份工作副本同步：全局安装位 `C:\Users\Administrator\.agents\skills\deep-research-ultra`（CRLF，git 上游 = harryopo/deep-research-ultra，分支 `main`）与工作台 `D:\ai\claude code\skill开发\projects\deep-research-ultra`（LF，交付分支 `skill-dev-workbench`，只推 `HEAD:skill-dev-workbench`）。禁止 force push、禁止合并无关历史。
- 未实测不得称完成：每个 Step 的验证命令必须真跑并贴输出。
- 计划 A 的验收只有一条：**宿主侧 `tools/list` 拿得到 `drux_ping`，中文入参往返不乱码**。

## 文件结构（本计划建立）

| 路径 | 责任 | 动作 |
|------|------|------|
| `server.py` | MCP stdio server 入口，仅声明探针工具 | 新建 |
| `tests/test_plugin_shell.py` | 插件壳层测试（直连 stdio 握手 + 编码往返） | 新建 |
| `mcp.json` | 向宿主声明 stdio server | 新建 |
| `.qoder-plugin/plugin.json` | 插件清单 | 新建 |
| `hooks/hooks.json` / `hooks/probe_log.py` | 证明宿主真会调 hook（只写日志，不拦任何东西） | 新建 |
| `docs/plans/evidence-mcp-path.md` | 记录路径变量取证结论（U2） | 新建 |
| `skills/deep-research-ultra/**` | 现有 skill 全部文件下沉一层 | 移动 |

---

### Task 1: 取证——mcp.json 里的命令路径怎么写（U2）

**Files:**
- Create: `docs/plans/evidence-mcp-path.md`
- Read: `C:\Users\Administrator\.qoder\plugins\cache\qoder-marketplace\*\mcp.json`

**Interfaces:**
- Consumes: 无
- Produces: 一个确定结论，供 Task 4 写 `mcp.json` 用。三种取值之一：`relative`（命令相对插件根）/ `var`（用某变量名，变量名写死在结论里）/ `absolute-only`（必须在安装时生成绝对路径）

- [ ] **Step 1: 抓全部既有用法作证据**

Run:

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache/qoder-marketplace"
grep -rn --include="mcp.json" --include=".mcp.json" -e '"command"' -e 'PLUGIN' -e '\${' . | head -40
grep -rn --include="hooks.json" -e '"command"' . | head -20
```

把输出原样贴进 `docs/plans/evidence-mcp-path.md`（标题「证据」段）。

- [ ] **Step 2: 判定并写结论**

在 `docs/plans/evidence-mcp-path.md` 写「结论」段，必须逐条回答：

1. 有没有插件的 `command` 指向插件内部文件？若有，它用的是相对路径还是 `${...}` 变量？把那一行原文抄进来。
2. `hooks.json` 的 `command` 已确证相对插件根（quality-guardian 用 `node hooks/check-ui-anti-patterns.js`）——`mcp.json` 是否同样支持？没有直接证据就写"无证据，按 var 方案兜底"。
3. 最终选定值写成一行：`DECISION: relative | ${PLUGIN_ROOT} | absolute-only`，并附证据行号。

- [ ] **Step 3: 提交**

```bash
cd "C:/Users/Administrator/.agents/skills/deep-research-ultra"
git add docs/plans/evidence-mcp-path.md
git commit -m "docs(plan-A): 取证 mcp.json 命令路径写法（U2）"
```

---

### Task 2: server.py 骨架 + 真 stdio 握手（U1，不依赖宿主）

**Files:**
- Create: `server.py`
- Create: `tests/test_plugin_shell.py`
- Read: `scripts/engines/mcp_client.py:116-306`（`McpSession`）

**Interfaces:**
- Consumes: `McpSession(command: List[str], env: Dict[str,str], budget: float, ...)`，方法 `open() -> bool`、`request(method, params) -> Optional[Dict]`、`close()`，可用作上下文管理器
- Produces: `server.py` 提供 `build_server()`（返回已注册工具的对象）与 `main()`（stdio 循环）；协议上 `tools/list` 至少含 `drux_ping`

- [ ] **Step 1: 先确认 McpSession 是否自带 initialize 握手**

Run: `cd "C:/Users/Administrator/.agents/skills/deep-research-ultra/scripts" && sed -n '164,200p' engines/mcp_client.py`

记下 `open()` 是否发 `initialize` + `notifications/initialized`。若没发，Step 3 的测试里要先手动 `session.request("initialize", {...})` 再 `session.notify("notifications/initialized")`——两种写法都写在 Step 3 里，按事实二选一。

- [ ] **Step 2: 写失败测试**

Create `tests/test_plugin_shell.py`:

```python
"""计划 A 探针：本地 Python 能否作为 stdio MCP server 被真握手。"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from engines.mcp_client import McpSession  # noqa: E402


def _session(budget: float = 25.0) -> McpSession:
    return McpSession([sys.executable, str(ROOT / 'server.py')], {}, budget)


def test_server_hands_shake_and_lists_drux_ping():
    with _session() as s:
        assert s.open(), f'stdio 握手失败：{getattr(s, "error", "未知原因")}'
        listed = s.request('tools/list')
        assert listed, f'tools/list 无响应：{getattr(s, "error", "")}'
        names = [t.get('name') for t in (listed.get('result') or {}).get('tools', [])]
        assert 'drux_ping' in names, f'探针工具未注册：{names} / {getattr(s, "error", "")}'
```

`request()` 返回的是原始 JSON-RPC 信封（`scripts/engines/mcp_client.py:300` 直接 `return resp`），
所以取 `result` 才对；把 `s.error` 拼进断言消息，失败时看得见真因。

- [ ] **Step 3: 跑测试看它失败**

Run: `cd "C:/Users/Administrator/.agents/skills/deep-research-ultra" && python -m pytest tests/test_plugin_shell.py -q`
Expected: FAIL —`ModuleNotFoundError: No module named 'engines.mcp_client'` 之前先遇到 `server.py` 不存在（`open()` 返回 False）。若失败原因是 import 路径，则修正 `sys.path` 注入行而不是改断言。

- [ ] **Step 4: 写最小 server**

Create `server.py`:

```python
"""deep-research-ultra 插件的 MCP server（计划 A：只放连通性探针）。

计划 B 会把 drux_ping 换成四个业务工具；本文件其余部分不动。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))


def build_server():
    from mcp.server.fastmcp import FastMCP
    srv = FastMCP('deep-research-ultra')

    @srv.tool()
    def drux_ping(text: str) -> str:
        """连通性探针：原样返回入参（含中文）。计划 B 会删除本工具。"""
        return text

    return srv


def main() -> int:
    try:
        build_server().run()
    except ImportError as exc:  # 缺依赖必须显式失败，不许静默
        print(f'drux-mcp 需要 python mcp 包：pip install mcp（{exc}）', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

同时在 `requirements.txt`（Task 4 后位于 `skills/deep-research-ultra/requirements.txt`）加一行 `mcp>=1.2`。
下限必须按本机 `python -c "import mcp; print(getattr(mcp,'__version__','unknown'))"` 的实测值写，
不要抄这里的 1.2——写高了公开用户装不上，写低了拿不到 FastMCP。

若 Step 1 发现 `open()` 不发 initialize，则在此文件里不需要任何改动——改的是测试；两边都跑不通时先确认 `mcp` 包提供的入口是 `mcp.server.fastmcp.FastMCP`（`python -c "import mcp.server.fastmcp as m; print(m.FastMCP)"`），不存在则退回 `mcp.server.Server`，并在 commit message 里记下实际入口名。

- [ ] **Step 5: 跑测试看它通过**

Run: `cd "C:/Users/Administrator/.agents/skills/deep-research-ultra" && python -m pytest tests/test_plugin_shell.py -q`
Expected: PASS（1 passed）。失败即 U1 不成立 → 跳到本计划末尾「失败出口」。

- [ ] **Step 6: 提交**

```bash
git add server.py tests/test_plugin_shell.py
git commit -m "feat(plugin): server.py 骨架，stdio 握手可取 tools/list"
```

---

### Task 3: 中文入参往返（编码这一关单独证，U1b）

**Files:**
- Modify: `tests/test_plugin_shell.py`
- Test: `tests/test_plugin_shell.py`

**Interfaces:**
- Consumes: Task 2 的 `drux_ping`
- Produces: 一条已证明的约定——**经 stdio 往返 UTF-8 中文不损坏**，计划 B 的所有工具据此设计入参

- [ ] **Step 1: 加失败测试**

Append to `tests/test_plugin_shell.py`:

```python
def test_cjk_argument_round_trips():
    probe = '边缘推理·调研 2026 年—含全角？'
    with _session() as s:
        assert s.open()
        got = s.request('tools/call', {'name': 'drux_ping', 'arguments': {'text': probe}})
        assert got, 'tools/call 无响应'
        payload = (got.get('result') or {})
        text = payload.get('content', [{}])[0].get('text', '')
        assert probe in text, f'中文往返损坏：{text!r} / {getattr(s, "error", "")}'
```

- [ ] **Step 2: 跑测试看它失败或通过**

Run: `cd "C:/Users/Administrator/.agents/skills/deep-research-ultra" && python -m pytest tests/test_plugin_shell.py::test_cjk_argument_round_trips -q`
Expected: 首轮可能 FAIL（响应结构不是 `content[0].text`，或 GBK 环境把 stdout 编码改坏）。按实际输出定：结构问题改测试断言（先 `print(got)` 看真实结构，再据实写断言）；编码问题在 `server.py` 的 `main()` 里加 `from console import force_utf8; force_utf8()` 后复跑。**不许为了让测试变绿而放宽断言内容本身。**

- [ ] **Step 3: 跑测试看它通过**

Run: `python -m pytest tests/test_plugin_shell.py -q`
Expected: 2 passed

- [ ] **Step 4: 提交**

```bash
git add server.py tests/test_plugin_shell.py
git commit -m "test(plugin): 证明 UTF-8 中文入参经 stdio 往返不损坏"
```

---

### Task 4: 插件壳三件套 + skill 目录下沉

**Files:**
- Create: `.qoder-plugin/plugin.json`, `mcp.json`, `hooks/hooks.json`, `hooks/probe_log.py`
- Move: `SKILL.md` `scripts/` `references/` `evals/` → `skills/deep-research-ultra/`
- Modify: `tests/test_plugin_shell.py:10`（ROOT 下的 scripts 路径）
- Test: `tests/test_plugin_shell.py`

**Interfaces:**
- Consumes: Task 1 的 `DECISION`
- Produces: 一个可被宿主识别的插件目录；`server.py` 仍在插件根（不受下沉影响）

- [ ] **Step 1: 先加一条壳完整性测试（失败）**

Append to `tests/test_plugin_shell.py`:

```python
import json


def test_plugin_shell_files_exist():
    for rel in ('.qoder-plugin/plugin.json', 'mcp.json', 'hooks/hooks.json'):
        assert (ROOT / rel).exists(), f'缺 {rel}'
    manifest = json.loads((ROOT / '.qoder-plugin' / 'plugin.json').read_text(encoding='utf-8'))
    assert manifest['name'] == 'deep-research-ultra'
    assert manifest['version'].startswith('7.')
    declared = json.loads((ROOT / 'mcp.json').read_text(encoding='utf-8'))
    assert 'deep-research-ultra' in declared['mcpServers']
    assert (ROOT / 'skills' / 'deep-research-ultra' / 'SKILL.md').exists(), 'skill 未下沉'
```

Run: `python -m pytest tests/test_plugin_shell.py::test_plugin_shell_files_exist -q`
Expected: FAIL —缺 `.qoder-plugin/plugin.json`

- [ ] **Step 2: 下沉目录（一次做完，别分步）**

```bash
cd "C:/Users/Administrator/.agents/skills/deep-research-ultra"
mkdir -p skills/deep-research-ultra
git mv SKILL.md scripts references evals requirements.txt skills/deep-research-ultra/
```

Note: `README.md` / `CHANGELOG.md` / `index.html` / `docs/` 留在插件根（面向人，不属于 skill 运行时）。

- [ ] **Step 3: 修路径引用**

Modify `tests/test_plugin_shell.py`：`sys.path.insert(0, str(ROOT / 'scripts'))` → `str(ROOT / 'skills' / 'deep-research-ultra' / 'scripts')`；`server.py` 里 `Path(__file__).parent / 'scripts'` 同样改为下沉后的路径。
Run: `python -m pytest tests/test_plugin_shell.py -q` → Expected: 前两条 PASS，`test_plugin_shell_files_exist` 仍 FAIL（还没写壳文件）。

- [ ] **Step 4: 跑全量回归（下沉最容易碰坏的就是它）**

Run: `cd skills/deep-research-ultra/scripts && python -m pytest tests/ -q`
Expected: `315 passed`。任何 collect error 都是路径/相对导入被移动破坏，改导入而不是删测试。

- [ ] **Step 5: 写三份壳文件**

Create `.qoder-plugin/plugin.json`:

```json
{
  "name": "deep-research-ultra",
  "displayName": "超级深度调研",
  "version": "7.0.0",
  "description": "Deep research with evidence ledger, real-source probe and an anti-forgery gate enforced by MCP + Stop hook.",
  "descriptionZh": "超级深度调研：证据账本可溯源、引擎真实自检、防伪校验戳由 MCP 与 Stop hook 强制执行。",
  "author": { "name": "harryopo" },
  "keywords": ["research", "mcp", "evidence", "deep-research"],
  "category": "developer-tools",
  "tags": ["skill", "mcp", "hooks"]
}
```

Create `hooks/hooks.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "python hooks/probe_log.py", "timeout": 10 }
        ]
      }
    ]
  }
}
```

Create `hooks/probe_log.py`（只记日志，**一期不拦任何东西**）:

```python
"""计划 A 的 hook 探针：证明宿主真会调 Stop hook。计划 B 换成 gate_hook.py 做验戳。"""
import datetime
import json
import sys
from pathlib import Path


def main() -> int:
    payload = sys.stdin.read()
    target = Path(__file__).resolve().parent / '.drux-hook-stop.log'
    with target.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps({'at': datetime.datetime.now().isoformat(),
                             'bytes': len(payload)}, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

日志写在 `hooks/` 里而不是插件根，避免污染仓库根；`.gitignore` 增加一行 `hooks/.drux-hook-stop.log`。

Create `mcp.json`（按 Task 1 的 DECISION 三选其一）：

- `relative`：`{"mcpServers": {"deep-research-ultra": {"type": "stdio", "command": "python", "args": ["server.py"]}}}`
- `var`：同上但 `"args": ["${PLUGIN_ROOT}/server.py"]`，变量名取 Task 1 抄到的原文
- `absolute-only`：新建 `mcp.json` 时用真实绝对路径直接写死本机路径，并同时建 `mcp.json.example` 存档模板：

```json
{
  "mcpServers": {
    "deep-research-ultra": {
      "type": "stdio",
      "command": "python",
      "args": ["C:/Users/Administrator/.agents/skills/deep-research-ultra/server.py"]
    }
  }
}
```

  并在 `docs/plans/evidence-mcp-path.md` 记一句后果：换机器/换安装路径需重跑安装步骤生成 `mcp.json`；
  同时在 README 安装节写明"这一步会生成含绝对路径的 mcp.json，故不入库"（届时把 `mcp.json` 加进 `.gitignore`，只保留 `mcp.json.example`）。

- [ ] **Step 6: 壳测试转绿**

Run: `python -m pytest tests/test_plugin_shell.py -q`
Expected: 3 passed

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat(plugin): 插件壳三件套 + skill 下沉到 skills/deep-research-ultra"
```

---

### Task 5: 宿主侧真装真验（U3 + U1 的最终判定）

**Files:**
- Create: `docs/plans/plan-a-verification.md`

**Interfaces:**
- Consumes: Task 4 的插件目录、Task 2-3 的 server
- Produces: U3（本地插件可否安装）、hook 是否真被调、宿主 `tools/list` 是否可见 三项事实

- [ ] **Step 1: 请用户把插件装进宿主并重启一次会话**

给用户这条指令（按本机 Qoder 插件目录实际情况二选一，先跑 `ls "C:/Users/Administrator/.qoder/plugins"` 确认布局再给）：
把 `C:\Users\Administrator\.agents\skills\deep-research-ultra` 以本地插件方式安装/链接进插件目录，然后重启 Qoder CLI。
（此步必须用户做一次动作——记录到 plan-a-verification.md 里，注明"人工步骤"。）

- [ ] **Step 2: 在宿主里验 tools 可见**

重启后由我调用 `mcp_list({keyword: "drux"})`。
Expected: 出现 `mcp__<plugin>__drux_ping` 之类条目。看不到 → U3 不成立，走失败出口。

- [ ] **Step 3: 验中文往返走宿主通道**

`mcp_call` 调 `drux_ping`，参数 `{"text": "边缘推理·调研 2026 年—含全角？"}`。
Expected: 返回含同一串中文。

- [ ] **Step 4: 验 hook 真被调**

Run: `cat "C:/Users/Administrator/.agents/skills/deep-research-ultra/hooks/.drux-hook-stop.log"`
Expected: 至少一行 `{"at": ..., "bytes": N}`。没有 → hook 未生效，把 Stop 事件名/路径写法作为待查项记下来，不要靠猜改。

- [ ] **Step 5: 写验证结论**

`docs/plans/plan-a-verification.md` 逐条写 U1/U2/U3/U4 + 本次三个实测证据（命令与输出原文）。把结论同步回 spec 第二节表格，把"尚未验证"改成"已验证：<结果>（日期）"。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "docs(plan-A): 宿主侧连通性实测结论（U1-U4 转事实）"
git push origin main
```

---

### Task 6: 文档与迁移说明

**Files:**
- Modify: `README.md`, `SKILL.md`（已下沉后的路径）, `CHANGELOG.md`

- [ ] **Step 1: README 安装章节重写**

把"clone 到 skills 目录"改为"安装插件"两步，并明确写：`v7 起必需插件；装不上时 skill 会硬停并打印本指引`。加一行未验证平台声明：macOS/Linux 路径未实测。

- [ ] **Step 2: SKILL.md 顶部加迁移提示**

在标题下加一段（≤5 行）：v7.0.0 起本 skill 以插件形式分发，`${SKILL_DIR}` 现为 `<插件根>/skills/deep-research-ultra`，旧手工安装法失效，指向 README。

- [ ] **Step 3: CHANGELOG 记 v7.0.0-alpha 条目**

写清：本步只完成壳与连通性，四个业务工具与强制 hook 在计划 B；附实测数据（握手耗时、hook 日志行数、冷启动秒数）。

- [ ] **Step 4: 全量回归 + 双副本同步**

```bash
cd skills/deep-research-ultra/scripts && python -m pytest tests/ -q          # 315 passed
cd ../.. && python -m pytest tests/ -q                                       # 3 passed
```
再按既有流程同步到工作台并两侧提交（禁 force push）。

---

## 失败出口（计划 A 任一环节证明不成立时）

触发条件：Task 2 握不上手 / Task 5 宿主看不见 tools / Task 5 hook 不触发。

处置（按 spec §13）：

```bash
cd "C:/Users/Administrator/.agents/skills/deep-research-ultra"
git stash push -u -m "plan-A-failed 2026-09-20"     # 先存，不丢工作
git log --oneline -8                                 # 找到下沉前的最后一个提交
git revert --no-commit <Task4 的壳提交> <Task2 的 server 提交>
git commit -m "revert: 插件化方案作废（原因：<实测结论>），退回 CLI-only"
```

然后在 `CHANGELOG.md` 写明失败现象、复现命令、结论"形态限制，非实现不足"，并把 spec 第二节对应项标为「已验证为不支持」。**不重试第三种方案**，交回用户决定。
