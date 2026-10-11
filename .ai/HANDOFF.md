# HANDOFF · deep-research-ultra（任何 agent 先读这份）

> 最后更新：2026-10-11 · 更新主体：OpenCode 会话（v6.57.0→v6.62.0 追平 + 收口五件 + P1 模型配档 + **系统体检与 P0 三条堵漏**）
> 读法：本文件 → `.ai/knowledge/` → 架构文档 → **以代码为最终准**。描述与代码不符时以代码为准并回来更新本文件。

## ★1. 会话概览
- 会话时间区间：2026-10-06 至 2026-10-11（上一轮 10-03 至 10-04 见第 10 节版本记录）
- 核心目标与交付范围：DRUX_RETRIEVER 检索器热切换（v6.57.0）→ L3 基准重放评测＋compare 分析插槽（v6.58.0）→ 包清理（18 份开发期文档移入 `docs/dev/`，CHANGELOG 3565→521 行）→ 管线全线基准重放＋知识模式分析插槽（v6.59.0）→ 多轮持续对抗压测＋骨架阅读指南＋分析段写法（v6.60.0）→ 子 Agent 按角色配模型（v6.61.0）→ **系统体检与 P0 三条堵漏（v6.62.0）**
- 核心模块：`scripts/{research,validate_report,skeleton,ledger}.py`、`references/report-types.md`、`tests/test_v6{58,59,60,61,62}_*.py`、`docs/dev/v6.62-系统体检报告.md`、`CHANGELOG.md`、`dist/`
- 整体完成度：四层注入防线经**四轮升级攻击语料**压测仍闭环；**可溯源链首次真正焊死**（v6.62.0：校验门硬绑账本）；**相关性不可判定时不再装懂**（v6.63.0）；**约束全部前置到前 200 行**（v6.64.0）；全量 1049 项（本机 Windows 1047 过 / 2 跳——bash 缺失按 skipif 照实跳，见第 4 节）
- 本次沉淀摘要：**系统体检**（8 维评判框架 + 实弹攻击实验，14 条问题清单落盘 `docs/dev/v6.62-系统体检报告.md`）＋ **P0 三条全堵**（v6.62.0）＋ **体检更正两条并修复**（v6.63.0）＋ **SKILL.md 信息架构重构**（手册搬走＋约束前置，v6.64.0）＋ P1 模型配档 ＋ 收口五件

