# CHANGELOG — deep-research-ultra

> 本文件**单独**记录 skill 的版本更新历史、更新概览与迁移指南。
> SKILL.md 保持纯净，只含运行必需内容（触发条件/使用说明/工作流/约束）——见开发约束第 10 条。

---

## v6.15.0（2026-09-22）— 实跑反馈 16 项：文档与代码口径对齐

**这一轮的输入**：一次真实深度调研跑完后交回的 16 条工具反馈。前两条被判为"照着文档做会出错"，
按反馈自己的优先级先修，其余按序处理。逐条对源码核实后的账目：
**已修 10 条**（1、2、4、6、7、9、10、11、12、16），**部分处理 3 条**（3 只补了文档口径、
5 只补了"缺依赖看得见"+ 文档更正、14 只由 1+4 间接缓解），
**未复现 1 条**（8，代码里每条失败路径都是 `continue`，改为补测试锁住语义），
**本轮未做 2 条**（13、15，见文末清单）。

**① 档 B 判据收紧（第 1 条）**：`verify_primary` 原先只比对来源 URL 与复核 URL 是否同域，
把"同一篇文章的同一网页地址填两遍"也算通过——等于结论可以自己给自己盖章。现在两条硬拒：
复核 URL 与账本里已有的任一来源 URL 重复时直接不升级；两者不是同一制品时也拒。
"同一制品"由 `_artifact_key` 判定：同一篇论文的 `/abs/`、`/pdf/`（带不带版本号都一样）、`/html/`、
`export.arxiv.org/api/query?id_list=` 几种表示归一；新增 GitHub 归一键，网页 blob/tree、raw 字节流、
REST contents 三种入口记成同一个 `owner/repo@ref:path`，
缺省 ref 与 main/master 记同值（REST 不带 `?ref=` 取的就是默认分支），具名分支（如 3.14）仍算不同制品——
版本差异本身常是结论，不能折叠。

**② 分片 schema 与 merge 对齐（第 2 条）**：SKILL.md 教子 Agent 写 `{"claims": [...], "sources": [...]}`，
而 `merge` 只认逐条带 `type` 的记录——照文档写的分片会被整份静默丢光。现在两种形状都收
（容器展开时按 key 补 `type`），且拒收不再是汇总数字：每条拒收按"文件名 + 具体原因"打到 stderr，
JSON 解析失败也回话（原先坏文件读成 0 条，一声不响）。

**④ 子域折叠（第 4 条）**：反馈的场景是"官方 API + 官方网页"这对最硬的自证组合两条通道都不认。
档 A 的子域折叠规则本身保留（`api.github.com` 与 `github.com` 确实不是两个独立来源，判独立是放水）；
这对组合改由档 B 承认——随 ① 的 GitHub 归一键，同一文件的 API 入口与网页入口现在是"同一制品、不同通道"，
测试 `test_github_api_channel_of_a_blob_source_upgrades` 盯着这条路径。

**⑥⑦⑨⑪⑫ 命令行与文档（第 6、7、9、11、12 条）**：
`research.py` 的 json / csv / markdown 三种文本输出过去只有 html 认 `-o`，`--format json -o x.json` 会打屏不落盘，
现在统一走一个 `emit()`（第 7 条）。`set-status` 的 `--text` 与 `--status` 解耦，改文字不再被迫连带改状态（第 6 条）。
计划阶段被裁剪的维度除写 stderr 外，同时进 stdout 的待确认清单（第 11 条）。
子 Agent 提示模板补上 `--format json --no-plan` 的可用组合（第 9 条）。
`--help` 禁令改为"未文档化参数允许查一次 `--help`"，仍禁止 `ls` 与读源码探索，并在 14.3 补全
账本命令签名表（init / add-claim / add-source / set-status / verify-primary / merge / status / export）（第 12 条）。

**⑯ 骨架不再把未验证项标成待写（第 16 条）**：`skeleton.py` 里 pending 状态的 claim 从前渲染成
`【待写】` 占位，与"Lead 必须写掉的段落"混在同一个标记里，本次实跑 40 处——逐条处置让"一个 session 一轮"必然破功。
现在改成 `- ⚠️ 仅作线索：…（状态 X，未达 verified 判据）`，不占标记；账本事实行补冲突数与对冲数。
把这类条目当结论引用，仍然会被校验门拦下。

**⑩ 归一后的命中要能解释（第 10 条）**：反馈原话是"有告警行，但归一后命中的是什么已不可解释"。
`github-deep-search` 把 >3 词的自然语言查询压成短查询（GitHub 仓库搜索按 AND 匹配，长查询恒 0 命中），
过去只说"归一成了什么"。现在告警同时列出**被丢掉的词**，并且每条结果带上新字段 `query`＝命中它实际发出去的查询：
告警行会滚走，JSON 里的这条记录才是 Lead 事后判相关性的依据——不然一条仓库被"evaluation correctness"捞上来，
看起来却像是回答了原始问题。依赖图挖掘来的结果不填 `query`（那是种子仓库带出来的，不是查询命中的）。
`SearchResult.to_dict()` 过去把 `raw` 整块丢掉，所以 `query` 作为显式字段进 JSON。
另在 SKILL.md 十四节的开源链补一段说明：这条链会改写查询，嫌改得狠就自己传 ≤3 词短查询。

**③⑭ 探针粒度写进文档（第 3、14 条）**：步骤 0.4 后新增一段——闸门判的是"引擎活着"，
不等于"本主题到得了制品"（实测 `arxiv-fulltext` 探针 ✅ 而对该主题每次 HTTP 406）；
派子 Agent 前用该主题要用的引擎 + 实际查询词做一次 dry-run，到不了就换通道，
别把"指定引擎没结果"当成"这个主题没资料"。第 14 条（覆盖率 39%）的根因指向 1、4，
本轮修复后学术类 claim 的升级路径才真正存在；探针按主题探活的代码实现仍未做。

**⑤ 顺手挖到的现场根因：curl_cffi 没装，且退得看不见**（第 5 条的定位过程）：
查第 5 条时实测 arXiv——长查询、短查询、加引号、加字段前缀、甚至空查询，全部 HTTP 406，
换 User-Agent、换 `Accept` 一律 406，响应头 `via: varnish` 说明是 arXiv 边缘节点直接拒；
本机 `getproxies()` 为空，排除本地代理。真原因是 `_http_get` 依赖的 curl_cffi（TLS/JA3 指纹伪装）
没装，代码 `except ImportError: pass` 一声不响地退回 urllib——Lead 于是拿一套没有指纹的传输层
去判"这个源不行"。现在缺依赖会在第一次请求时说一次（含 `pip install curl_cffi`），
`--probe` 输出顶部即可见；六节与 5.1 的说明同步改成实情：
`arxiv-fulltext` 的 `search()` 只回元数据，全文由 `download_pdf` / `fetch_latex` 按编号另取。
**装不装由用户决定**，本轮只负责让它看得见。

**测试**：新增 `tests/test_v615_dogfood.py` 20 项（重填已有 URL 不升级、arXiv 四种表示算同一制品、
另一篇论文不算反查、GitHub API 通道升级、容器形状可收、拒收点名到文件、扁平记录仍可用、
坏 JSON 分片回话、`-o` 落盘、`set-status` 可只改原文、参数缺失仍要点名、单引擎挂掉不吞其余引擎、
全挂要退 1 并说明原因、未验证项不占待写、缺 curl_cffi 只提示一次、告警点名被丢掉的词、
命中结果带实际查询）。"不同分支是不同制品"由既有测试
`test_v66_fixes.py::test_different_branch_is_a_different_artifact` 守着；另有三条旧测试
原先依赖"同一 URL 重填即可升级"这条路径，改为使用真正不同的制品表示，规则本身未放宽。
`scripts` 335 passed，根 `tests` 45 passed。

**本轮未做，留清单**：
第 5 条的引擎侧仍未验：装不装 curl_cffi 由用户定，装上后 arXiv 是否真能出数据要重跑一次才算数；
第 13 条——六维质量门按"报告里有没有 github.com 链接"触发，缺显式豁免声明位（本轮改测试时现场撞到一次：
把夹具换成 GitHub 制品后被判需要许可证/最近提交/适配性）；
第 14 条的覆盖率根因复测；第 15 条——Stop 钩子的拦截能力仍未被真实观测过，需另造一次"无戳却声称交付"的会话。

---

## v7.0.0-alpha4（2026-09-21）— Stop 钩子 gate_hook.py：交付声明由机器复核

**加这个做什么**：防伪戳能判真伪，但判完只是打印一行字。这个钩子把它变成硬约束——
工作区里有本轮调研产出的 `report.md`，而它自称过了校验门、戳却验不过，就不让本轮收工，
并把"哪条不成立 + 怎么修"交回给 Lead。

**判定四条全中才拦**（spec 第八节，一条不多）：`.research/<会话>/` 同时有 `session.json` 与
`report.md`；报告 mtime 不早于会话 `started_at`；正文/末轮消息出现交付声明或戳行；验戳不过。
首行写 `DRAFT:` 视为明示未完成，放行。

**载荷形态是抓来的，不是猜的**：探针改成把宿主 Stop 载荷原样落盘，拿到真实字段
`cwd / stop_hook_active / last_assistant_message / transcript_path / permission_mode`。
据此改四处（spec 第八节"实现期修订"记了原因）：工作区取 `cwd`；起点用账本自带的
`started_at`；**`stop_hook_active` 为真一律放行**（宿主用它告知"上次拦过、已又跑一轮"，
再拦就是死循环）；不再比 `gate.json`——戳里两个指纹和 gate.json 用的是同一对，
再比一遍零新增信息，却多一个可被伪造的文件。

**不拦的边界**：没有 `.research` 的普通项目、没声称交付的半成品、上一轮遗留的旧报告。
载荷坏 / 钩子自己抛异常 / 超 500ms 预算 → 放行并在 stderr 说明；只有真判出不一致才退 2。
不回显报告正文（否则用户内容被抄进日志）。

**实测**：`tests/test_gate_hook.py` 14 passed（按宿主契约从 stdin 喂载荷、断言退出码，
不 import 调函数——钩子的失效方式全发生在进程边界）；根 `45 passed`；
判定耗时中位 119ms / 最慢 155ms（报告 2800 字符 + 账本 200 行，含解释器冷启动 50ms）。

