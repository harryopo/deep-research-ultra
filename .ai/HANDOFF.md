# HANDOFF · deep-research-ultra（任何 agent 先读这份）

> 最后更新：2026-10-08 · 更新主体：OpenCode 会话（v6.57.0→v6.60.0 追平 + CHANGELOG/HANDOFF/dist 三处收口）
> 读法：本文件 → `.ai/knowledge/` → 架构文档 → **以代码为最终准**。描述与代码不符时以代码为准并回来更新本文件。

## ★1. 会话概览
- 会话时间区间：2026-10-06 至 2026-10-08（上一轮 10-03 至 10-04 见第 10 节版本记录）
- 核心目标与交付范围：DRUX_RETRIEVER 检索器热切换（v6.57.0）→ L3 基准重放评测＋compare 分析插槽（v6.58.0）→ 包清理（18 份开发期文档移入 `docs/dev/`，CHANGELOG 3565→521 行）→ 管线全线基准重放＋知识模式分析插槽（v6.59.0）→ 多轮持续对抗压测＋骨架阅读指南＋分析段写法（v6.60.0）
- 核心模块：`scripts/{research,skeleton,ledger}.py`、`references/report-types.md`、`tests/test_v6{58,59,60}_*.py`、`CHANGELOG.md`、`dist/`
- 整体完成度：四层注入防线经**四轮升级攻击语料**压测仍闭环；全量 1018 项（本机 Windows 1016 过 / 2 跳——bash 缺失按 skipif 照实跳，见第 4 节）
- 本次沉淀摘要：收口三件套——CHANGELOG 补 v6.60.0 条目、本文件追平 v6.60.0、dist 按 HEAD 重打包

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

## ★3. 进行中与断点
> （原 P0「对比类报告实跑验收」已完成——compare-os-agents-20261004 过门盖戳 body=b5f033a5，见第 7 节；原「GitHub 推送」已完成，分支与 origin 同步）
1. **L3 content_sha256 与语义分类器**（P1，随账本 schema 变更）
2. 完成度：未开始；scan_untrusted 为高精度正则版
3. 断点位置：`scripts/ledger.py` `scan_untrusted()`
4. 前置：无
5. 暂停原因：sha256 与 L3 分类器（语义级）同批，当前正则版已覆盖最高频形态
6. 接续：`add_claim`/`set_status` 打 sha 字段；引入语义分类器需评估误报率
7. 标准：误报率有实测数字；不破坏 1018 项存量测试
1. **dist 上传 GitHub Release**（P1，发布动作）
2. 完成度：`dist/deep-research-ultra-v7.0.0.zip` 已按 HEAD（v6.60.0）重打包，`dist/release-notes.md` 同步到内核 6.60.0／1018 项；**未上传 Release**
3. 断点：无代码断点
4. 前置：无
5. 暂停原因：发布属外发动作，等用户明示
6. 接续：把 zip 传到 GitHub Release（index.html 下载按钮指 `releases/latest`）；传完跑一次解包内 `run_all_tests.py` 复核
7. 标准：Release 资产解包后 Linux 上 1018/1018 全绿

## 4. 已知问题与技术债务
- `[Q]` ~~Windows 本机 2 项测试恒挂~~ ✅ 已收口（2026-10-08）：`test_v6223_mcp_config_writer.py` 两条要起 `bash` 跑 `setup-mcp.sh` 的用例加 `skipif(bash 缺失)`——环境缺件照实报 skip 不再报失败。本机 `run_all_tests.py` 全绿：1016 过 / 2 跳 / 0 挂；收集数 1018 不变，Linux/CI 下两条照跑
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
- `P1` ~~GitHub push~~ ✅ 已推；~~dist 重打包~~ ✅ 已按 HEAD 重打（v6.60.0），**上传 Release 待用户明示**
- `P1` 报告正文/证据分层呈现
- `P1` ~~基准重放评测（L3 分类器误报率实测）~~ ✅ 已落（v6.58.0，precision/recall 量化 + KNOWN_FP 档案）
- `P1` 子 Agent 按角色配模型
- `P1` custom search engine 端点（"新增数据源不改代码"的完整目标，需引擎注册制重构）
- `P2` L3 sha256＋语义分类器；L5 高危动作二次确认

## ★8. 运行与验证
- 环境变量变更：`OPENALEX_MAILTO` 已 setx（复用 UNPAYWALL_EMAIL）；本会话内联 `OPENALEX_MAILTO="$UNPAYWALL_EMAIL"` 前缀仍需保留
- 新增依赖：agent-reach v1.5.0（venv `~/.agent-reach-venv`）、yt-dlp 2026.08.19、bili-cli 0.6.2、mcporter 0.14.2（均免登录通道）
- 测试命令：仓库根 `python run_all_tests.py`（**1018 项**＝内核 968＋壳 50；Windows 无 bash 时内核 2 项 skip，见第 4 节）；单套 `cd skills/deep-research-ultra/scripts && pytest`
- 完整回归：`run_all_tests.py`＋`research.py --probe`（实弹，17 引擎应出数据）
- 排查工具：`canary.py check`、`guard.py --session`、`verify_quotes.py --raw`、`agent-reach doctor`

## ★9. 操作禁区
- **登录态通道红线**：agent-reach 登录态 9 通道不装不配不引 Cookie（用户约束，见第 5.4）
- **禁止**：把 claim 标 verified 绕过档 A/档 B；改 REQUIRED_SECTIONS 不全仓查 fixture；`git add -A`（Mimosa 全树误报）；推送/发布不经用户确认
- **骨架重生成覆盖 Lead 段落**：改账本状态后用 `--merge-from` 重生成，别手抄
- **测试数与版本号**：增删测试必须同步 index.html（钉子测试会拦）；版本单一来源＝SKILL.md frontmatter
- **`~/.zcode/skills` 是 junction**：与 `~/.agents/skills` 同一存储，不存在"同步第二安装位"
- L3 标记只降级不删除；逐字对账不换字符形态；档 B 反查必须真换通道

## 10. 版本记录
- 2026-10-08 · OpenCode 会话 · v6.57.0→v6.60.0 追平（DRUX_RETRIEVER、L3 基准重放、包清理、管线全线基准、多轮对抗压测、阅读指南、分析段写法）＋ 收口三件套（CHANGELOG 补 6.60 条目、本文件追平、dist 重打包） · 标签：收口、压测、dist
- 2026-10-04 12:30 · ZCode 会话 sess_3de4172a · v6.52.0→v6.56.0 五版本＋Agent-Reach 接入＋L1-L4 防线闭环＋对比报告形态＋报告类型学＋派单任务书化 · 标签：注入防线、报告类型学、任务书化、主体画像
