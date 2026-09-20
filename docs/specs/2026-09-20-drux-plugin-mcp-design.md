# deep-research-ultra 插件化设计（MCP + Hook 双层强制）

日期：2026-09-20　状态：待用户审阅　目标版本：v7.0.0（破坏性变更）

## 一、为什么做这个改动

v6.7.0 的一次真实运行（effort=deep、4 session、25 子 Agent）暴露了 16 条缺陷。逐条对代码复核后，
问题分成两类：

- **开发方式造成的**（约 10 条）：噪声灌进账本、文档里的命令签名写错、status 输出机器读不出、
  下载的 PDF 被换成无关文档却没报错。这些已在 v6.10–v6.14 逐条修完，与形态无关。
- **形态造成的**（4 条）：skill 是"给 LLM 读的说明书 + 一堆脚本"，每一步都要 Agent 自愿去跑。
  于是——它可以跳过校验门自称 passed；子 Agent 的运行环境与 Lead 不同却共用一张引擎清单；
  宿主内置源在 Python 子进程里永远返回 0 却仍被推荐；跨进程的引擎掉线无人共享。

第二类修不动，因为不是代码错，是**没有强制点**。本设计的目的就是造强制点。

## 二、已验证的事实（后续实现不得凭印象推翻）

在本机 `C:\Users\Administrator\.qoder` 实测：

1. 插件可自带 MCP server：插件根放 `mcp.json`，格式
   `{"mcpServers": {"<name>": {"type": "stdio", "command": "npx", "args": [...]}}}`。
   证据：`chrome-devtools-mcp/1.9.0/mcp.json`（含 `${PLUGIN_DATA}` 变量）、`playwright/1.0.0/mcp.json`。
2. Hook 由插件提供：`<plugin>/hooks/hooks.json`，事件含 `PreToolUse`、`Stop`；
   `command` 相对插件根解析。证据：`quality-guardian/1.0.0/hooks/hooks.json`、
   `superpowers/6.3.0/hooks/hooks.json`。
3. 插件清单：`.qoder-plugin/plugin.json`，字段含 name / displayName / version / description /
   descriptionZh / author / logo / keywords / category / tags。
4. 一个插件可同时携带 `skills/`、`hooks/`、`mcp.json`、`scripts/`、`commands/`、`agents/`。
5. `~/.qoder/settings.json` 的 `mcpServers` 目前只有 `type: http` 条目（走 mcp.qoder.com），
   且**没有 `hooks` 键**。因此"改 settings.json 装 stdio server 与 hook"这条路未经证实，本设计不采用。
6. Python `mcp` 包在本机可 import；`python`、`node`、`npx`、`uvx` 均在 PATH。

**尚未验证（实现期第一件事就是验，不许猜）**：

- 插件内 MCP server 的命令行路径变量确切名称（`${PLUGIN_ROOT}` 还是别的；`mcp.json` 里已确证 `${PLUGIN_DATA}`）。
- `python`（而非 npx）作为 `command` 能否正常拉起 stdio server。
- 未上架的本地插件目录能否直接安装（决定 README 怎么写）。

## 三、已确认的产品决策

| 决策 | 选择 | 含义 |
|------|------|------|
| 验收标准分期 | 一期强制点 → 二期跨子 Agent 共享状态 → 三期 host-only 判定 | 一期不承诺解决 D1/D2/D3 |
| 强制实现方式 | MCP + Hook 双层 | 只有 MCP 会被绕过；只有 Hook 没有正规入口，反而逼出绕路 |
| 未安装者策略 | **必需**：装不上就硬停并给指引，不许静默降级 | v7.0.0 破坏性变更 |
| 实现语言 | 全 Python，复用 `scripts/` 现有模块 | 不引新依赖、不发 PyPI、冷启动不联网 |
| Hook 拦截面 | 只拦"交付声明"，不拦写文件动作 | 造假造的是声明，不是文件 |

> 措辞修正：上表"不引新依赖"不准确。MCP server 需要 Python `mcp` 包——这是一项**新增运行时依赖**，
> 本机已装但公开用户未必。因此 `requirements.txt` 必须加 `mcp`，`drux_session_start` 前置检查
> `python -c "import mcp"`，缺失时按既有风格报"缺什么 / 怎么装 / 怎么验"，不静默降级。

## 四、目标形态：仓库从「skill 目录」变成「插件包」

```
deep-research-ultra/                 ← 插件根
├── .qoder-plugin/plugin.json        ← 新增：插件清单
├── mcp.json                         ← 新增：声明 stdio MCP server
├── hooks/hooks.json                 ← 新增：Stop 事件挂交付验戳
├── server.py                        ← 新增：MCP server（thin，只做参数校验与编排）
├── gate_hook.py                     ← 新增：hook 可执行脚本（只读、轻量）
├── skills/deep-research-ultra/      ← 现有 skill 整体下沉一层
│   ├── SKILL.md
│   ├── scripts/                     （ledger.py / validate_report.py / probe.py / ...）
│   └── tests/
└── README.md / CHANGELOG.md / index.html
```