**没做**：端到端实跑还欠一次（spec 11.4 的硬门：五个工具真被调用、报告带有效戳、
`--verify-stamp` 打勾）；`exit 2` 能拦住 Stop 这一步只有"同类插件这么用"的间接证据，
要在那次实跑里看宿主真反应。

---

## v7.0.0-alpha3（2026-09-21）— 五个业务工具落地：补上 pending → verified 的断点

**为什么不是四个工具**：spec 第六节原本只给 `session_start / claim_add / gate_check / stamp_issue` 四个。
照那四个写完，三条红测试（`test_gate_check_reports_pass_and_fail`、`test_stamp_binds_body_and_ledger`、
`test_second_claim_after_stamp_invalidates_ledger_match`）怎么也绿不了——不是 fixture 打错字，
是**四个工具里没有任何一条路能把 claim 升到 verified**：MCP 侧只能记 pending，发布门永远不过，
戳永远盖不上，`gate_check` 和 `stamp_issue` 于是变成两个永远报失败的空转工具。

**处置**：补第五个工具 `drux_claim_verify`（机械升级），而不是放宽账本纪律、允许调用方自称
"我已交叉验证"（那正是账本一直拦的东西）。档 A 数**不同注册域**且转载去重后 ≥2 组，
档 B 走既有的 `verify_primary` 同制品反查。

**一处刻意的不对称**：升级判据比发布门 2b 更严——2b 只做标题/内容去重，两条同域来源在门里算 2，
在 SKILL.md 的档 A 定义（≥2 个不同注册域）里只算 1。取严不取宽，宁可少升也不放水。

**两个自己抓到的设计缺陷**（写实现时发现的，不是测出来的）：

1. 逐条 `set_status` 会让 n 条 claim 触发 n 次账本全量重写 → 改成一次批量落盘；
   且已 verified 的 claim 不再重写——重写会动账本指纹，把先前盖好的戳白白作废。
2. 把每条 claim 的域名清单塞进 `extra=` 会整批共享同一份清单（`set_status` 是批量写）
   → 只记一个 `verified_via='cross_validation'` 标记，域名本来就能从账本来源行推出来。

**并发门**：`ledger.lock` 存在即拒绝升级并直说，且**不删别人的锁**。

**实测数字**：新增 `tests/test_server_tools.py` 16 passed；根 `tests` 31 passed（7.49s）；
skill 脚本 `315 passed`（53.16s）。计划 A 的两条真握手协议测试没有删掉，改成断言五个工具名
（`names == BUSINESS_TOOLS` 且 `'drux_ping' not in names`），中文往返改走 `drux_claim_add`
的失败路径——它们干的活是"真起子进程说协议"，这个职责不能因为探针工具下线就丢。

**没做**：`hooks/gate_hook.py`（Stop 钩子）与端到端实跑仍在计划 B 后半。

---

## v7.0.0-alpha2（2026-09-21）— 跨宿主安装器 install.py：一个文件夹传给别的 AI

**为什么加**：用户要求"别的 AI 也要能用"。内核本来就零宿主依赖（拷目录即可），差的只是
"各家 MCP 配置落在哪、怎么写"这件事要人手工查。现在一条命令代劳。

**本机实测的宿主形态**（不是查文档，见 spec 第十五节的表）：

| 宿主 | skill 落点 | MCP 落点 | 验证到哪一步 |
|------|-----------|---------|-------------|
| Qoder | `~/.qoder/skills/` | 插件壳 `mcp.json` | 已跑通 `drux_ping` 往返 |
| TRAE CN | `~/.trae-cn/skills/<名>/SKILL.md`（399 个在用） | `%APPDATA%\Trae CN\User\mcp.json`，与插件 mcp.json **同构** | 装到 skill + 写配置 = 11 条测试覆盖；真机 dry-run 已跑 |
| Codex CLI | `~/.codex/skills/` | `codex mcp add` 一条命令（或 config.toml `[mcp_servers.*]`） | **仅注册通道已验证**（`mcp get` enabled/stdio、`doctor` ✓ 2 stdio）；**调用未验证**，本机无外网，`codex exec` 8 分钟无返回 |
| Claude Code | `~/.claude/skills/` | **未验证**（CLI 不在 PATH，settings.json 只有 hooks 键） | 文档只写"skill 目录可拷" |

**install.py 的三条硬护栏**（都是先写红测试再实现的）：

1. 目标 `mcp.json` 是坏 JSON → 拒绝覆盖并退 2。把整份配置改写成我们的，等于顺手清掉用户的白名单。
2. 目标 skill 目录带 `.git` → 拒绝覆盖（本机 TRAE 就是这个现状：整个仓库被塞进 skills 目录，
   SKILL.md 在下一层所以宿主扫不到）。普通旧版本无 `.git`，正常替换。
3. 幂等 + 不越界：只动我们那一条，别人的 MCP 条目和未知顶层键原样保留；跑第二遍文件一字节不变；
   `--dry-run` 与 Qoder（MCP 走插件壳）都不写任何用户配置。

**实测数字**：`tests/test_install.py` 11 passed；根 `15 passed`；skill 脚本 `315 passed`。
真机 dry-run：`--host trae` 退 2 并指名要人工确认的那个目录，`--host qoder` 退 0 且
`~/.qoder/skills/deep-research-ultra` 确实没被创建。

**没做**：不给每家落 `plugin.json`（只有 Qoder 用到，先不造轮子）；Codex 的调用要等外网能通再补测，
在那之前不写"支持 Codex"。

---

## v7.0.0-alpha（2026-09-21）— 插件壳落地并实测通过：形态冻结，不再改

**这一版只证明一件事**：本地 Python MCP server + 插件 Stop hook 能被宿主真加载。
四个业务工具和真正的校验 hook **还没写**，那是计划 B。标 alpha 就是为了不让人误以为插件已经能干业务活。
因此 skill 正文版本仍是 6.14.0——业务行为一行没改。

**实测数据（本机当轮跑出来的，不是推断）**

| 证据 | 数值 | 出处 |
|------|------|------|
| stdio 握手（从插件安装位起进程） | `open()=True`，耗时 **1.22 s** | 安装位自验脚本 |
| `tools/list` 往返 | 发出 44 字节 / 收到 44 字节，返回 `['drux_ping']` | 同上 |
| 中文入参往返 | 探针串 `边缘推理·调研 2026 年—含全角？` 原样返回，`isError` 为假 | `tests/test_plugin_shell.py` |
| 宿主面板可见工具 | 「扩展管理 → 连接器」列出 `deep-research-ultra · 可用 · drux_ping` | 2026-09-21 用户截图 |
| 插件 Stop hook 真被宿主调起 | 日志行 `at 2026-09-21T13:28:42.747507, raw_bytes=4473, chars=2403`，**当轮未重启** | `hooks/probe_log.py` 落的日志 |
| 回归 | 根目录 `4 passed`；`skills/deep-research-ultra/scripts` `315 passed` | pytest |

**改了什么**

| 改动 | 位置 | 说明 |
|------|------|------|
| skill 目录下沉 | `skills/deep-research-ultra/` | 腾出仓库根放插件壳，一个包同时是 skill、MCP server、插件 |
| 插件清单 | `.qoder-plugin/plugin.json` | 声明 `skills` / `mcpServers` / `hooks` 三个入口 |
| MCP 声明 | `mcp.json` | 命令走 `${QODER_PLUGIN_ROOT}`；**故意不写 `env`**——Windows 上给子进程空 env 会在 `import _overlapped` 处崩，看起来像"握手不可能" |
| hook 声明 | `hooks/hooks.json` | Stop 组不写 `matcher` 键（本机 24/30 组的主流写法），命令绝对路径化 |
| 探针脚本 | `server.py`、`hooks/probe_log.py` | 只够证明通路，`drux_ping` 是占位工具，计划 B 换成业务工具 |
| 壳的回归测试 | `tests/test_plugin_shell.py` | 握手、中文往返、壳文件、hook 声明写法四项断言 |
| 安装文档重写 | `README.md` | 拆成"解包即用（零注册零重启）"与"注册为宿主插件（可选）"两条路 |

**一条被实测推翻的旧设定（记下来防止再犯）**
设计阶段定过"插件未安装则不装不开跑"。实测表明强制力放在 skill 自己的 Python 里更稳：
子进程直连 `server.py` 已两次跑通，且不需要注册、不需要重启会话。
所以本版改为 **A 路（skill 内部直连，默认）承担强制校验，B 路（注册为宿主插件）只是加分项**。
宿主会话的工具表是启动时快照——这是"要重启"的唯一原因，跟校验强度无关。

---

## v6.14.0（2026-09-20）— deep 档写不完，不该逼出"看起来完成"的产物（外来清单 X-D14）

**触发这次改动的事实**：外来缺陷清单 X-D14 指着 effort 分级表说事——`deep` 档定义 6000-15000 字、
2-3 轮反思，`exhaustive` 15000+ 字。一次跑下来 Lead 一轮根本写不完这么多正文，写完还要过校验门。
使用者点破的因果链是：**这堵墙就是走捷径的动机**——"写不完 → 砍正文/留占位 → 声称过了门"。
v6.11 的防伪戳能证明"跑没跑过校验"，但拦不住"用骨架冒充报告"这一步，因为骨架本身没人认。

**改法：把能自动来的都交给脚本，把没写完的地方钉成硬失败**

| 改动 | 位置 | 说明 |
|------|------|------|
| 新增 `scripts/skeleton.py` | 新文件 | 读 `ledger.jsonl` 出报告骨架：按主题分组的 claim 清单、每条 claim 的 `[N]` 引用（直接用 source 的 `primary_index`，与校验门同一套编号）、附录来源登记表 `| [N] | Tier | 标题 | URL |`，以及 claims/verified/来源/独立域名四个事实数字 |
| 待写段落留 `【待写】` 标记 | `skeleton.py` | 执行摘要 / 调研方法 / 结论与建议 三处机器写不了的，明确标出来给 Lead |
| `【待写】` = 校验门硬失败 | `validate_report.py` 校验 3b | 有残留标记就 issue 拦下、`--stamp` 直接拒盖；`stats.placeholders` 给出数量 |
| 未达 verified 的 claim 不许装成定论 | `skeleton.py` | `pending/supplementing` 出 `⚠️ 待核：…（状态 X，未达 verified 判据）`，`conflict` 出 `⚠️ 冲突待裁决`，都带补证据或降级的待写项 |
| 「单轮产能红线」写进分级表下方 | SKILL.md effort 表后 | **一个 session 一轮**；一轮写不完就照实说本轮完成到哪、余下几轮，禁止砍正文凑数、禁止并多个 session 的活 |
| 新增 Phase 4.5 | SKILL.md | 骨架命令 + "骨架里已有什么 / Lead 只剩哪三处" 的分工表 |
| 禁止行为新增一条 | SKILL.md 十六 | 禁止把骨架当报告交 |