## ★2. 已完成工作
- `[V]` `scripts/engines/fallback.py` L1 出口白名单——`_EGRESS_ALLOW`＋`egress_denied_reason()`，`_http_get/_http_post` 建连前拒绝；实弹 probe 前后一致（17 引擎）零误伤 — 提交 2dbe217
- `[V]` `scripts/canary.py` L4 canary 哨兵——init/token/check 三命令，令牌出 canary.txt 即 exit 1；端到端"污染分片→merge→canary 逮外泄"有测试 — 提交 2dbe217
- `[V]` `scripts/verify_quotes.py` 语料收 `.json`＋`--max-len 1200` 超长告警＋省略号分段诊断 — 提交 2dbe217
- `[V]` `scripts/ledger.py` L3 `scan_untrusted()`（复用 guard 16 形态＋零宽/双向/canary 三附加）——add_claim/merge 全入库口扫描打 `untrusted` 标记，只降级不删除 — 提交 ecb8085
- `[V]` `scripts/ledger.py` I4 双通道拒绝——`set-status verified` 与 `verify-primary` 拒带标 claim；`--text` 干净重写即摘标重开升级（测试钉住正道）— 提交 ecb8085
- `[V]` `scripts/skeleton.py` `--intent compare`（基线/候选/对比矩阵/维度证据四层）＋ academic/business/risk/opensource 类型专属骨架块＋带标 claim 🚩 渲染 — 提交 15b3361/9292be4
- `[V]` SKILL.md Phase 1.2b 主体画像（内部调研）＋ Phase 3 对比撰写指引＋优化建议四要素 — 提交 15b3361
- `[V]` SKILL.md Phase 2.5 派单模板任务书化（110→55 行）＋ `references/report-types.md`（六型类型学）＋ `references/subagent-lessons.md`（事故档案）— 提交 9292be4
- `[V]` Agent-Reach 免登录接入——CLI 装独立 venv（`~/.agent-reach-venv`，v1.5.0），yt-dlp/bili-cli/mcporter+Exa 全点亮（6 免登录通道），技能壳在 `~/.agents/skills/agent-reach/`；登录态 9 通道按用户红线禁用 — 提交 d40e4d9/dcff015
- `[V]` 工作区库 ec09188：镜像存档化（STALE.md）＋ v6.51 修复方案书与两份参考文档入库
- `[V]` `scripts/research.py` `DRUX_RETRIEVER` 环境变量回退——子 Agent 不带 `--sources` 也继承 Lead 的引擎组；显式 `--sources` 优先 — 提交 0625512（v6.57.0）
- `[V]` `tests/test_v658_l3_benchmark.py` L3 基准重放——20 条干净语料零误报 / 12 类 payload 全命中（recall 100%）/ 3 处已知误报入 KNOWN_FP；compare 骨架候选节＋基线节分析插槽 — 提交 b3d773a（v6.58.0）
- `[V]` 包清理——18 份开发期调研文档移入 `docs/dev/`，CHANGELOG 3565→521 行（旧史进 `docs/dev/CHANGELOG-archive.md`），去除过期引用 — 提交 a2cc060
- `[V]` `tests/test_v659_pipeline_baseline` 管线全线基准——guard 机械门／L3 标记／I4 拒绝／canary 干净／修复路径／绿队放行六步在同一会话 12 条 payload 上全过；knowledge 骨架维度节加分析插槽（`--merge-from` 跳过）— 提交 2732439（v6.59.0）
- `[V]` `references/report-types.md` 分析性段落写法——读者层/审计层两层不混、通用三句式、六型思考架构、三条禁令 — 提交 9f1d68b（v6.60.0）
- `[V]` `skeleton.py` 阅读指南——报告头三行（结论→一页拍板／溯源→证据 claims／审计→登记表＋对账回执）— 提交 6ec9361/8bc68ef（v6.60.0）
- `[V]` `tests/test_v660_multi_round_adversarial.py` 多轮持续对抗压测——红队四轮升级（试探/升级/混合/外传），每轮 L3+I4 蓝队检查，canary R2 起外泄必须 exit 1，全程干净 claim 不被误伤 — 提交 f04a2da（v6.60.0）
- `[V]` 本会话收口——CHANGELOG 补 v6.60.0 条目（原先最高只到 6.59.0）；本文件追平 v6.60.0；`dist/` 按 HEAD 重打包（原为 6.48.0/894 项时代产物）
- `[V]` `test_v6223_mcp_config_writer.py` 两条 bash 用例加 `skipif(shutil.which('bash') is None)`——Windows 本机 `run_all_tests.py` 由"1016 过/2 挂"变全绿"1016 过/2 跳"，收集数 1018 不变
- `[V]` **P1 子 Agent 按角色配模型**（v6.61.0）——SKILL.md Phase 2.5 配档表（检索＝跑腿档 `DRUX_MODEL_RETRIEVER`／判断型＝判断档 `DRUX_MODEL_REVIEWER`／Lead 不传 `model`；宿主无 `model` 参数时忽略本表不许退化串行）＋ `research.py --plan-only` 回执「派单模型」行（未设报变量名、已设原样生效）＋ `tests/test_v661_model_routing.py` 5 项；版本追平 6.61.0（README/index.html 同步，收集数 1018→1023）
- `[V]` **系统体检**（`docs/dev/v6.62-系统体检报告.md`）——8 维评判框架（外部标尺：DeepResearch Bench ICLR 2026 的 FACT/RACE、DRACO 的四维度与负权重幻觉项、ACL 2026 的 citation faithfulness/claim groundedness）＋ 实弹攻击实验；14 条问题清单（P0×3 / P1×11 / P2×2），每条带 `file:line` 或实测复现步骤
- `[V]` **P0-1 校验门硬绑账本**（v6.62.0）——体检实测完整伪造链（编造报告 → passed:true exit 0 → 盖章 → 验戳 ✅，而戳里写着 `ledger=none`）。三处堵死：无账本判未通过（exit 1，issue 点明哪三项没跑）／无账本拒绝盖章（exit 2）／`ledger=none` 的戳一律验不过（哪怕正文指纹完全正确）。正路不误伤：带账本合格报告照样盖章验过
- `[V]` **P0-2 `--output` 自建父目录**（v6.62.0）——`research.py` 新增模块级 `_write_out()`，html/markdown/json/plan 四处共用；原行为实测 FileNotFoundError exit 1（交付契约在目录未建时崩）
- `[V]` **P0-3 产出边界写清**（v6.62.0）——实测 `research.py --format markdown` 产出是**证据集**（检索结果页）而非报告，与宣传页形态错位；SKILL.md Phase 3、README、index.html 三处写明「脚本产出=证据集，不能直接交付，报告由 Lead 从账本组稿后过门」
- `[V]` `tests/test_v662_gate_needs_ledger.py` 8 项（含 `ledger=none` 伪造戳、正路不误伤、两条目录自建）；版本追平 6.62.0，收集数 1023→1031
- `[V]` **体检更正两条并修复**（v6.63.0）——读代码推翻体检初稿的 P1-4/P1-5 两条结论，报告已标注更正：①`relevance` 权重 0.35 本就是五维最高，真问题是**判别力≈0**（中文 2-gram 匹配英文标题恒零命中；实测切题 27.3/跑题 21.3/无关 20.0，authority=95 把三者都托到 ~61 medium）→ 新增 `_relevance_is_reliable()`，不可判定时封顶 45 + `grade=unrated`（封顶必须放在 Tier 加权之后，实测旁路会把 45 抬回 54）；②门限本就是 `max(2, 参数)` 且硬失败，真问题是**旋钮拧不动** → 默认值改 2，放宽走 `--allow-single-source` 并记进 warnings/stats/防伪戳 — `tests/test_v663_truthful_scoring.py` 9 项；收集数 1031→1040

