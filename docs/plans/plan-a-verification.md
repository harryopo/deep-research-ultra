# 计划 A 验证记录：插件壳与 stdio 连通性

对应 spec `docs/specs/2026-09-20-drux-plugin-mcp-design.md` 第二节列出的未验证假设。
本文件的作用只有一个：把"我以为成立"变成"这台机器上实测过"。
判定日 2026-09-20，环境 Windows 10.0.26200 / x64，Python 3.13.5（`D:\Miniconda3`），`mcp` 2.1.1，分支 `plan-a/plugin-shell`。

## 结论一览

| 编号 | 假设 | 结论 | 依据 |
|---|---|---|---|
| **U1** | 本地 Python 能作为 stdio MCP server 被真握手 | ✅ **成立** | `tests/test_plugin_shell.py::test_server_hands_shake_and_lists_drux_ping` 通过；实现者与评审者各自独立起进程复跑，握手 0.98–1.26s，`tools/list` 返回 `['drux_ping']` |
| **U1b** | 中文入参经 stdio 往返不损坏 | ⚠️ **服务端成立，宿主侧未证** | `test_cjk_argument_round_trips` 通过，收发 UTF-8 逐字节相同。根因在依赖里：`mcp/server/stdio.py:170-179` 自己把两个 buffer 重包成 UTF-8（`errors='replace'`），所以 `PYTHONIOENCODING` / `PYTHONUTF8` 结构上够不到它——计划里预设的 `force_utf8()` 修的是一个不存在的问题。**未证的正是计划 A 的唯一验收**：本测试的 client 是我们自己的代码，宿主的编码器与 JSON 写法不是 |
| **U2** | `mcp.json` 里的命令路径怎么写 | ✅ **`${QODER_PLUGIN_ROOT}`** | 扫 26 个插件：指向插件内部文件的 `args` 两例全用该变量，相对路径 0 例。附带推翻一条我原来的假设：**相对路径 hook 命令在本机被证明是坏的**（宿主按 workspace cwd 解析，日志有 `MODULE_NOT_FOUND` 且同记录里 `plugin_root` 已知未用），已改 |
| **U3** | 一个未上架的本地目录能否作为插件安装 | ⏳ **待人工**（见下） | 本机 26 个插件全在 `cache/<market>/<plugin>/<version>/`，注册表条目都带 UUID `marketId`，**没有本地安装的先例**。`qoder` 不在 PATH 上，没有可自助的 CLI 安装命令 |
| **U4** | 插件带的 hook 是否真被宿主调用 | ⏳ **待人工** | 尚无 `hooks/.drux-hook-stop.log`，该文件的存在与否就是判据 |
| **U5**（新） | 宿主能不能 spawn `python` | ⏳ **待人工** | 全机 **0 个插件**用 python 起 MCP server（只有 `npx` / `${QODER_NODE_RUNTIME}`），且本机没有 `py` 启动器。这一条不成立就是计划 A 的失败出口 |

## 还没证的这三条怎么读结果

**看 `hooks/.drux-hook-stop.log` 时**（字段是 `raw_bytes` / `chars`，不是 `bytes`）：

- 有行 → hook 通道通。`raw_bytes != chars` 还免费告诉你宿主发来的不是合法 UTF-8。
- 没行 → **不能单独当"宿主不调 hook"的判据**。探针自身已经不可能因为载荷内容而不落行（它读 `sys.stdin.buffer`，
  且记录先拼好再 open），但"宿主调了钩子、仍然零日志"还剩四条不在探针掌控内的路径，逐条排：
  1. `hooks/hooks.json` 用的是裸 `python`——宿主 spawn 用的 PATH 里有没有它，就是 U5，本次要量的正是这个；
  2. `${QODER_PLUGIN_ROOT}` 在 hook 的 `command` 字段里到底会不会被展开（证据只证明了这个变量在**别的插件**的 command 里被真替换过）；
  3. `hooks/hooks.json` 可能根本没被宿主加载；
  4. 宿主若不关闭 stdin，`sys.stdin.buffer.read()` 会一直阻塞，到 `timeout: 10` 被杀——同样一行都不留。
  所以这一步必须同时去宿主日志里找那次 hook 运行的成功/失败记录，两个证据一起下结论。


**`tools/list` 里看不见 `drux_ping` 时**：