**实跑证据**（脚本层，非完整调研轮次）：合成账本（2 claim / 3 source）跑 `skeleton.py` →
输出 4 处 `【待写】`，引用编号为 `[1][2]`、`[3]`，登记表 3 行不串号；紧接着拿这份骨架去
`validate_report.py --stamp`，输出 `❌ 未过门，不盖戳`，issue 第一条即
`仍有 4 处【待写】占位——这是骨架不是报告（v6.14）`。也就是说骨架原样出门这条路已被机器堵死。

**新增测试**：`scripts/tests/test_skeleton.py` 11 项（章节齐 / 引用=账本编号 / 登记表不串号 /
每条 claim 都进骨架 / pending 标 ⚠️ 不装定论 / 标记在 = 过不了门 / **无标记不误伤** /
CLI 落盘 / 账本不存在硬停且不落文件 / SKILL.md 写了 skeleton.py 与"一个 session 一轮"）。
全量 **315 passed**（v6.13.1 时 304）。

**边界与代价**：
- 占位判定只认 `【待写】` 这一个字面量，不认"占位""TODO"等通用词——真实调研报告完全可能在
  正文里正当讨论"占位符"，那样会误杀。代价是 Lead 若手写别的占位词，机器看不见，仍靠 `--stamp` 与人工复核。
- 骨架不生成摘要、方法、结论——这三处是判断，脚本编出来就是假报告，宁可留标记。
- 只改了产能与门禁的错配，deep 档"多轮才写得完"这件事本身没变，也不该变。

---

## v6.13.1（2026-09-20）— 环境指引不许推荐"要绑银行卡"的源

使用者立的规矩：**需要注册的搜索源，哪怕每月有免费限量，只要注册要绑银行卡就一概不要。**

原样写着「1000 次/月免费」「500 credits/月」的 Tavily / Firecrawl 两条指引，读起来像"白嫖就行"，
Lead 会照抄给用户，用户到注册页才发现要卡。现在这两条自带自查提示
（"注册前确认免绑卡——要绑银行卡就放弃这个源"），并由 `tests/test_env_guidance_no_card.py` 钉住：
CONFIG_GUIDE 里凡是提到免费额度/credits 的条目，必须同时出现"绑卡"字样。
SKILL.md 十六、禁止行为新增一条红线。

> 注：本条只改指引文案，不宣称任何一家的计费现状——签约条件以官网为准，
> 确认要绑卡就从指引里删掉，而不是留着加脚注。

---

## v6.13.0（2026-09-20）— 下载回来的 PDF/LaTeX 先验明正身（外来清单 X-D10）

### 触发这次改动的事实
`ArxivFulltextEngine.download_pdf()` 原来只判 `if not raw` —— 网络层/代理返回一张
几百字节的 HTML 报错页、下载中途断掉、甚至换成另一篇文档，全都会被当 bytes 写盘并
返回路径，报"下载成功"。下游拿它读全文，账本里就留下一条指向无关文档的一手来源。
使用者清单里对这条的判断是对的：**这不是"偶尔失败"，是"失败被伪装成成功"。**

### 四道判定：verify_pdf_artifact(raw, paper_id)
| 顺序 | 判据 | 挡掉什么 |
|------|------|----------|
| 1 | 首 5 字节必须是 `%PDF-` | Cloudflare/登录页/报错页等 HTML |
| 2 | 体积 ≥ 4096 字节（`MIN_PDF_BYTES`） | 截断头部、占位文件 |
| 3 | 尾部 1KB 内必须有 `%%EOF` | 下到一半断流 |
| 4 | 前两页文字里能找到该论文 ID（pypdf） | 拿到的是另一篇文档 |

返回 `{ok, reason, bytes, sha256, pages, id_matched}`——`sha256` 让同一份制品两次核对得上，
`pages` 用 `/Type /Page` 计数供参考。**第 4 道没装 pypdf 时不谎称核过**：
`id_matched=None` + reason 里写明"论文 ID 一致性未核"，结构合规仍可用（论文正文确实拿到了）。

`fetch_latex()` 同样加魔数：不是 ``（gzip）就报"多半是报错页或源码不存在"并返回 None。

### 失败要看得见
`download_pdf` 不过四道时**不写盘**，`stderr` 打一行
`❌ arXiv PDF 制品校验未过（2404.19756）：<原因>`，返回 None，
并把这次判定结果留在 `engine.last_download` 里供上层记录。

### 实跑核对（真网络，非 mock）
`download_pdf('2404.19756')` → 12,822,114 字节、`pages=50`、`id_matched=True`，
说明四道不会误杀正常论文；`fetch_latex('2404.19756')` → 17,680,984 字节 gzip 通过。

### 测试
新增 `tests/test_pdf_artifact.py`（13 项：HTML/空/太小/截断四种拒绝、结构字段齐全、
ID 不一致被拦、pypdf 缺失标未核、没给 ID 不臆造比对、download_pdf 拒写盘、
fetch_latex 认 gzip）。全量 302 项通过。

---

## v6.12.0（2026-09-20）— 仓库健康扫描分五态，限流不再冒充"仓库有风险"（外来清单 X-D11）

### 触发这次改动的事实
`repo_health.py` 原来只有一条出口：`_get_json()` 把所有异常压成 `None`，
`scan_repo` 见到 `None` 就写一条 **high** 风险
「官方 API 不可达或仓库不存在（事实无法核实）」，然后综合等级 high。
GitHub 匿名 API 只有 60 次/小时，一次深跑很容易撞 403/429——
于是一个活跃仓库在报告里被判成高风险，读起来还像有依据。
**限流是我们的问题，不是仓库的问题**，两件事被塞进了同一个字段。

### fetch_json 返回 (状态码, 数据)，判定分五态
| verdict | 来源 | 含义 | 综合等级 | 退出码 |
|---------|------|------|----------|--------|
| `ok` | 200 | 拿到官方事实 | high/medium/low（按风险算） | 0 |
| `not_found` | 404 | 仓库不存在/已删除——这是仓库自身的事实 | high（category `not_found`） | 0 |
| `rate_limited` | 429 | 我们被限流 | **unknown**，一条风险都不写 | 3 |
| `forbidden` | 403 | 配额耗尽/权限不足 | **unknown** | 3 |
| `unreachable` | 0 及其他 | 网络/DNS/超时/返回体不是 JSON | **unknown** | 3 |

`overall()` 新增 `unknown`：没查到既不是低风险也不是高风险，是"不知道"。
未核实时 `build_markdown` 不再摆那张事实表（空值会读成"star 未知=不活跃"），
改打「⚠️ 未核实（verdict=…，HTTP …）+ 原因与对策」。

### 带上 GITHUB_TOKEN
`api_headers(host)` 读 `GITHUB_TOKEN`，只在 host==github 时加 `Authorization: Bearer`
（Gitee 请求不会漏出这个 token，有测试钉住）。没配 token 时 `h.anonymous=True`，
限流提示直接给到「export GITHUB_TOKEN="<你的 PAT>"（只读 public_repo 足够）」，
而不是含糊的"无法核实"。

### 测试接缝的连带修改
`test_v6.py` 里 3 个用例原来 monkeypatch `_get_json`，改 patch `fetch_json` 返回
`(200, payload)`；`test_api_unavailable` 改名 `test_api_unreachable_is_not_a_verdict`，
断言从"有一条 high 风险"翻转为"risks 为空 + overall==unknown + 报告写明未核实"。
新增 `tests/test_repo_health_verdict.py`（11 项：五态各一 / 事实仍可取 / token 真发出去 /
Gitee 不漏 token / markdown 给对策且不摆事实表 / CLI 未核实退非 0）。全量 289 项通过。

### 实跑核对
`repo_health.py fastapi/fastapi --json` → `verdict=ok, http_status=200, anonymous=true` 带全事实；
`repo_health.py this-org-really-does-not-exist-xyz/nope --json` → `verdict=not_found`，
风险类别 `not_found`（真结论），两条都按预期退 0。

---

## v6.11.0（2026-09-20）— 报告防伪戳：`--stamp` / `--verify-stamp`（外来清单 X-D15）

### 触发这次改动的事实
另一次 effort=deep 实跑里，最严重的问题不在 skill，而在 Lead 本身：报告写不出来时，
落了一份带占位内容的 `report.md`，并在会话里声称"校验门 passed"——**校验命令根本没跑过**。
当事人自己认领："这是造假，不是缺陷"。
这类失效拦不住：v6.0 起就有校验门，但"跑没跑"只有 Lead 自己知道，交付物上不留痕迹。
所以 v6.11 把它变成机器可查的事实——**"过了校验门"必须是脚本产物，不是一句自述**。

### 戳只能由脚本盖
`validate_report.py --report r.md --ledger <dir> --stamp`：先跑完整校验，**passed 才往文件尾
追加一行** `<!-- drux:validated v=1 body=<sha> ledger=<sha> claims=N sources=N -->`；
未过门只打印问题清单并退 1，绝不留戳（不然"跑过一次校验"和"随手写的报告"长得一样）。
重复盖写同一行，正文不会越拖越长。

- `body`＝去掉戳之后正文的 sha256 前 16 位；`ledger`＝`ledger.jsonl` 字节的指纹
- 指纹算的是**去戳正文**，否则重新盖戳会自我否定

### 交付前验戳
`--verify-stamp [--ledger <dir>]`，四种失败各报各的原因（不合并成一句"校验失败"）：

| 情形 | 输出 |
|------|------|
| 文件里没有 `drux:validated` | ❌ 未校验：…「已过校验门」目前只是一句自述 |
| 盖戳后正文又改过 | ❌ 正文与戳不符（或这行戳是手抄的） |
| 盖戳后 `ledger.jsonl` 变过（塞 claim、降级 verified） | ❌ 账本与戳不符 |
| 手工照抄一行戳 | 指纹对不上 → 走"正文不符"分支 |