## ★3. 进行中与断点
> （已关闭：原 P0「对比类报告实跑验收」compare-os-agents-20261004 过门盖戳 body=b5f033a5；原 P1「GitHub 推送」3 提交已推、分支与 origin 同步；原 P1「dist 上传 Release」**已完成 2026-10-10**——`v7.0.0` 资产替换为内核 6.60.0 包，SHA256 与本地一致 `064DB1BD…B4BE`，标题同步「内核 6.60.0」，notes 换新）
1. **L3 content_sha256 与语义分类器**（P1，随账本 schema 变更）
2. 完成度：未开始；scan_untrusted 为高精度正则版
3. 断点位置：`scripts/ledger.py` `scan_untrusted()`
4. 前置：无
5. 暂停原因：sha256 与 L3 分类器（语义级）同批，当前正则版已覆盖最高频形态
6. 接续：`add_claim`/`set_status` 打 sha 字段；引入语义分类器需评估误报率
7. 标准：误报率有实测数字；不破坏 1018 项存量测试

## 4. 已知问题与技术债务
> **2026-10-11 系统体检新增 11 条**（P1×9 / P2×2），完整清单与修法见
> `docs/dev/v6.62-系统体检报告.md`。P0 三条已于 v6.62.0 全部堵死。以下按严重度摘录。
- `[P1]` ~~**默认 `--min-sources 1` 与铁律 6 冲突**~~ 🔵 **体检初稿写错，已更正并修复**（v6.63.0）：判定本是 `n_indep < max(2, 参数)`（门槛=2 且硬失败），真问题是**旋钮拧不动**（help 写 `--min-sources 1`，传了不生效）。现默认值改 2，放宽须走 `--allow-single-source` 且记进 warnings/stats/防伪戳
- `[P1]` ~~**CRAAP 不含相关性**~~ 🔵 **体检初稿写错，已更正并修复**（v6.63.0）：`relevance` 权重 0.35 本就是五维最高；真问题是**判别力≈0**——中文 2-gram 匹配英文标题恒零命中，实测切题 27.3 / 跑题 21.3 / 完全无关 20.0，authority=95 把三者都托到 ~61 medium。现新增 `_relevance_is_reliable()`，不可判定时封顶 45 + grade `unrated`。**跨语言判准仍未解决**，需单独一轮
- `[P1]` **相关性跨语言判准**（v6.63.0 遗留）——`_score_relevance` 对中文查询 × 外文语料基本无判别力，本版只做到"不可判定时别装懂"；真修法是换跨语言匹配（向量/翻译词典）。`test_the_old_behaviour_is_what_we_are_fixing` 钉住"三档仍区分不出来"这件事，防止误以为已修好
- `[P1]` **宣称 34 数据源 vs 本机 probe 实测真出数据 14 个**（`--list` 34/30、probe 横幅 25、实跑 14，四个口径互不相同）。`test_v6410` 只钉名义值不钉可用值。修法：宣传改双数字，可用值由 probe 自动生成
- `[P1]` **`env_check` 网络预检假阴性**——报 `github.com:443 不可达`，同一时刻 probe 里 GitHub 深搜/code 搜索各出 5 条；会让人误弃招牌能力。修法：降级为提示，以 probe 为准
- `[P1]` **`duckduckgo` 引擎实际请求 startpage.com**（名实不符，排障误导）
- `[P1]` ~~**SKILL.md 1929 行 ≈27k tokens，约束埋在最后三分之一**~~ 🟢 **已落（v6.64.0）**：手册 588 行搬进新建的 `references/playbooks.md`（665 行）；**铁律 → §〇.6、禁止行为 → §〇.7**（前 200 行内，原章节位只留指针、正文唯一）；账本签名表 §14.3 保留在 SKILL.md（`test_v6330` 拦住过一次，它写着"照抄即可"）。实测 **1942 → 1438 行 / ≈27k → ≈21.5k tokens**。~~目标 ≤800 行~~ 已修正为不可达（四阶段工作流本身 816 行是 Lead 操作手册），验收标准改为"约束在前 200 行"由 test_v664 钉住
- `[P1]` **首次配置唯一路径依赖 bash**（§13.1 第 1 步 `bash setup-mcp.sh --core`），而 README 主打多宿主
- `[P1]` **probe 自检把上游打限流**（S2 连发两次 429），且与 env_check 归因矛盾
- `[P1]` **分层架构数字漂移**——§四 写 Layer1=13，`--list` 实测 11；钉子只钉总数不钉分层
- `[P2]` **31/99 个测试文件是文档钉子（81 处断言）**——防文案改动，防不住功能坏掉；v6.62.0 堵 P0 前无一项测试亮红灯。建议宣传口径拆成「功能测试 N + 文档钉子 M」
- `[P2]` **注入防线与证据账本尚未实测**——本次只审了代码结构（guard 16 种形态正则、两层判据、留痕账族识别），未做注入攻击实验，也未验证 L3/I4 能否被绕过。框架第 3、6 维暂无结论，需专项实验
- `[Q]` ~~Windows 本机 2 项测试恒挂~~ ✅ 已收口（2026-10-10）：`test_v6223_mcp_config_writer.py` 两条要起 `bash` 跑 `setup-mcp.sh` 的用例加 `skipif(bash 缺失)`——环境缺件照实报 skip 不再报失败。Linux/CI 下两条照跑
- `[Q]` Mimosa git 门禁非确定性拦截（工作区第三方存量误报）——重试即过；见工作区 `.learnings/ERR-20261004-001`。对 dev 仓库提交本身无影响
- `[W]` 报告正文与证据过程分层呈现（claim 行内联 scope/状态对读者偏重）——待优化清单 P1，见 `references/v6.54-对比报告升级设计.md`
- `[W]` 对比矩阵格子级语义校验（当前靠【待写】硬失败兜底）——同上 P1
- `[Q]` Exa 免费档配额上限未知——重度使用时 agent-reach doctor 会提示
- `[V]` Semantic Scholar 429：PMID↔DOI 判同依赖 S2，被限流时相关 claim 只能保持 pending（已有预案：≥90 秒间隔重试）
- 已尝试并放弃：在旧镜像上修 bug（镜像已 STALE 存档化）；B 方案强制全文抓取（复评维持 A，见 CHANGELOG v6.56.0）

