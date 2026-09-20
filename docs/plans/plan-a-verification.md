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