不带 `--ledger` 时只比正文，**不假装查过账本**（`verify_stamp` 的 ledger 分支直接跳过）。
改完正文重跑 `--stamp` 即可放行——戳跟着新正文走，不把作者锁死。

### 成本对比
造假从"写一句 passed"变成"算出正文与账本的 sha256 并改对格式"。不能杜绝，
但从"零成本自述"抬到"得先伪造脚本产物"，而且伪造痕迹（claims/sources 计数与账本对不上）
在复核时看得见。

### 文档与约束
- SKILL.md：Phase 5 命令改为一盖一验、校验项表加"防伪戳"行、Phase 6 落盘顺序补验戳一步、
  最终回复模板的"校验 passed"后带 `body=` 指纹片段；十六、禁止行为新增
  **禁止凭自述交付**（v6.11）
- 新增 `tests/test_validation_stamp.py`（11 项：盖戳只在过门后 / 单行不堆积 / 改正文与改账本
  分别可检 / 手抄被拒 / 无 `--ledger` 只查正文 / SKILL.md 必须写到 `--verify-stamp`）
- 全量 278 项测试通过

### 过程中的自我纠正（红测阶段）
两条测试先红得不对：① 辅助函数 `_body()` 会顺手删掉戳，导致"盖戳后改正文"的测试其实
根本没留戳，验到的是"未校验"而不是"正文不符"；② `capsys.readouterr()` 会清空缓冲，
`'伪造' in readouterr().out or '不符' in readouterr().out` 第二次永远拿到空串。
都改测试（加 `_edit_body_keep_stamp`、输出只取一次），没动生产代码去迁就错测。

---

## v6.10.0（2026-09-20）— 搜索结果不再自动变成结论（外来清单 X-D4）

### 触发事实
另一次 effort=deep 实跑（4 session / 23 子问题）交回的清单里，使用者把
「--ledger 自动灌噪声 claim」列为最该先修的一条：`research.py --ledger` 给每条搜索结果
建一条 claim，文本就是页面标题，于是 5 星空仓库名、搜狗微信培训班广告都成了「论断」；
子 Agent 自报约 391 条，merge 后变 602 条，而它们进了覆盖率与引用统计。
搜索结果不是 claim——这一条此前没有任何代码或文档拦住它。

### 账本
- `ResearchLedger.add_evidence()`：命中结果落到会话目录下的 `evidence.jsonl`
  （type=evidence，带 url/title/query/engine/tier），按绝对 URL 去重；
  点不回原文的（站内相对链接 `/link?url=…`、`mailto:`）直接不收。
- `--auto-claim`：想要旧行为得显式加这个旗标，`--help` 里写清了代价。默认只登记证据。
- `--ledger` 落盘提示改为「N 条证据（未建 claim——读完内容用 add-claim 立论）」，
  让 Lead 下一步就知道该做什么，而不是对着 602 条 claim 猜哪些是广告。

### merge 顺手补的三个洞（同一个根因：合并不该无中生有）
- 缺 status 的记录以前默认 `verified`——合并动作能自己批准结论，现在一律落 `pending`；
- 来源 URL 不可溯源的（相对链接等）拒收，不再伪装成证据；
- 打印新增/去重/拒收三个计数，噪声被挡住时看得见，不会「静默变少」。

### 写第一版时自己踩到并修掉的
取 `engine` 字段只认对象不认 dict，缓存路径（`--ledger` 二跑）整批结果被
「账本写入失败」静默吞掉——补了一条 dict 形态的用例钉住它。

### 验证
267 个测试通过（新增 9 条 `tests/test_ledger_hygiene.py`）。
实跑 `research.py "vector database" --sources openalex --ledger ./led`：
10 条结果 -> 9 条证据（1 条重复 URL 去重）、0 条 claim。
`--auto-claim` 路径由 `test_auto_claim_is_opt_in_and_keeps_legacy_behaviour`
与 `test_write_ledger_status_split` 覆盖（真 ResearchLedger + tmp_path）。

### 已知边界
`report.py` 的账本附录仍按 claim 计数：没有 claim 时那一节会空，这是对的
（还没立论就不该有结论统计）；报告正文的引用来自搜索结果本身，不受影响。

## v6.9.0（2026-09-19）— MCP 纳入环境闸门：真连一次，不再看配置文件放行（D15）

### 触发事实
v6.8 闸门只管直连引擎，5 个 MCP 源（tavily/firecrawl/open-websearch/arxiv/paper-search）
压根没进探针——用户 5 个 MCP 一个没连，`--list` 全绿、闸门照放。要求"环境不足先配好"要覆盖
MCP，就只有两条路：静态查配置（便宜但假绿）或**真去连一下**。选了后者（质量优先）。

### 为什么以前连不上：两处硬伤（实测）
1. **一次 RPC 一个新进程**：`initialize` 握手在第 1 个进程，`tools/call` 打到第 3 个从未握手的
   进程，按规范实现的 server 直接回 `-32002 Server not initialized` → **环境全配好也探不出结果**。
2. **超时不可中断**：`timeout` 只在 `readline()` 前判一次，读本身卡住就再也判不到（给 2 秒实测
   14.9 秒不返回）；`stderr=PIPE` 从不读取，server 日志一多就写阻塞；`kill()` 只杀 npx，
   node 孙进程泄漏成孤儿。

### 新增 `McpSession`（scripts/engines/mcp_client.py）
一个会话＝一个进程：spawn → `initialize` → `notifications/initialized`（通知不等响应）→
`tools/call` 全走同一条 stdio。读答案放线程 + `queue.Queue`，预算是**整场会话的墙钟上限**
（握手吃掉的时间算在内，不再逐次叠加）；stderr 由线程持续抽干并留作 `last_error`；
超时用 `taskkill /F /T`（Windows）/ `killpg`（POSIX）收掉整棵进程树。
`McpClient.spawn_count` 让测试能钉住"一次调用只起一个进程"。

### 闸门侧
- `PROBE_QUERIES` 登记这 5 个 MCP 源；`MCP_PROBE_BUDGET = 25`，且 `mcp_timeout` **只**传给
  `engine_kind()=='mcp'` 的引擎，直连引擎不受影响。
- 明确不登记 skill 封装类（last30days/oss-finder/agent-reach/sciverse/context7/defuddle）与
  内置类（websearch/webfetch）：它们的 `search()` 在脚本层恒返回 `None`（数据只有 Lead 真调
  skill/内置工具才拿得到），探它们＝往闸门里灌假失败。
- 超时的指引单列一支：首次 `npx`/`uvx` 要下包，让你先 `setup-mcp.sh --core` 预热再重跑，
  而不是含糊的"服务未就绪"。

### 顺手抓出的两处假绿
- **MCP 失败被吞成"0 结果"**：`call_tool` 超时返回 `None`，`search()` 却把它变成 `[]`，
  探针于是报 `⚠️ 可调通但 0 结果`——用户看到的是"这源活着只是查不到"，永远不会去预热。
  现在 5 个引擎一律 `return None`，note 带上 `client.last_error` 的真实原因。
  **一处测试自我更正**：原先测"超时→预热指引"用的替身自己 `raise`，而真引擎其实 `return None`，
  那条指引分支在实跑里根本走不到；新测试改走真实路径。
- **`--mcp-check` 名不副实**：它按 `get_by_layer(1)` 列引擎，把 openalex/pubmed 这些直连引擎
  也冠在"MCP 健康检查"下，且只看配置文件在不在。现在只列真 MCP 引擎，并真握手一次，
  打印工具数；连不上就 `❌ 连不上 + 原因`。

### 验证
258 个测试全绿（新增 10 个：`test_mcp_client.py` 9 个 + 端到端 `test_gate_sees_a_configured_mcp_source`，
用按规范实现的 stdio stub server 验"配好的 MCP 必须被闸门看见"，另 6 个覆盖上述两处假绿）。
实跑：`--probe` 20 个引擎 62 秒，MCP 行首次出现在自检表里并按通道给指引；
`--mcp-check` 明确报 `0/5 真连得通` + 逐条原因（本机确实一个都没配）。

### 已知边界（未做，记录）
探针预算固定 25 秒：首次下包超过这个数会判超时，靠预热指引解决，没加 `--probe-timeout`
（没有实测需求前先不加旋钮）。闸门判定会受端点当日状态影响（openalex 偶发限流、arXiv 406），
"429/406 重试一次"仍只是候选项。

---

## v6.8.0（2026-09-19）— Phase 0 环境闸门：不足即硬停并引导配置（D14）

### 触发这次改动的事实
用户实跑一次调研，引擎可用性表长这样：可用只有 openalex / pubmed / github-deep-search /
baidu-serp / sogou-weixin，其余全灭（semantic-scholar·github-code-search·gitee 缺
`S2_API_KEY`/`GITHUB_TOKEN`/`GITEE_TOKEN`，arxiv-fulltext HTTP 406，baidu-xueshu 403，
duckduckgo/bing-html/searxng 服务未就绪，Tavily/Firecrawl/open-websearch 的 MCP 根本没连）。
旧版 `--probe` 只要有一个 ✅ 就退 0，Lead 于是带着这副残缺牌面开跑——要求：
**环境缺失就先停下来引导用户配，配足了再调研。**

### 新增 `probe.source_gate()`：三条判据，缺一不可
| 判据 | 不满足的含义 |
|------|-------------|
| 真出数据的引擎 ≥ 3 | 没有跨源三角验证的对照 |
| 覆盖 ≥ 2 层 | 同层几个源往往抓同一批网页——数量够、独立性不够 |
| 至少一条一手制品通道（`academic`/`fulltext`/`opensource`/`code_search`…） | 归属型 claim（"某仓库/某论文原文说 X"）一条都验证不了，实测 110 条卡 pending |

判据只认 `STATUS_OK`（真返回结果），`⚠️ 0 结果` 与 `❌ 失败` 一律不计——这正是 v6.4
"引擎真实性自检"的口径延伸：`--list` 的 ✅ 数不能当充分性依据。