## 5. 本次经验沉淀

### 5.1 问题解决
- **引文对账 45 段 MISS**——根因三类：『』内嵌省略号、术语强调占用逐字引号、raw 断行粘连。方案：只截短不改字的截齐修复器＋verify_quotes 分段诊断＋语料收 .json。适用：一切逐字对账场景。已升档（见第 6 节索引指向 subagent-lessons.md 与 CHANGELOG v6.52.0）
- **测试数钉子连环拦**——每次增删测试都要同步 index.html 的测试数声明（test_landing_page_facts 钉死）。这是设计使然：宣传数字必须由磁盘实测背书

### 5.2 技术决策
- **派单提示词"任务书＋教训档案"分离**（v6.55）：运维提示词保持任务书形态，事故叙事进 `references/subagent-lessons.md`；新坑先进档案，模板只在措辞误导时才动
- **L3 只降级不删除**（v6.56）：对策 DoS-by-poisoning；误报出口与真注入相同（`--text` 重写），不设白名单豁免
- **X-D19 B 方案维持 A**（v6.56）：L1/L2 落地后 B 的边际收益小于成本；重启条件＝"摘要与正文系统性不一致"的实跑证据
- **Agent-Reach 只启用免登录通道**（v6.53.1，用户红线）：登录态 9 通道有账号封号风险（上游文档自认），一律不装不配不引 Cookie