skill 内部所有既有路径引用（`${SKILL_DIR}`）保持不变——只是 `${SKILL_DIR}` 的值多了一层前缀。

**代价**：老用户"clone 仓库到 ~/.claude/skills/deep-research-ultra"的手工安装法失效，需改为装插件。
README 安装章节重写，SKILL.md 顶部加一句版本迁移提示。这是本设计判定值得付的价：
装一次插件，skill / MCP / hook 同时到位，"没装插件的用户"这个类别基本消失。

## 五、组件职责

| 单元 | 干什么 | 不干什么 |
|------|--------|----------|
| SKILL.md | 拆维度、编排、判断、写作指引 | 不再教 Agent 手跑 CLI |
| `server.py` | 唯一有写权限的内核：建 session、记账本、跑校验、盖戳 | 不做正文写作、不做检索 |
| `gate_hook.py` | 交付时验戳，不过就拦 | 不写文件、不 import scripts 大包、不执行报告内容 |
| `scripts/*.py` | 被 server import 的既有实现 | 不再是对外主入口（保留为降级与维护入口） |

进程模型：MCP server 每会话一进程，Lead 与其派生子 Agent 共用同一进程。
一期不利用这点，但**必须按"server 内可持有会话级状态"来写**，二期断路器直接受益。
（若实测发现子 Agent 另起进程，一期结论不变，二期方案改，记入风险。）

## 六、MCP 工具契约（一期四个）

统一约定：入参 JSON 化（长中文正文走参数，不走 argv，顺带消掉 Windows GBK 传参乱码）；
返回值恒含 `ok`；失败必带 `error` 与 `hint`，**绝不返回看起来成功的空结果**。

### `drux_session_start`
- 入参：`query`、`effort`、`dimensions[]`
- 行为：跑 Phase 0 环境闸门（复用 `probe.source_gate()`），通过后建 `.research/<session_id>/`
- 返回：`session_id`、`ledger_dir`、`usable_engines[]`、`warnings[]`
- 闸门不过：`ok:false`，`issues` 逐条给"缺什么 / 去哪配 / 怎么验"（取 `probe.CONFIG_GUIDE`）；**不建 session**

### `drux_claim_add`
- 入参：`session_id`、`text`、`topic`、`sources[{url,title,tier?}]`、`perspective?`、`confidence?`
- 行为：写 claim + 挂来源；tier 缺省按 `domain_tier()` 自动分级
- 返回：`claim_id`、`accepted`、`rejected_sources[{url,reason}]`
- 硬规则：不可溯源 URL（相对链接、空、非 http）拒收并给原因；**调用方自称 verified 一律忽略并回注 warning**
  （保持"verified 只能由交叉验证或一手反查赋予"的既有纪律）

### `drux_gate_check`
- 入参：`session_id`、`report_path`
- 行为：只读跑 `validate_report()`
- 返回：`passed`、`issues[]`、`warnings[]`、`stats`

### `drux_stamp_issue`
- 入参：`session_id`、`report_path`
- 行为：**内部先跑一遍 gate**；`passed` 为假时不产出戳，返回 issues
- 成功：写 v6.11 格式戳行（格式不变，旧报告仍可验）+ 写 `gate.json` 回执
- 返回：`ok`、`stamp_line`、`body_sha`、`ledger_sha`

## 七、数据与文件

`.research/<session>/` 沿用现有结构（`ledger.jsonl` / `evidence.jsonl` / `claims/` / `sources/`），
新增一个回执文件：

```json
{ "report_sha": "...", "ledger_sha": "...", "passed": true,
  "issues_hash": "...", "issued_at": "...", "skill_version": "7.0.0" }
```

同时 `drux_session_start` 建目录时写一个 `session.json`：

```json
{ "session_id": "...", "started_at": "...", "query": "...", "effort": "..." }
```

hook 靠 `session.json` 判断"哪次调研、什么时候开的"，不靠猜 mtime。

- 戳行格式**不变**：`<!-- drux:validated v=1 body=… ledger=… claims=N sources=N -->`
- 并发写：claim / source 走原子追加（现状即如此）；整文件重写类操作（`set_status`）只允许 Lead 经工具做，
  且写前检查 `ledger.lock` 是否存在——存在就直接失败并报"另一处正在改账本"，不排队不等死。

## 八、Hook 策略

事件：一期**只用 `Stop`**（已在其他插件中确证可用）。`SubagentStop` 不是一期承诺，
列入二期评估——它能让子 Agent 也拦，但先确认运行时支持再写，不凭文档想当然。

判定链——**四条全中才拦**：

