# HANDOFF · deep-research-ultra（任何 agent 先读这份）

> 最后更新：2026-10-04 12:30 · 更新主体：ZCode 会话 sess_3de4172a（v6.52.0→v6.56.0 收口轮）
> 读法：本文件 → `.ai/knowledge/` → 架构文档 → **以代码为最终准**。描述与代码不符时以代码为准并回来更新本文件。

## ★1. 会话概览
- 会话时间区间：2026-10-03 至 2026-10-04
- 核心目标与交付范围：四六级实跑收口（v6.52.0）→ 注入防线 L1+L4+L2（v6.53.0）→ Agent-Reach 免登录接入（v6.53.1/6.53.2）→ 对比/优化类报告形态（v6.54.0）→ 报告类型学与派单任务书化（v6.55.0）→ L3+I4+对抗压测防线闭环（v6.56.0）
- 核心模块：`skills/deep-research-ultra/SKILL.md`、`scripts/{fallback,ledger,validate_report,skeleton,verify_quotes,canary}.py`、`engines/fallback.py`、两处测试根
- 整体完成度：四层注入防线（L1/L2/L3/L4）全部落地；对比类报告形态可用；测试 968→1000 全绿
- 本次沉淀摘要：问题解决 3 条、技术决策 4 条（详见第 5 节）、升档长期库 2 条

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

## ★3. 进行中与断点
1. **对比类报告实跑验收**（P0）
2. 完成度：代码与测试全就绪，未跑过真实对比任务
3. 断点位置：无代码断点——等一个真实任务（如"调研与本项目类似的开源方案"）
4. 前置：无（compare 骨架/主体画像指引/矩阵全绿）
5. 暂停原因：等用户发起真实场景
6. 接续：按 SKILL.md Phase 1.1 判定为对比类 → Phase 1.2b 主体画像 → Phase 2.5 派单（新任务书模板）→ Phase 5 发布门前跑 `canary.py check` → `skeleton.py --intent compare`
7. 交付标准：报告含基线节/候选节/对比矩阵（每格 [N]）/优化建议四要素，过门盖戳
1. **L3 content_sha256 与分类器增强**（P1，随账本 schema 变更）
2. 完成度：未开始；scan_untrusted 为高精度正则版
3. 断点位置：`scripts/ledger.py` `scan_untrusted()`
4. 前置：无
5. 暂停原因：sha256 与 L3 分类器（语义级）同批，当前正则版已覆盖最高频形态
6. 接续：`add_claim`/`set_status` 打 sha 字段；引入语义分类器需评估误报率
7. 标准：误报率有实测数字；不破坏 1000 项存量测试
1. **GitHub 推送与 dist 重打包**（P1，发布动作）
2. 本地 7 个提交未推（v6.52.0→v6.56.0）；dist 仍是 6.50.1 时代产物
3. 断点：无代码断点
4. 前置：无
5. 暂停原因：推送属外发动作，等用户明示
6. 接续：`git push`；按既有流程重打 dist（内含测试数与版本号已对齐 6.56.0/1000）
7. 标准：远端 HEAD = ecb8085；dist 解包后 `run_all_tests` 1000/1000

## 4. 已知问题与技术债务
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
- `P0` 对比类报告实跑验收（真实任务跑 `--intent compare` 全流程）——前置：无；风险：矩阵格子质量靠 Lead；验证：过门盖戳＋四要素齐全
- `P0` 对抗红蓝压测升级（真人式多轮对抗语料，现为单发语料自动化）——前置：无；验证：canary/L3/guard 三层全部命中
- `P1` GitHub push（7 个本地提交）＋ dist 重打包——前置：用户确认发布
- `P1` 报告正文/证据分层呈现——前置：实跑反馈
- `P2` L3 sha256＋语义分类器；L5 高危动作二次确认

## ★8. 运行与验证
- 环境变量变更：`OPENALEX_MAILTO` 已 setx（复用 UNPAYWALL_EMAIL）；本会话内联 `OPENALEX_MAILTO="$UNPAYWALL_EMAIL"` 前缀仍需保留
- 新增依赖：agent-reach v1.5.0（venv `~/.agent-reach-venv`）、yt-dlp 2026.08.19、bili-cli 0.6.2、mcporter 0.14.2（均免登录通道）
- 测试命令：仓库根 `python run_all_tests.py`（1000 项＝内核 950＋壳 50）；单套 `cd skills/deep-research-ultra/scripts && pytest`
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
- 2026-10-04 12:30 · ZCode 会话 sess_3de4172a · v6.52.0→v6.56.0 五版本＋Agent-Reach 接入＋L1-L4 防线闭环＋对比报告形态＋报告类型学＋派单任务书化 · 标签：注入防线、报告类型学、任务书化、主体画像