### 5.3 可复用代码 / 设计模式
- **全仓测试入口**：仓库根 `run_all_tests.py` 依次跑内核＋壳两套并汇总通过数——"绿被两个测试根瓜分"的解法；CHANGELOG 的全量 N 项以它为准
- **文档钉模式**：SKILL.md 关键规则用测试断言短语存在（test_v652/v6531/v655 多处）——改文案必须同步钉子

### 5.4 业务规则
- **登录态通道红线**（用户约束，2026-10-04）：agent-reach 的 Reddit/X/小红书/FB/IG/雪球/Boss/LinkedIn/B站字幕（OpenCLI）一律不装不配不引 Cookie——平台检测非浏览器调用会封号（上游文档自认）。开通须用户逐通道显式要求＋建议专用小号

## 6. 长期记忆同步说明
- 已升档 `.ai/knowledge/engineering/git-gate-explicit-staging.md`（[F]，适用于本机所有含 Mimosa 钩子的仓库）
- 已升档 `.ai/knowledge/environment/zcode-agents-junction.md`（[F]，本仓库双路径单存储的环境事实）
- 宿主记忆库（跨项目）已同步：repo-layout/junction 真相、Mimosa 拦截模式与封印、Agent-Reach 红线
- 待补：L3 分类器语义级增强后回填误报率实测数字

## ★7. 下一步行动
- `P0` ~~对比类报告实跑验收~~ ✅ 已完成（compare-os-agents-20261004，过门盖戳 body=b5f033a5）
- `P0` ~~检索器热切换~~ ✅ DRUX_RETRIEVER 已落（v6.57.0）；custom search engine 端点待下一批
- `P0` ~~对抗红蓝压测升级~~ ✅ 多轮持续对抗压测已落（v6.60.0，四轮升级攻击语料）
- `P1` ~~GitHub push~~ ✅ 已推；~~dist 重打包~~ ✅ 已按 HEAD 重打（v6.60.0）；~~上传 Release~~ ✅ v7.0.0 资产已替换（2026-10-10，SHA256 对撞一致）
- `P1` 报告正文/证据分层呈现
- `P1` ~~基准重放评测（L3 分类器误报率实测）~~ ✅ 已落（v6.58.0，precision/recall 量化 + KNOWN_FP 档案）
- `P1` ~~子 Agent 按角色配模型~~ ✅ 已落（v6.61.0，配档表＋回执行＋5 项测试）
- `P0` ~~校验门可被伪造链绕过／落盘崩溃／产出边界错位~~ ✅ 已落（v6.62.0，三条全堵，8 项新测试）
- **阶段 2 剩余**（体检报告 §三）：~~`min-sources` 对齐铁律 6~~ ✅（v6.63.0，旋钮不再说谎）／~~CRAAP 耦合相关性~~ ✅（v6.63.0，不可判定时封顶 + `unrated`）／**SKILL.md 瘦身到 ≤800 行**（未做，API 手册迁 `references/`）／跨平台首次配置（去 bash 依赖）
- **阶段 3**：宣传双数字（名义/实测可用）→ env_check 假阴性降级为提示 → probe 同族串行限流 → 分层计数入钉 → 测试口径拆分如实呈现 → **注入攻击端到端专项实验**（补框架第 3、6 维结论）
- `P1` custom search engine 端点（"新增数据源不改代码"的完整目标，需引擎注册制重构）
- `P2` L3 sha256＋语义分类器；L5 高危动作二次确认