- 先去宿主日志找 `WinError 10106` 或 `_overlapped` 字样。若命中，说明子进程环境被整体替换（没 SYSTEMROOT，Winsock 起不动），这是**配置问题不是能力问题**。`mcp.json` 此刻没有 `env` 键，且已有断言钉住它不许被"顺手加上"。
- 没有这类痕迹才是真的能力不支持，走计划 A 的失败出口。

**中文往返那一步**：

- 宿主如果以 `ensure_ascii=True` 发请求，回显里看到的是 `\uXXXX` 转义。字符串比较会**因为错误的原因**通过（线上跑的其实是纯 ASCII）。所以这一步不许只比字符串，要比**字节数**。

## 需要你做的那一次动作（U3/U4/U5 全靠它）

我不能自己做完：注册表 `~/.qoder/plugins/installed_plugins_v2.json` 是宿主持有的共享状态，当场有 5 个 `.tmp` 说明宿主在原子写它，手改写坏会连累其余 26 个插件；而且验完必须重启会话，重启会杀掉当前这个会话。

仓库现在**同时**是 skill 目录和插件包，但 `SKILL.md` 已经从顶层下沉到 `skills/deep-research-ultra/`，而 `~/.agents/skills/deep-research-ultra/SKILL.md` 这个路径**已经不存在了**。也就是说：
**不装插件，这个 skill 就用不了了。** 这是你选的「必需：不装不开跑」的字面兑现，它在这里提前发生了一次。
所以最稳的顺序是：

1. 你在 Qoder 的插件管理里，把 `C:\Users\Administrator\.agents\skills\deep-research-ultra` 以本地插件方式装上（若只有市场安装入口、装不了本地目录，直接说——那本身就是 U3 的答案，按失败出口退回 CLI 形态，不重试第三种方案）。
2. 退出并重启 Qoder CLI，开一个新会话。
3. 新会话里说一句"继续计划 A 的验证"，我会自己跑 `mcp_list` 找 `drux_ping`、比对字节数发中文、读 hook 日志，把 U3/U4/U5 写成事实并接着做计划 A 剩下的 Task 6 与计划 B。

**想先回到能用的状态**：`git checkout main`（main 还停在 v6.14 的形态，skill 立刻恢复可用），这条分支上的 6 个提交原样留着不丢。

## 尚缺的取证

- **握手与冷启动计时未落文档**：`task-2-report.md` 的 §4 写的是"报告了 1.2–1.3s"这一转述，没有贴带时间戳的原始输出。计划 A 的 CHANGELOG 承诺要附握手耗时、hook 日志行数、冷启动秒数三个实测数，现在只能引用转述。重启后那次验证要顺手补上可复制的计时。
- **U2 里 `${QODER_PLUGIN_ROOT}` 的展开只在本机成立**：macOS/Linux 未实测，README 需按现状声明。

## U3 的安装入口：本机能试的都试过了（2026-09-20 二次复测）

复测的三个否定结果（都不是"插件装坏了"，是"根本没装上"）：

| 检查 | 命令/工具 | 结果 |
|---|---|---|
| 宿主有没有 `drux_*` 工具 | `mcp_list({keyword:"drux"})` | `{"tools":[],"total":0}`；全量列表里 grep `drux\|deep-research` 也是 0 命中 |
| hook 有没有被调过 | `ls hooks/` | 只有 `hooks.json`、`probe_log.py`，无 `.drux-hook-stop.log` |
| 注册表里有没有我们 | 读 `installed_plugins_v2.json` | 仍 26 条，`deep-research`/`drux` 命中 0；`settings.json` 的 `enabledPlugins` 同样 0 条（共 26） |

四条安装路径逐条查过的结论：

1. **`mcp__extension-market__install_extension` 不可用**。入参只有 `installRef`，且描述明文"Never invent references or submit URLs, commands, market IDs, or destination paths"——它只能装市场里已列出的条目，**结构上就装不了本地目录**。
2. **没有 CLI 入口**。`qoder` 与 `qodercli` 都不在 PATH；`~/.qoder/entry/qoder-dispatcher.ps1` 的查找顺序是 `QODER_CLI_BIN` → PATH 上的 `qodercli` → `~/.qoder/bin/qodercli/qodercli.exe`，本机三者皆无，所以拿不到 `--help` 去看有没有 plugin 子命令。npm 全局目录里也没有 `@qoder-ai` 包。
3. **没有本地市场先例**。`plugins/cache/` 下只有 `qoder-marketplace` 与 `qoderapp-bundler` 两个市场；注册表 26 条的 `scope` 全是 `user`，没有 `local`/`link`/`dev` 这类值可参照。
4. **手工写入注册表可行但未执行**。条目形状已知（`{scope, installPath, version, installedAt, marketId, displayName}` + `enabledPlugins["<name>@<market>"]=true`），但 `marketId` 是宿主发放的 UUID，本地插件该填什么**没有证据**；且该文件当场有 5 个 `.tmp`，说明宿主在原子写它，改坏会连累其余 26 个插件。属于共享状态，等用户点头才动。