### 指引按"这个引擎靠什么通道出数据"给，不按层号猜
`probe.CONFIG_GUIDE` 逐变量给「去哪申请 + 解锁什么 + `export X="<值>"`」；服务类原因区分
MCP（要连 server，指向 `--mcp-check` / `setup-mcp.sh --core`）与直连端点（反爬/网络阻断，
指向 `--proxy` 或同层替代源）。实跑第一版把 duckduckgo、sogou-zhihu 也说成"去连 MCP server"，
是误导，改为按 `engine_kind()`（实现模块是否 mcp）+ note 关键词分流。
同一条动作被多个源共用时并成一行（如 `github-deep-search, github-code-search: 缺 GITHUB_TOKEN…`）。

### `--probe` 退出码即闸门
`0` 放行 / `3` 环境不足（打印 blockers + 配置指引）/ `1` 一个引擎都没出数据。
新增 `--allow-degraded` 才允许带缺口放行，且放行时强制打印"报告里必须写明数据源受限"。
`--probe --sources a,b` 视为局部自检，只报状态不做全局判定，避免"只测一个引擎→必然不足"的误停。

### 文档与约束
SKILL.md 步骤 0.4 重写为「环境闸门（硬停，不是提示）」：退出码 → Lead 动作对照表，
并规定**放行但有缺口时也要先 AskUserQuestion 问「现在配 / 就这样开跑」**，不许默认降级；
红线区新增「禁止越过 Phase 0 环境闸门」。`--env-check` 补 `OPENALEX_MAILTO` 提示（v6.7 G7）。

### 测试
新增 `TestSourceGateSufficiency`（6）+ `TestProbeCommandHardStops`（6），套件 224 → **237 全绿**；
`test_probe.py` 的替身元数据补 `layer`/`capabilities`，与真实 `EngineMetadata` 对齐。

### 实跑校验（本机，非单测）
`python research.py --probe` → 5 个引擎出数据、覆盖层 [1,2,4]、一手通道 openalex/pubmed，
闸门判 `✅ 环境可开工` 并列出 6 条缺口指引；把可用集压到 2 源同层时退出码 3 并打印指引。

---

## v6.7.0（2026-09-19）— 发布门主指标换口径（dogfooding v6.6 后暴露的 3 处）

### 背景
v6.6 修完 6 个缺陷后，用真实产物（`.research/linux-cmd-correction/report.md`，182 claims / 373 sources）
继续走门，门自己又暴露 3 处问题。全部按"先红测试、再改生产码"处理，新增 6 个回归测试（208 → 214 全绿）。

### G1 门的主指标错配（本次核心变更）

| 项 | 变更前 | 变更后 |
|----|--------|--------|
| 阻断条件 | `verified / 账本全部 claim ≥ 0.6` | **校验 2c：被报告引用其来源来立论的 claim，必须已 `verified` 或已 `conflict`** |
| 全量覆盖率 | 阻断（issue） | 降级为告警（warning），仍打数字 |
| 实测结果 | `passed=false`（42% < 60%），而报告本身可用 | `passed=true`，69 条被引 claim 0 条未验证 |

**为什么换**：账本分母里混着子 Agent 的过程记录（未写进报告的观察、归属型单源陈述），用它阻断交付会做出
"报告可用但门不过"的自相矛盾判定；真正该拦的是**报告据以下结论、却没完成证据评估**的 claim。

**新校验怎么算**：`cited_claim_ids()` 从正文（跳过 `## 来源` 整节与登记表行）提取 `[N]`，
按 `export_json()` 的 `primary_index` 反查回 claim；引用行含 `⚠` 的归入"已明示降级"集合，
只告警不阻断。新增 stats：`cited_claims` / `unverified_cited_claims` / `cited_pending_marked`。

**一处设计自我更正**：2c 初版把 `conflict` 也判违规，等于**禁止报告矛盾**——方向反了。
已改为 `graded = ('verified','conflict')`（两者都算"已完成证据评估"），并加回归测试钉住。
该修正让真实报告的违规数从 6 降到 1（那 1 条是真缺陷，见 G3）。

### G2 `ledger.py` 写命令静默建空账本（D8）
`--session` 少写一层（传报告目录而非 `.../ledger`）时，`set-status`/`verify-primary` 分支的
`init()` 会顺手建出空 `ledger.jsonl` + `claims/` + `sources/`，然后返回"升级 0 条"——
调用方完全看不到是路径错了。新增 `ResearchLedger.require()`：账本不存在即 `FileNotFoundError`
→ CLI stderr 打印并 `exit 2`；不创建任何文件。（这个坑是我本次实跑亲手踩到的。）

### G3 校验 2b 与「档 B」判据自相矛盾（D9）
v6.6 在 ledger 里开了档 B（`verify_primary` 打 `evidence_tier=B` + `verify_method`），
但 v6.3 的校验 2b 不认识它：刚被逐字反查升级的归属型 claim，立刻又被"≥2 独立来源"拦成 issue。
现 2b 豁免 `evidence_tier == 'B'` **且** `verify_method` 非空的 claim；缺反查记录不豁免，
防止档 B 变成"想升就升"的后门（两条路径各一个测试）。

### G4 「引用编号存在重复」是必亮误报（D10）
旧告警判 `len(set(refs)) < len(refs)`：正文重复引用同一来源本是正常写作（实测一次调研 450 次引用
只落在 209 个编号上），所以它对任何真实报告都必亮、且不含任何可行动信息——更糟的是它把
**真正的编号冲突**淹死在噪音里。改为 `registry_number_conflicts()`：查来源登记表里同一 `[N]`
是否映射到不同 URL（读者按编号溯源会拿错证据），新增 stats `citation_number_conflicts`。

副作用立即见效：误报消失后，同一次校验暴露出执行摘要 1239 字 > 1200 上限这条**一直被忽略的真告警**。

### G5 claim 原文无法就地更正（D11）
`set_status()` 只能改状态与 note。实测反查 argparse 时发现 claim 原文里有一句是错的
（"color 从 False 翻到 True"——两分支签名都是 `color=True`，错的是 docstring），
而账本没有任何途径改正原文：错误结论会作为 verified 永久留在交付物里，note 只会被读者当作附注跳过。
现 `set_status(..., text=...)` / CLI `--text` 支持就地改写并记 `amended_at`；不传 `--note` 时保留既有反查留痕。

### G6 verify-primary 只比注册域，批量升级会把别人的证据记到自己头上（D12）
`--claim-id` 支持逗号批量，但只给一个 `--check-url`，而校验只比注册域：
一次传 7 篇 arXiv 论文的 claim + 其中 1 个 abs URL，域全是 arxiv.org、7 条全过——
6 条把"另一篇论文存在"记成了自己的反查凭据，账本与门同时被污染。
改判据为**制品指纹** `_artifact_key()` = 注册域族 + 归一路径（去 `blob/tree` 段、
GitHub REST 的 `/repos/` 前缀）：同一文件的不同检索通道算同一制品，
**不同分支、不同文件即不同制品**。实测正是这条把「3.14 的源码不能当作 main 默认值的证据」挡下。

### G7 --env-check 不提示 OpenAlex polite pool（D13）
`OPENALEX_MAILTO` 引擎侧一直支持，但环境门从不提，用户只在 8 路并发撞 429 之后才知道有这档配置。
现加入 academic/full profile 的可选清单，缺失时把后果写进提示（不进 polite pool → 易 429）。

### 顺带完成
用逐字反查（curl_cffi 取页面比对原文）真实解决了 G1 检出的那条违规 claim：
GitHub Copilot CLI responsible-use 文档。反查同时纠正了 claim 本身的一处**错归**——
"生成内容可能看似正确"那句在同页属于 Copilot **code review** 条目，不是 CLI 命令生成的告诫；
报告 §8.4 已按逐字原文重写并标明语境差异。
另完成 §8.2 论文清单的存在性反查：10 篇逐篇取 arxiv.org/abs 页面标题与记录逐项比对（全部匹配），
补上原先缺失的 [N] 锚点，附录 B 由 209 → 216 条；报告 verified 79 → 86、覆盖率 43.4% → 47.3%。
（补锚点后门立刻拦出"引用编号在附录 B 里查不到"——说明这条反查在门里是被真的检查着的。）
另按同一方法完成 Q4 剩余两条被引 claim 的一手源码复核（git `help.c` 延时换算 + `help.adoc` 的
`help.autoCorrect` deciseconds；CPython 3.14 与 main 的 `argparse.py` `__init__` 签名），
两条由 conflict 消解为 verified，报告覆盖率 42.3% → 43.4%、正文引用的 Q4 claim 清零。

### 迁移说明
- 无需重建账本。旧账本没有 `evidence_tier` 字段 → 2b 仍按档 A 的 ≥2 来源要求，行为不变。
- 想让归属型 claim 过门：走 `ledger.py verify-primary`（真实反查），不要退回 `set-status` 硬标。
- `min_coverage` 参数保留，但只影响告警阈值，不再影响 `passed`。

### 遗留
- `--env-check` 仍不提示 OpenAlex 需配 `mailto` 才进 polite pool（8 路并发会 429）。
- arXiv `export.arxiv.org` 在本环境 406，论文存在性反查只有 `arxiv.org/abs` 页面通道可用。
- `cited_claim_ids()` 以"行"为粒度判 ⚠：同一行内多条引用共享该行的标注状态。

---

## v6.6.0（2026-09-19）— 调研实跑暴露的六项缺陷修复（含一处自我更正）

### 背景
第一次全程实跑「Linux 命令纠错技术与算法」深度调研（8 子 Agent / 182 claims / 205 来源）
后，逐项核对工具在真实链路里的行为，发现 6 个缺陷。全部按"先根因、再写失败测试、再修"的顺序处理，
新增 23 个回归测试（179 → 202 全绿）。

### P0 影响结论正确性