## ★8. 运行与验证
- 环境变量变更：`OPENALEX_MAILTO` 已 setx（复用 UNPAYWALL_EMAIL）；本会话内联 `OPENALEX_MAILTO="$UNPAYWALL_EMAIL"` 前缀仍需保留
- 新增依赖：agent-reach v1.5.0（venv `~/.agent-reach-venv`）、yt-dlp 2026.08.19、bili-cli 0.6.2、mcporter 0.14.2（均免登录通道）
- 测试命令：仓库根 `python run_all_tests.py`（**1049 项**＝内核 999＋壳 50；Windows 无 bash 时内核 2 项 skip，见第 4 节）；单套 `cd skills/deep-research-ultra/scripts && pytest`
- 完整回归：`run_all_tests.py`＋`research.py --probe`（实弹；**本机 2026-10-11 实测 25 引擎探测、14 个真出数据**——5 个 MCP 未配、2 个缺 key、S2 族 429、百度学术 403、Gitee 401）
- 排查工具：`canary.py check`、`guard.py --session`、`verify_quotes.py --raw`、`agent-reach doctor`、`research.py --probe`
- **交付门禁自查**（v6.62.0 起）：`validate_report.py` 不给 `--ledger` 一律判未通过且拒绝盖章——报告交付前必须带 `--ledger`，别为"过门"省略它

## ★9. 操作禁区
- **登录态通道红线**：agent-reach 登录态 9 通道不装不配不引 Cookie（用户约束，见第 5.4）
- **禁止**：把 claim 标 verified 绕过档 A/档 B；改 REQUIRED_SECTIONS 不全仓查 fixture；`git add -A`（Mimosa 全树误报）；推送/发布不经用户确认
- **骨架重生成覆盖 Lead 段落**：改账本状态后用 `--merge-from` 重生成，别手抄
- **测试数与版本号**：增删测试必须同步 index.html（钉子测试会拦）；版本单一来源＝SKILL.md frontmatter
- **`~/.zcode/skills` 是 junction**：与 `~/.agents/skills` 同一存储，不存在"同步第二安装位"
- L3 标记只降级不删除；逐字对账不换字符形态；档 B 反查必须真换通道

## 10. 版本记录
- 2026-10-11 · OpenCode 会话 · **v6.64.0** SKILL.md 信息架构：手册 588 行搬进 `references/playbooks.md`、铁律→§〇.6/禁止行为→§〇.7（前 200 行内）、1942→1438 行、≈27k→≈21.5k tokens；~~≤800 行目标修正为不可达~~；test_v664 9 项＋收集数 1040→1049 · 标签：信息架构、约束前置
- 2026-10-11 · OpenCode 会话 · **v6.63.0** 体检更正两条：相关性不可判定时封顶 45 + `unrated`（含 Tier 加权旁路）、`--min-sources` 旋钮不再说谎（放宽走 `--allow-single-source` 并进防伪戳）＋ test_v663 9 项＋收集数 1031→1040 · 标签：更正、说真话、交叉验证
- 2026-10-11 · OpenCode 会话 · **v6.62.0** 系统体检（8 维框架＋实弹攻击，14 条问题落盘 `docs/dev/v6.62-系统体检报告.md`）＋ **P0 三条堵漏**（校验门硬绑账本／`--output` 自建目录／产出边界写清）＋ test_v662 8 项＋收集数 1023→1031 · 标签：体检、可溯源堵漏、测试
- 2026-10-10 · OpenCode 会话 · **v6.61.0** 子 Agent 按角色配模型（SKILL.md Phase 2.5 配档表、`--plan-only` 回执派单模型行、test_v661 5 项、收集数 1018→1023）· 标签：模型配档、P1 落地
- 2026-10-10 · OpenCode 会话 · v6.57.0→v6.60.0 追平（DRUX_RETRIEVER、L3 基准重放、包清理、管线全线基准、多轮对抗压测、阅读指南、分析段写法）＋ 收口五件（CHANGELOG 补 6.60 条目、本文件追平、dist 重打包、bash 用例 skipif、v7.0.0 资产替换上传）· 标签：收口、压测、dist、发布
- 2026-10-04 12:30 · ZCode 会话 sess_3de4172a · v6.52.0→v6.56.0 五版本＋Agent-Reach 接入＋L1-L4 防线闭环＋对比报告形态＋报告类型学＋派单任务书化 · 标签：注入防线、报告类型学、任务书化、主体画像