**因此 U3 目前的状态是"未测"，不是"不成立"**。按判读规则：不能因为看不见 tools 就宣布插件化失败。

## 手工安装已执行（2026-09-21，用户授权"手工装吧，试一试"）

上面第 4 条路径（手工写入注册表）当场执行了。可逆性先做：改前把
`installed_plugins_v2.json` 与 `settings.json` 拷到 `~/.qoder/plugins/.planA-backup/*.orig`。

| 步骤 | 做法 | 实测输出 |
|---|---|---|
| 导出干净树 | `git archive HEAD \| tar -x -C ~/.qoder/plugins/cache/local/deep-research-ultra/7.0.0/` | 无 `.git`、无 `.superpowers`、无 `bd.html` |
| 登记 | 键 `deep-research-ultra@local`，`scope: user`，不写 `marketId` | 条目总数 26 → 27；`原有条目一字未动：True`；`enabledPlugins 已置 true：True`；重跑报 `已存在，不动`（幂等） |
| 装位自验 | 用装位那份 `mcp_client.py` 起装位 `server.py` | `open()=True 耗时 1.22s`；`tools/list -> ['drux_ping']`；中文往返 `发出字节=44 收到字节=44`；hook 探针 `exit=0`，日志 `raw_bytes=45` = 载荷 44 + 换行 |

**这一步只证明"安装位那份树独立可跑"，宿主认不认它仍未测** —— 起新会话后 `mcp_list({keyword:"drux"})` 仍是
`{"tools":[],"total":0}`，因为本会话早于登记时刻，宿主只在会话启动时加载插件。所以 U3/U4/U5 还是要等一次真重启。

### 两个连带事实

1. **改代码必须重新导出**：宿主现在从 `cache/local/deep-research-ultra/7.0.0/` 加载，不再看
   `~/.agents/skills/deep-research-ultra`。此后任何改动都要重跑上面那条 `git archive`，否则验的是旧代码。
2. **`git archive` 出的是 CRLF**：本仓库 `core.autocrlf=true` 且无 `.gitattributes`，blob 存 LF、导出转 CRLF
   （逐文件测过去 CR 计数：git 侧 0、装位侧 = 行数，去掉 CR 后字节全等）。所以"装位文件跟 git 不一样"是换行符，
   不是内容漂移——别拿 `sha256sum` 直接比 blob 和工作树。

## 重启前顺手做的两项取证（都改了结论）

### 一、非市场插件的 mcp.json 确实会被宿主加载

`qoder-context@qoderapp-bundler` 的注册条目**没有 `marketId`**，`@` 后缀也不是市场名，但它带着
`mcp.json` + `hooks/` + `skills/`，且本次会话里 `SearchWorkspace` / `SearchKnowledge` 就是它的 MCP 工具
（`toolOverrides.exposedName` 去掉了前缀）。它的 `mcp.json` 用的正是
`"${QODER_PLUGIN_ROOT}/runtime/qoder-search.bundle.mjs"`。

这条先例同时说明：① `@local` 这种非市场后缀不必然被宿主拒绝；② `${QODER_PLUGIN_ROOT}` 是官方在用的变量
（另有 `${QODER_NODE_RUNTIME}` 指插件自带运行时——Python 没有对应变量，所以 `python` 必须能在宿主环境里
解析到，这正是 U5 要量的）。**注意它不能替代实测**：它证明的是"这条路走得通"，不是"我们这份也走得通"。

### 二、hook 声明写法横扫 6 个真插件后的纠正