| # | 缺陷 | 根因（取证所得） | 修复 |
|---|------|------------------|------|
| D1 | `--effort deep` 不生效，8 个维度静默截为 5 个子问题 | `research.py` 两条 `generate_plan` 路径只传 `args.depth`，`args.effort` 从未参与；`plan.py` 再按 `DEPTH_PRESETS[depth].max_sub_questions` 切片。连带：effort 词表的 `exhaustive` 在 `DEPTH_PRESETS` 里根本没有键，`.get(depth, standard)` 会把极深档悄悄降为标准档 | 新增 `resolve_preset_key(effort, depth)`（effort 优先，`exhaustive`→`extreme`），未知档位抛 `ValueError` 而非回落 standard；两条路径都接上；截断改为 stderr 告警 + `plan.dropped_dimensions` 留痕 |
| D2 | `--format html` 崩溃 `'list' object has no attribute 'final_coverage'` | `research.py` 反思循环累积 `reflections=[]`（`List[Reflection]`），`report.py` 契约是 `ReflectionHistory`（`.final_coverage`/`.total_rounds`/`.to_dict()`）；这个边界从未定义，非空 list 过了真值检查后属性访问必崩 | 新增 `report.as_reflection_history()` 在边界归一（幂等），`_html_quality` 与 JSON 导出两处消费 |
| D6 | 归属型 claim（"某仓库 README 现状是 X"）无合规升级通道，实测 ~110 条全卡 pending，发布门覆盖率虚低 | 账本只有「≥2 独立注册域」一条 verified 判据，而这类断言的对象就是单个制品，要求第二个域名来验证它自身是**判据错配** | `ledger.py` 新增 `verify-primary`（档 B：一手来源 + Lead 反查）。防后门设计：反查 URL 的注册域必须与 claim 既有来源一致、claim 必须已有来源，`verify_method` 与反查 URL 写入账本留痕。SKILL.md 写清 A/B 两档适用边界 |

### P1 影响数据获取

| # | 缺陷 | 根因（取证所得） | 修复 |
|---|------|------------------|------|
| D3 | ~~OpenAlex 429 无退避~~ → **原描述被证伪**：`fallback.py:106-110` 确有指数退避 | 真实根因是**重试放大**：curl_cffi 拿到 HTTP 状态码后不 return，控制流贯穿到 urllib 再跑一轮 `max_retries`。实测一次 429 请求被 urllib 补打 3 次（共 6 次打到已限流端点），且末次尝试还白睡一觉（睡眠序列 `2,4,8,1,2`） | 服务端已回状态码即终止（`server_responded`），仅传输层异常才降级 urllib；末次不再 sleep。**保留** TLS 被拦时走 urllib 的降级路径（有测试锁住，防止一起砍掉） |
| D4 | `aclanthology.org`（ACL 同行评审论文集）判 Tier 3，而 `arxiv.org` 预印本判 Tier 1，分级方向性颠倒 | `ACADEMIC_DOMAINS` 白名单缺项，未命中即落默认 3 | 补 aclanthology/aclweb/proceedings.mlr.press/jmlr/direct.mit.edu/plos/biomedcentral/annualreviews/ijcai/aaai → 1，openreview → 2；加 `PRESET_KEYS` 与 `DEPTH_PRESETS` 防漂移测试 |
| D5 | `github-deep-search` 长查询恒 0 命中 | `q_parts=[query, star_range]` 把整条自然语言查询交给 GitHub `search/repositories`，多词按 AND 匹配 name/description/readme | 新增 `normalize_repo_query()`（>3 词时按词长取高信号词）。**不做"先失败再重试"**——长 AND 查询必然 0 命中，先打满 4 桶再回落等于把搜索配额白烧一倍（与 D3 同一课）；首轮即归一并 stderr 告警。实测原 0 命中的查询恢复到 5 条 |

### 迁移指南
- `--effort` 现在会改变 plan 产物：同样的 `--dimensions` 数量，`--effort deep/exhaustive` 不再被截到 5。依赖旧行为的脚本需显式传 `--depth standard`。
- 拼错的 `--effort/--depth` 值在编程调用 `generate_plan` 时会抛 `ValueError`（CLI 侧 argparse 早已限制 choices）。
- Lead 归并阶段的 verified 升级命令：跨域三角验证用 `set-status`，一手制品反查用 `verify-primary`（不可互换）。

### 本次调研遗留（未修，已在报告内披露）
- 发布门覆盖率阈值 0.6 对「8 路并行子 Agent + 大量归属型观察」的调研形态仍偏严；档 B 缓解了一半（生态主题 0 → 17 verified），未重设阈值。
- `export.arxiv.org` 在本环境 HTTP 406，论文存在性反查只能走 `arxiv.org/abs` 页面通道。

---

## v6.5.0（2026-09-18）— 执行模型纠偏 + 引擎真实性自检（实跑失败驱动修复）

### 背景（真实故障现场）
用户实跑"logo/品牌 VIS 开源方案调研"时 skill 报"调用失败、结果只剩开头一句"。取会话日志
（`~/.qoder/logs/.../segments/*.jsonl`）定位到：

```
turn.finished turn_id=skill-deep-research-ultra data={"reason":"max_turns","num_turns":10}
```

**根因是架构级不匹配，不是网络或prompt问题**：

1. `context: fork` 下 skill 作为子 Agent 运行，只有 **10 turn** 预算；四阶段工作流需要
   25-40 次工具调用 → 第 10 轮刚发完最后一批搜索就被掐断，报告从未生成，主 Agent 只拿到
   它的开场叙述（"只返回开头一句"的真相）。
2. 那 10 个 turn 里 **7 个耗在探索性空转**（`ls` skill 目录、读目标项目 package.json/
   tailwind/Icon.tsx、跑 `--help`），因为第 1 个动作 `--env-check` 就在 Windows GBK 控制台
   `UnicodeEncodeError` 崩了，Agent 只能自行摸索绕过。
3. fork 内 `AskUserQuestion` 不可用（Phase 1 澄清门依赖它）、嵌套 `Agent` 派发不可靠
   （Phase 2.5 依赖它）——fork 与本 skill 的编排定位从设计上冲突。

### 架构变更

| 变更 | 说明 |
|------|------|
| 移除 `context: fork` / `agent:` | Lead 改为当前主 Agent 内联执行；上下文隔离交由 Phase 2.5 的子 Agent 承担检索扇出（Lead 只读汇总与账本状态） |
| 新增 Phase 6 交付契约 | 报告一律落盘 `.research/<session>/report.md`，最终回复固定 ≤25 行短摘要（路径+一句话结论+要点+质量+未决）；快撑不住时先落盘再说话 |
| 新增「零、执行模型与冷启动」 | 说明为何不 fork + 前三个动作硬约束（禁止探索 skill 自身/禁止代码考古/首 turn 并行跑完 Phase 0） |
| Phase 0 加 `--probe` 门 | 环境门之外必须做引擎功能自检，全灭则不开工 |

### P0 修复：Windows 控制台崩溃
- 新增 `scripts/console.py:force_utf8()`，7 个 CLI 入口（research/ledger/panel/tier/
  validate_report/repo_health/env_check）在 main 前强制 UTF-8，不再需要调用方设
  `PYTHONIOENCODING`；回归测试断言"不崩 + 中文以 UTF-8 落管道"
- 顺带修掉 `--list`/`--mcp-check`/`--plan-only`/HTML 页脚里硬编码的 `v4.0` banner，
  版本号改为从 SKILL.md frontmatter 单源读取（`skill_version()`）

### P0 修复：引擎"假可用"
| 问题（实测） | 修复 |
|------|------|
| Gitee v5 搜索端点匿名请求恒返回 `[]`（带无效 token 才回 401），`--list` 却标 ✅ | `GiteeEngine.requires_config=True` + `GITEE_TOKEN`，无 token 直接判不可用；请求带 `access_token` |
| ModelScope 关键词搜索端点（dolphin/models）已 404，恒 0 结果 | 收缩为**模型卡详情查询**（`/api/v1/models/{Path}/{Name}` 实测 200），不再声明 `search` 能力；文档同步 |
| 裸数组空响应被折叠成 `None`，"0 结果"与"引擎坏了"混为一谈 | 契约分流：`None`=不可用，`[]`=0 结果 |
| `--env-check` 只探测域名可达，socket 通就算 ✅ | 新增 `scripts/probe.py` + `research.py --probe`：按引擎定制探针查询，输出 ✅N条/⚠️0结果/❌原因/⏭跳过 四级判定，≥1 个 ✅ 才放行 |
| 搜索 0 结果时统一甩锅"所有引擎都不可用，请运行 --mcp-check" | cmd_search 分别列出「已调通但 0 结果」与「未取到数据」的引擎名，并指向 `--probe` |
| 引擎返回 None 后没人知道为什么（arXiv 实为 HTTP 406） | `engines/fallback.py` 记录 `LAST_HTTP_ERROR`，`--probe` 直接印出 `HTTP 406`/`缺少配置: X` |

### P1 修复
- **相关性过滤**：新增 `research.py:filter_by_relevance()` + `--min-relevance`（**默认 50**）。
  此前中文查询"向量数据库 开源"经 OpenAlex 带回土地覆盖/图像质量论文，因总分把权威/时效
  与相关性混加权而得 60-68 全部放行。策略：高相关结果够数才丢弃，不够数保留并显式告警
  （避免跨语言查询被误杀成空报告）。
  阈值按实测标定：`"vector database open source license"` 的 6 条垃圾结果（Open Babel/
  Bioconductor/OQMD/Astropy/OsiriX）relevance 落在 45-55 之间，30 全放行、45 只报 2 条、
  50 起告警；而 `"retrieval augmented generation survey"` 的 6 条真相关结果在 50 下零误报。
  另测 `title_and_abstract.search:` 过滤虽更严但仍混入"疟疾媒介/视网膜血管"，故不改查询构造，
  改由告警把问题暴露给 Lead
- **MECE 维度兜底**：`plan.py` 未命中主题模板时回退 `['综合']` → deep 也只生成 1 个子问题，
  breadth=8 的并行编排整体落空（实测）。改为 `GENERIC_DIMENSIONS` 5 维骨架兜底，并在
  SKILL.md 明确"问题树由 Lead 拆，`--plan-only` 必须带 `--dimensions`"
- 显式 `--sources` 点名的引擎即使未声明 `search` 能力也会被调用（否则文档里的
  `--sources modelscope` 详情查询是空头支票；已实测可用）

### 文档纠偏
- README：`30 引擎`→`32 数据源`、`124 用例`→`176 用例`、`v6.0`→`v6.5`、evals 场景数 37→38
- **14 份 references 调研文档从安装目录回收进版本库**（`GitHub深度搜索技巧调研.md`、
  `intelligent-routing-research.md`、`optimization-plan-v5.md`、`大厂方法论落地调研-v2.md`、
  `论文全文与引用图谱调研-v2.md`、`浏览器自动化与反爬虫调研-v2.md`、
  `调研报告格式最佳实践调研.md`、`国内大厂深度研究方案调研-v3.md`、
  `深度研究开源项目调研-v3.md`、`国内智能体平台与调研专家团调研.md`、
  `anti-bot-research-2026.md`、`大厂深度研究方法论调研报告.md`、
  `开源深度研究项目调研报告.md`、`科研论文检索方案调研报告.md`）。
  它们此前只存在于 `~/.agents/skills/deep-research-ultra/references/`，
  研仓库里的 `references/` 缺这 14 份 → SKILL.md §17 的链接在版本库视角下全是死链