1. 工作区 `.research/` 下存在 `session.json.started_at` 不早于本轮会话开始、且其目录下有 `report.md` 的调研会话；
2. 正文出现"校验 passed""已交付"，或出现 `drux:validated` 戳行；
3. 验戳失败：无戳 / 正文指纹不符 / 账本指纹不符 / 与 `gate.json` 不一致；
4. 报告首行没有 `DRAFT:` 草稿标记。

不拦：写文件这个动作本身、普通 md、没跑调研的会话、既没戳也没声称过了的报告
（后者按 Phase 6 规则要求它写"未过门：<issues>"）。

明确不假装能防的：Agent 去删插件、改 hooks.json、伪造 gate.json。那是宿主权限边界，
写进文档而不是吹说拦得住。`DRAFT:` 是给人看的逃生口，Agent 用它算"明示未交付"，可接受。

性能：hook 只做文件读 + sha256，预算 500ms。实测超预算则退化为"戳行存在 + gate.json 指纹匹配"，
退化条件与实测数据一并记进 CHANGELOG。

## 九、错误处理

- server 起不来 / 未装：`drux_session_start` 调不到 → Lead 硬停，打印装插件的确切命令，
  沿用 v6.8 的"不许静默降级"红线。
- 工具内部异常：返回 `{ok:false, error, hint}`。原则：**失败必须长得像失败**
  （源自 X-D10「下载被换成无关文档却静默成功」、X-D11「限流被写成无法核实」）。
- MCP 握手：沿用 v6.9 教训——整场墙钟预算、超时可中断、不留孤儿进程。
  本地 Python 冷启动目标 < 1s；实测不达标改走 `uvx` 并记档。

## 十、安全边界

- server 与 hook 不读、不写、不打印任何密钥；配置读取沿用现有 env 变量机制，错误信息不回显值。
- 安装只新增插件目录内容，不碰用户 `settings.json` 里其它 MCP 与插件配置。
- hook 不执行报告内容、不对报告文本做 eval；只做正则匹配与哈希。
- 路径一律绝对化处理，兼容带空格与中文的目录（本仓库工作目录即含空格）。

## 十一、测试

1. 单测（pytest，现有 315 项继续全绿）：直接 import `server.py` 里的工具函数，不起进程。
   覆盖：拒收不可溯源、自标 verified 被忽略、不过门拿不到戳、戳与正文/账本指纹绑定、gate.json 与戳一致。
2. 协议测试：用仓库内现成的 `scripts/engines/mcp_client.py` 真起 server，跑 `tools/list` +
   `tools/call` 全链路；含一条中文入参经 Windows 控制台往返不乱码。
3. hook 测试：把 `gate_hook.py` 当 CLI 测（stdin 喂 hook JSON，断言退出码与输出），
   三场景——真报告放行、假戳拦下、无声明不拦。
4. **端到端硬指标（一期验收门，不接受用单测替代）**：真跑一次 `effort=standard` 调研，要求
   四个工具全部被实际调用过、report.md 带有效戳、hook 未被绕过、`--verify-stamp` 输出 ✅。
   做不到即视为一期未完成。

## 十二、一期不做

跨子 Agent 断路器与引擎健康共享（二期）、host-only 源判定（三期）、把 `report.py` / `probe.py`
整体搬进 server、PyPI 发包、任何 UI 与市场页改动。

## 十三、实现拆成两份计划

一期范围对单份实现计划偏大，拆两步，各自可独立验证：

1. **计划 A｜插件壳与连通性**：目录下沉、`plugin.json`、`mcp.json`、`server.py` 骨架，
   验收标准只有一条——真握手拿到 `tools/list`（含中文入参往返）。这一步把第二节所有"未验证项"变成事实。
2. **计划 B｜四个工具 + hook + 端到端**：在 A 的确证结果上实现工具、`gate_hook.py`、测试与实跑。

A 失败（例如本地 python 起不了 stdio server）则整个插件化方案作废，回到"仅 CLI + 文档"，
并把失败原因写进 CHANGELOG，不硬撑。

## 十四、主要风险

| 风险 | 影响 | 处置 |
|------|------|------|
| Qoder 不支持本地未上架插件安装 | 用户装不上手 | 实现第一步先验证；不行则改为"仓库内提供插件目录 + 文档指引"，仍不改 settings.json |
| `python` 作为 stdio command 不被接受 | server 起不来 | 改 `uvx` 或 `node` 薄壳转调 python，先测后定 |
| 子 Agent 各起 server 进程 | 二期共享状态失效 | 一期不依赖；二期前实测确认 |
| 破坏性变更影响老用户 | 需重装、旧文档失效 | v7.0.0 + 迁移说明 + 保留 CLI 与维护入口 |
| hook 拖慢每一轮结束 | 使用者体感变差 | 500ms 预算 + 退化方案 + 实测数据公开 |