| 判据 | 本机证据 | 我们原来的写法 |
|---|---|---|
| `matcher` 键 | 30 个 hook 组里 24 组**根本不写**，5 组写 `'Edit\|Write'` 这类真正则，空串 `""` 只 quality-guardian 的 Stop 一处 | 写了 `"matcher": ""` ❌ |
| 命令形态 | 主流是 shell 串 + 引号包变量：`node "${QODER_PLUGIN_ROOT}/hooks/x.mjs"`（vercel）、`sh "…"`（superun）；bundler 那份另用 `cmd.exe` + `args` 数组 | `python "${QODER_PLUGIN_ROOT}/hooks/probe_log.py"` ✅ 与 vercel 同形 |
| 裸相对路径 | quality-guardian 的 `node hooks/x.js` 有先例但无"确实触发过"的证据 | 已避开 ✅ |

空串 matcher 的风险是要害：计划 A 拿 hook 日志当 U4 的**唯一**证据，而空串若被宿主按字面量比较，hook 就永不触发，
日志为空会被读成"宿主不调插件 hook"——一次假阴性足以作废整个插件方案。故按 24/30 的主流写法删掉该键，
并加测试 `test_stop_hook_declaration_matches_proven_form` 把"不许空 matcher、必须带 `${QODER_PLUGIN_ROOT}`、
不许裸相对路径"钉住（红→绿：先失败于 `hooks.json` 的空串，删键后 `4 passed`；技能内 `315 passed` 不变）。

## U4 已成立：宿主真的调起了插件的 Stop hook（2026-09-21 13:28:42，未重启）

写上面那段"空串有风险"之后十几分钟，实测把它推翻了。安装位 `hooks/.drux-hook-stop.log` 里出现一行：

```json
{"at": "2026-09-21T13:28:42.747507", "raw_bytes": 4473, "chars": 2403}
```

这条不是我造的：我的自验脚本写的是 `raw_bytes=45`（一段中文载荷）且当场删掉了日志，13:2x 复查 `find` 也确实没有该文件。
4473 字节 / 2403 字符（字符数远小于字节数 → 载荷含中文）只可能来自宿主的一个真实 Stop 事件。所以：

- **U4 = 成立**：宿主会加载插件的 `hooks/hooks.json` 并调起 Stop hook，`python "${QODER_PLUGIN_ROOT}/…"` 这种
  shell 串写法可被调起。这是计划 A 的第 4 项事实，也是"双层强制"里 hook 那一层能落地的第一手证据。
- **空串 matcher 会被本机宿主当全匹配**，不是静默不触发。上一条"怕假阴性"的动机因此作废，
  测试里保留断言的真实理由已改写为"跟 24/30 多数派一致 + 命令必须走 `${QODER_PLUGIN_ROOT}`"。
- **不需要重启就拿到了 hook 证据**：登记发生在 13:19:04，本会话在此之前就起来了，hook 却在 13:28 被调起
  → 宿主对 hook 声明是事件时读取、不是会话启动时快照。这解释了为什么 U4 先于 U3 出结果。

**还不能下的结论**：① 13:19 到 13:28 之间本会话结束过好几个 turn，日志只有这一行，
所以"每次 Stop 必调"没有证据，派发节奏（合并、丢弃、还是按某种条件）待下一次复查看是否出现第二行；
② U3（MCP tools 可见）此刻仍 `mcp_list({keyword:"drux"}) → 0 条`，MCP 侧看起来仍是会话启动时加载，
所以 tools 那半边还是要一次重启才能判；③ 4473 字节的完整载荷没留档（探针只记长度），
计划 B 的 `gate_hook.py` 要真用它就得先把载荷落盘看结构。

## U3 / U5 已成立：宿主面板里 drux_ping 是可见工具（2026-09-21，用户截图）

用户在「扩展管理 → 连接器」面板截图：`由 Plugin 提供` 一栏里出现

```
deep-research-ultra   ·可用   由 超级深度调研 提供
  工具 (1)
    drux_ping
      连通性探针：原样返回入参（含中文）。计划 B 会删除本工具。
```

这三行同时结掉三项未验证：

| 项 | 判据 | 结论 |
|---|---|---|
| **U3** 本地插件能否被宿主安装并加载 | 面板列出了我们这个插件，状态"可用" | **成立** |
| **U5** 宿主能否起 `python` 这个子进程 | 面板能列出 `drux_ping`，就必须已经 spawn 了 `python ${QODER_PLUGIN_ROOT}/server.py` 并完成 `initialize` + `tools/list` 握手 | **成立**（Python 3.13 + mcp 2.1.1，走 PATH 上的 `python`，无需宿主自带运行时） |
| **U1b** 中文经宿主通道 | 面板把 `server.py` 里那段中文 docstring 原样显示，无乱码 | 通道侧**间接**成立；直接调用的字节级比对仍要在能看见该工具的会话里做一次 |