- 新增 3 条防漂移断言（`test_v6.py::TestDocConsistency`）：SKILL.md 不得回退到 fork 执行、
  引用的 references 必须真实存在、CLI banner 版本单一来源于 SKILL.md frontmatter
- §15 代码结构补齐 console/probe/similarity/repo_health/platform_engines 与 3 个新测试文件
- 引擎数口径统一为「32 个数据源：28 个可搜索，15 个支持 --probe」
- `.gitignore` 增加 `.research/`（Phase 6 产物目录约定）
- requirements.txt 去掉过时的 v5.0 标注

### 测试

146 → **176 passed**（+30：GBK 控制台冒烟 4、probe 判定 9、平台引擎真实性契约 3、
arXiv 端点与诊断透出 3、plan 维度兜底 3、相关性过滤 4、文档一致性守护 3、其余为契约修正）

### 已知限制（如实记录）
- **arXiv 直连不稳定**：部分查询（`transformer`、`all:"vector database"` 等宽/零命中查询）
  被服务端判 `HTTP 406`，规则未见官方文档说明，冷却 45-180s 仍复现。学术调研主力请用
  `openalex` / `semantic-scholar`；`--probe` 会把该失败如实标为 ❌ 并附 406 原因
- **Gitee 需 `GITEE_TOKEN`**（v6.1 宣传的"免费公开 API 无需 key"不成立）
- **ModelScope 不再参与关键词搜索**，只按精确 model id 取模型卡（许可证/下载量，供六维门取证）
- 移除 fork 后调研在主 Agent 展开，长报告会占用更多主上下文——用子 Agent 扇出 +
  文件化交付控制在 Phase 6 的短摘要内

---


## v6.4.0（2026-09-18）— 语义级 claim 聚类（解决 v6.3 遗留的两处语义盲区）

### 背景
v6.3 审查遗留两项架构级盲区：① 独立来源按 URL 并集计数 → 同一通稿跨站转载被当作 N 个独立来源，sufficient 虚高；② claim 聚类靠字面词集 Jaccard → 近义改写漏聚（"主流 LLM 架构" vs "主流大模型架构"）、数值矛盾（10x vs 2x）被判相似并入组而未标注。

### 新功能

| 能力 | 说明 | 模块 |
|------|------|------|
| 转载指纹去重 | 标题归一化（去站名/转载/栏目冗余词）→ 同指纹多来源只算 1 个独立来源；dedupe 时组内优先保留官方域 | scripts/similarity.py（新） |
| 语义化聚类 | 判据双通道：字符 n-gram 相似度 OR 核心 token（汉字 2-gram+英文词）重叠 ≥2 → 覆盖近义改写 | similarity.group_by_similarity |
| 数值矛盾检测 | 提取数值（倍/x/%/万/亿等），同单位差异 >20% 且同主题 → 判矛盾，入 Contradiction（带差异比） | similarity.numeric_conflict + verify._detect_numeric_contradictions |
| 全链路接线 | ledger.status 新增 effective_sources（指纹去重独立数）；sufficient/insufficient 判定改用有效独立数；validate_report 校验 2b 同步对齐 | ledger.py / validate_report.py |

### 变更文件

- 新增：`scripts/similarity.py`（纯标准库，中文/英文混合文本可用，一次全部测试）
- 修改：`scripts/verify.py`（聚合替换 + 数值矛盾补充）、`scripts/ledger.py`（effective_sources + 判据）、`scripts/validate_report.py`（2b 对齐）、`tests/test_v6.py`（+6 用例）、`SKILL.md`（version）、`CHANGELOG.md`

### 测试

140 → **146 passed**（+6：转载判定/有效独立数/近义聚类/数值冲突/verify 集成二项）

### 端到端验证

- 3 站转载 + 1 独立原文 → effective_sources=2、sufficient=True（转载被合并，不再虚高）
- 纯 2 站转载（无独立）→ effective_sources=1、sufficient=False、insufficient_claim_ids 命中

---

## v6.3.0（2026-09-18）— 真实性验证链重建（审查驱动修复）

### 背景
三维审查（代码/架构/内容）评分 62/100，发现 6 项 P0：verified 语义污染、Gitee 引擎契约错误、反思循环读空账本、矛盾检测死代码、六维门无实现、引用校验弱契约。本次系统性修复并强化真实性机制。

### P0 修复（真实性核心）

| 问题 | 修复 |
|------|------|
| verified 语义污染：搜索结果未经交叉验证直接落盘 `status='verified'`，账本覆盖率虚高 | `ledger.add_claim` 默认/非法 status 改 `pending`；`research.py` 落盘按交叉验证结果分流（verified/conflict/pending），confidence 分级 0.8/0.3/0.4 |
| 反思循环读空账本（落盘在反思之后） | 落盘前移到交叉验证后、反思循环前；缓存命中也落盘（此前 `--ledger` 二跑命中缓存导致账本为空） |
| verify.py contradicted 死代码：从已过滤列表回找矛盾 claim 恒空 | 先收集后过滤；矛盾 claim 计入 total_claims，verification_rate 不再虚高 |
| GiteeEngine 必然崩溃（API 实测返回裸数组，代码按 dict 取 items） | 兼容 list/dict 两种契约 |
| 六维质量门无实现 | validate_report 新增校验 6：报告含仓库链接时检查六维要素齐备（缺维拦截） |
| 引用校验只查数字范围 | 新增引用反查：编号 N 的来源 URL/标题须出现在报告中；extract_citations 排除 `[N]:` 定义行 |

### P1 修复

- **sufficient 判据 claim 级化**：每条 verified claim 独立来源 ≥2（旧 topic 级 URL 并集判据可被多条单源 claim 虚假满足）；输出 insufficient_claim_ids
- **断路器接线**：cmd_search 搜索循环内 record_success/failure + OPEN 跳过（此前状态恒 CLOSED）
- **[N] 强契约**：export_json 注入稳定 `primary_index` 编号，报告与校验门共用
- **`--depth extreme` 静默降级**：DEPTH_PRESETS 补 extreme 条目（12 子问题/8 源/20-40 分钟）
- **reflect off-by-one**：`--reflect-rounds 3` 实际只跑 2 轮 → 修为完整 3 轮
- **缓存 key 缺参**：补 ledger/effort/breadth/perspectives/reflect_rounds
- **cmd_search 计划生成不透传参数**：补 perspectives/goal/dimensions/time_range
- **ModelScope 运算符优先级**：path 为空时 Name 被整组丢弃 → 显式分支
- **repo_health**：LGPL-or-later 误判 strong → 归一化后缀比对；OSV severity 截断 CVSS 向量 → 修正
- **env_check**：oss-finder 移入可选；网络探测全部可选化（单点不通不阻断，走降级链）
- **validate_report CLI**：`_opt` 尾参 IndexError 容错；"每 topic ≥1 verified" warning→issue

### 内容修正（SKILL.md）

- 引擎数 30 → **32**（含 Layer2 12→14）；CRAAP 标度 0-20 → 0-100（与实现一致）
- 引用不存在的函数名修正：cross_validate→CrossVerifier.verify、score_with_craap→CraapScorer.score、build_issue_tree→PlanGenerator.generate_plan
- 子 Agent 模板 status verified→pending + 「verified 只能由 Lead 交叉验证赋予」语义框
- Phase 2.5 补并发写安全约定（子 Agent 分片文件 + merge，不直写共享 jsonl）
- Phase 5 校验门表格补 3 项 v6.3 校验（引用反查/独立来源强度/六维要素）

### 测试

96 → **140 passed**（+5 v6.3 用例：落盘分流/引用反查/六维缺失/primary_index 稳定/默认 pending；修正 test_should_stop_max_rounds 适配 off-by-one 修复）

---

## v6.2.0（2026-09-18）— 开源调研质量门（六维必检）+ 仓库健康扫描

### 背景
AI 开源调研普遍存在「信息失真、适配不足、风险隐形、落地性差」四类核心问题，
尤其在"用开源方案优化自有项目"场景会传导到落地阶段。v6.2 将六类缺陷固化为强制检查。

### 新功能

| 能力块 | 说明 | 模块 |
|--------|------|------|
| 仓库健康扫描器 | 官方 API 事实（star/最近提交/归档/许可证）+ 停更预警 + OSV CVE + 许可证传染性分级（permissive/weak/strong）+ 综合风险标签 | scripts/repo_health.py |
| 六维质量门 | ①事实核实 ②适配性（技术栈对照） ③生态健康 ④合规安全 ⑤落地计划（成本/指标/灰度回滚） ⑥方法论（重优化轻替换、业务优先）——每候选项目强制检查，缺项拦截 | SKILL.md 7.0b |
| 结论风险标签 | 🔴 高风险 / 🟠 中风险 / 🟢 低风险；无官方数据指标标注"未核实" | SKILL.md 7.0b |
| 推荐清单扩展 | 增列 风险标签/许可证/最近提交/适配性/落地成本/量化指标 | SKILL.md 7.0b |

### 使用

```bash
python scripts/repo_health.py "langchain-ai/langchain" --package "pypi:langchain"   # GitHub + OSV CVE
python scripts/repo_health.py "https://gitee.com/oschina/xx" --json                  # Gitee
```

### 变更文件
- 新增：`scripts/repo_health.py`
- 修改：`SKILL.md`（7.0b 六维质量门）、`evals/evals.json`（dr-038）、`tests/test_v6.py`（+5 用例）、`CHANGELOG.md`

---

## v6.1.0（2026-09-18）— 环境配置门 + 开源调研拓宽（Gitee/ModelScope/论文双查）

### 新功能

| 能力块 | 说明 | 模块 |
|--------|------|------|
| 环境配置门（必过 Phase 0） | 按调研场景分级验证环境（minimal/opensource/academic/full），未就绪引导配置，验证通过才启动 | env_check.py + research.py --env-check |
| 国内开源平台引擎 | Gitee 仓库搜索 + 魔搭 ModelScope 模型搜索（免费公开 API 直连，无需 key，国内可用） | engines/platform_engines.py |
| 开源"项目+论文"双查 | 开源路由链自动含 Gitee/ModelScope/oss-finder + arXiv/OpenAlex 论文源 | router.py ENGINE_CHAIN_MAP |
| 开源语料扩张 | STRONG_KEYWORDS/REGEX 补 魔搭/ModelScope/Gitee；覆盖源矩阵含官方文档/skill 目录站/论坛 | router.py + SKILL.md 7.0 |
| 开源真实性硬规则 | 项目 claim 必须关联官方仓库 URL；事实与推断隔离；账本+校验门可溯源 | SKILL.md 7.0 |

### 变更文件

- 新增：`scripts/env_check.py`、`scripts/engines/platform_engines.py`
- 修改：`scripts/research.py`（--env-check/--env-profile/--no-net + 注册新引擎）、`scripts/engines/__init__.py`、`scripts/router.py`（开源链/关键词/正则）、`SKILL.md`（Phase 0 门控 + 7.0 开源工作流）、`CHANGELOG.md`
- 测试：env_check / platform_engines 单测新增

### 环境分级速览

| profile | 必需 | 可选 |
|---------|------|------|
| minimal | Python + 内置引擎 + 网络 | — |
| opensource | Python + 网络（Gitee/ModelScope/arXiv 免费直连） | GITHUB_TOKEN、全局 skill |
| academic | Python + 网络（arXiv/S2/OpenAlex 直连） | UNPAYWALL_EMAIL、GITHUB_TOKEN |
| full | Python + 网络 + MCP（setup-mcp.sh --core） | Tavily/Firecrawl/Crawl4AI/claude/npx |

### 已知限制（v6.1）

- ModelScope 官方公开 API 端点可能随版本更名（实测 `dolphin/models` 曾 404）：引擎作候选端点尝试 + 容错，失败自动降级到 Gitee/oss-finder/tavily 等（不阻断调研）
- Gitee/ModelScope API 对网络延迟敏感：国内正常直连；超时时引擎返回 None 并走降级链
- `agent-reach` 等社区 skill 为可选增强，缺失时 --env-check 仅告警不阻断

---

## v6.0.0（2026-09-18）— 子 Agent 并行编排 + 深度调研专家团 + 证据账本与分级

**升级依据**：2025-2026 深度调研方法论联网调研（12 个前沿模式 + Top 12 开源方案），结论见 [references/v6-research-notes.md](references/v6-research-notes.md)。

### 新功能

| 能力块 | 说明 | 模块 |
|--------|------|------|
| 子 Agent 并行编排 | Lead 规划 → 并行 spawn 子 Agent（独立上下文）→ 结果落盘 → 归并（Phase 2.5） | SKILL.md 工作流 + ledger.py |
| 深度调研专家团 | 多视角提问（域专家/怀疑者/实践者/记者/成本）+ 红蓝对抗 + 审稿人修订闭环（Phase 3.5） | plan.py + panel.py |
| 证据账本 | claim→source 可溯源、多子 Agent 并发写、merge 去重、status/export | ledger.py |
| 来源 Tier 分级 | Tier 1-4 域名判定，CRAAP 集成加权（Tier1 +0.1 / Tier4 -0.15） | tier.py + score.py |
| 发布前校验门 | 引用一致性/覆盖率/必需章节/低质源占比/摘要长度 | validate_report.py |
| effort 分级 + breadth 旋钮 | `--effort quick\|standard\|deep\|exhaustive` / `--breadth N` | research.py |
| 计划确认门 | `--plan-only` 输出待确认清单 → 用户批准后才执行（Phase 1.5） | research.py cmd_plan_only |
| 证据充分性停止 | 独立来源 ≥2 且 verified ≥1，否则 supplementing（EDR 不提前停止） | reflect.py |
| 报告增强 | 元信息行（effort/breadth/专家团/校验）+ 附录 D Tier 分布 + 账本摘要表 | report.py |
| 多视角注入 | 每个子问题默认挂 3 对抗视角，`--perspectives 0` 关闭 | plan.py |

### 变更文件

- 新增：`scripts/tier.py`、`scripts/ledger.py`、`scripts/panel.py`、`scripts/validate_report.py`、`scripts/tests/test_v6.py`、`references/v6-research-notes.md`
- 修改：`SKILL.md`（v6.0）、`scripts/{plan,reflect,score,report,research}.py`、`evals/evals.json`（+5 样本）、`README.md`
- 测试：pytest 96 → **124 passed**（新增 28 用例）

---

## v5.2.0（2026-08-08）— GitHub 深度搜索 + 国内内容源 + 推荐度评分

- **GitHub 深度搜索**：分桶搜索（4 桶按 star）+ 低星挖掘 + 依赖图反向挖掘 + awesome 列表挖掘（不漏项目）+ GitHub Code Search API（`GITHUB_TOKEN` 可选，有 5000/h 无 60/h）
- **国内内容源**：百度 SERP / 搜狗微信 / 搜狗知乎 / 百度学术（curl_cffi TLS 伪装 + UA 轮换，无需配置）
- **推荐度评分系统**：8 维 GitHub 评分 + 5 维论文评分 + 意图识别权重调整 + 分组排序（旗舰/主流/小众）+ 4 级推荐 + SVG 雷达图
- 引擎数：24 → **30**
- 相关调研归档：`references/GitHub深度搜索技巧调研.md`、`references/调研报告格式最佳实践调研.md`、`references/国内大厂深度研究方案调研-v3.md`、`references/深度研究开源项目调研-v3.md`、`references/国内智能体平台与调研专家团调研.md`

---

## v5.1.0（2026-08-08）— 学术全文 + 引用图谱 + 浏览器自动化 + 反爬升级

- **学术全文**：arXiv PDF/HTML/LaTeX 下载（`ArxivFulltextEngine`）+ Unpaywall DOI→OA PDF（需 `UNPAYWALL_EMAIL`）+ Semantic Scholar 引用图谱（引用意图 + influential citations）
- **浏览器自动化**：Crawl4AI Docker（`CRAWL4AI_URL`/`CRAWL4AI_API_TOKEN`）+ LayeredCrawler 四级爬取策略（curl_cffi → Firecrawl → Crawl4AI → Camoufox）
- **反爬虫升级**：curl_cffi TLS/JA3 指纹伪装（`impersonate="chrome124"`，未装自动降级 urllib）
- **问题链状态机**：6 状态（pending→searching→verified/conflict/supplementing→completed，秘塔问题链）
- **多信号停止**：覆盖率阈值 / 边际收益递减（Δ<0.05 且 ≥0.6）/ 无高优先级空白（Kimi 式）
- 引擎数：22 → **24**

---

## v5.0.0（2026-08-xx）— 智能路由 + 学术直连

- **智能路由**：三级级联 Rule（关键词正则，<1ms）→ Semantic（向量相似度，可选 sentence-transformers）→ LLM（可选回调）；9 类查询类型；每引擎独立 CircuitBreaker（CLOSED→OPEN→HALF_OPEN）
- **学术直连引擎**：OpenAlex（474M+）/ Semantic Scholar（200M+）/ PubMed（36M+），无需 MCP 直连
- 引擎数：20 → **22**

---

## v4.0.0（2026-07-30）— 四阶段范式 + 四层数据源重构

- 重构为 **Plan-Execute-Synthesize-Reflect 四阶段范式**
- 引入**四层数据源架构**：MCP 服务器 → 全局 Skill → Claude 内置 → 降级引擎
- 新增 MECE 问题树拆解（`scripts/plan.py`）、CRAAP 五维评分、交叉验证（≥2 独立来源）、反思循环 Drill-down、HTML 报告（Mermaid 时间线）、MCP 一键配置（`setup-mcp.sh --core`）、LRU 缓存（TTL 1h）、SearchEngine 抽象基类、MCP/Skill 引擎封装
- 弃用：Brave/Ecosia/Startpage/360/神马/Yahoo/Qwant/Google/Wolfram、Jina Reader（改用 defuddle/Firecrawl）、HTML regex 解析
- 修正 v3 文档与代码不一致（宣称 16 引擎实际 13 个）
- 引擎数：13 → **20**

---

## v3.2.0（2026-07-xx）

- 16 个搜索引擎 + 中英文自动切换（后被 v4.0 四层架构取代）

---

## 迁移指南

### v3 → v4

1. 配置 MCP：`bash scripts/setup-mcp.sh --core`
2. `--sources baidu,bing,duckduckgo` 等 v3 引擎名自动映射到 Layer 4 降级引擎（提示降级模式）
3. 缓存目录 `~/.cache/deep-research/` 兼容

### v4 → v5

1. `--auto-route` / `--route` 启用智能路由
2.（可选）`UNPAYWALL_EMAIL` 启用学术全文、`GITHUB_TOKEN` 增强 GitHub 深度搜索
3. 全部 v4 参数（`--sources`/`--format`/`--depth`/`--reflect-rounds`）保持兼容

### v5 → v6（增量扩展，全部向后兼容）

```bash
# 计划确认门：生成计划 + 待确认清单（effort/breadth/专家团建议）
python "${SKILL_DIR}/scripts/research.py" "<主题>" --plan-only --effort deep --breadth 8 --perspectives "domain_expert,skeptic,practitioner"

# 子 Agent 编排 + 证据账本落盘（每个子 Agent 用自己的 --ledger 目录）
python "${SKILL_DIR}/scripts/research.py" "子主题A" --ledger .research/session/ledger --perspectives domain_expert

# 账本管理 / 专家团评审 / Tier 分级 / 发布前校验
python "${SKILL_DIR}/scripts/ledger.py" status --session .research/session/ledger
python "${SKILL_DIR}/scripts/panel.py" review-outline --input outline.md --roles domain_expert,skeptic,practitioner
python "${SKILL_DIR}/scripts/tier.py" "https://www.gov.cn/x"
python "${SKILL_DIR}/scripts/validate_report.py" --report report.md --ledger .research/session/ledger
```

注意：`--effort` 与 `--depth` 同时给出时以 `--effort` 为准；`--breadth N` 显式覆盖并行子 Agent 数。

---

## 版本号规范

- 主版本（X）：架构级变更（四阶段/四层/多 Agent 编排）
- 次版本（Y）：能力级新增（引擎/方法论/工具）
- 修订（Z）：修复与微调