**"由 超级深度调研 提供"这行是 plugin.json 的 `displayNameZh` 生效的证据**，顺带说明宿主读的是我们的清单而不是猜的。

### 更正本文前两处说法

- 第 77 行"U3 目前的状态是未测"与第 91 行"所以 U3/U4/U5 还是要等一次真重启"——**结论作废**，
  保留原文是为了留下"我当时怎么错的"。错在把"`mcp_list` 在旧会话里查不到"当成了"宿主没加载"：
  宿主确实加载了，只是**会话的工具表是启动时的快照**，旧会话永远看不见新插件。
  这条区分很重要，它把"要不要重启"从玄学变成了一个有明确答案的问题：

| 要验/要用什么 | 需要重启吗 | 依据 |
|---|---|---|
| Stop hook 被调起 | **不需要** | U4：登记后同一会话 13:28 就触发 |
| 宿主面板看见 tools | **不需要** | 本节截图，登记后即列 |
| 当前会话里 `mcp_list` / 直接调 `drux_ping` | **需要**（开新会话） | 本会话 `mcp_list({keyword:"drux"})` 恒 0，而面板可见 |
| skill 自己直连 `server.py`（不经宿主） | **完全不需要** | `tests/test_plugin_shell.py` 4 passed：从仓库目录 spawn、握手、中文往返，全程不碰宿主 |

最后一行是"能不能装完就用"的答案：**能**，只要调用方是 skill 自己的 Python 代码而不是宿主工具表。
这条已升为计划 B 的默认路径（见下节）。

## 补证：宿主侧真调用了一次 drux_ping（2026-09-21，开新会话后）

截图只证明"面板里有这个工具"，不证明"调得动"。新会话里宿主把它作为
`mcp__plugin_deep-research-ultra_deep-research-ultra__drux_ping` 暴露出来，实调一次：

```
入参 {"text": "边缘推理·调研 2026 年—含全角？"}
出参 {"result": "边缘推理·调研 2026 年—含全角？"}
```

这是 U1b（中文经 stdio 往返不乱码）第一次由**宿主通道**跑通，之前只有测试脚本自己 spawn 的通道。
计划 A 的验收标准到此全部有实证，不再有"看面板推断"这一档。

顺带证实了本文的会话快照说：同一个包，注册后**旧会话查不到、新会话查得到**，
差的是宿主启动时的工具表快照，不是插件没加载。

## 形态定案（计划 A 的全部实测换回这一条结论，之后不再改形态）

**一个插件包，三种角色，两条调用路。** 目录形状就是计划 A 已经建好的那个，不再动：

```
插件根/
├── server.py                 ← MCP server：四个业务工具（计划 B 填）
├── mcp.json                  ← 给宿主看的声明（注册后 agent 能直接调工具）
├── hooks/hooks.json + gate_hook.py  ← Stop 兜底：交付声明必须带真戳
└── skills/deep-research-ultra/       ← skill 本体（流程、脚本、账本、校验门）
```

两条路各管各的，**不互相依赖**：

| | A 路：skill 内部直连（默认，零重启） | B 路：注册为宿主插件（可选加分） |
|---|---|---|
| 谁发起 | skill 的 Python 用自己的 `McpSession` spawn `server.py` | 宿主在会话启动时 spawn |
| 需要注册/重启 | **都不需要**，clone/解压即用 | 需要一次注册 + 开新会话 |
| 保证什么 | 硬校验由脚本自己把关：账本溯源、来源体检、防伪戳、发布门——**agent 想绕也绕不过**，因为调用发生在 Python 进程里 | agent 能直接看见并调用 `drux_*`；Stop hook 兜住"没跑校验就宣称完成" |
| 已实测 | 握手 1.22s、中文往返 44/44 字节、4 passed | U3/U4/U5 全部成立（本文上两节） |

**这条定案解决了"开发来开发去"的根因**：之前反复是因为把"必须让宿主加载"当成了唯一目标，
于是插件注册、市场安装、重启这些不可控环节变成了阻塞点。现在目标改成
**"强制力放在 A 路（我们自己进程内），B 路只是让体验更好"**——B 路装不上也不影响校验成立，
所以不再需要为了验证一个想法去换形态。计划 B 按这个分工实现，不再重开形态讨论。

