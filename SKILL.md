---
name: deep-research-ultra
version: 6.12.0
description: |
  超级深度调研工具，基于 Plan-Execute-Synthesize-Reflect 四阶段范式，由主 Agent 担任 Lead 编排子 Agent 并行检索（Orchestrator-Worker），配合深度调研专家团（多视角对抗/审稿人闭环）、证据账本（claim→source 溯源）、来源 Tier 分级与发布前校验门；智能路由（三级级联）匹配 32 个数据源（四层：MCP+学术直连 / Skill+GitHub+国内平台深搜 / 内置+浏览器 / 降级+反爬），引擎真实可用性由 --probe 自检把关。
  当用户说"深度调研"、"deep research"、"帮我研究"、"全面分析"、"调研报告"时调用。
allowed-tools: Read Write Bash Glob Grep AskUserQuestion Agent WebSearch WebFetch
---

# Deep Research Ultra — 超级深度调研工具

**Plan → Execute → Synthesize → Reflect 四阶段深度调研范式**
**Lead 内联编排 + 子 Agent 并行检索 + 深度调研专家团 + 证据账本与分级**

---

## 零、执行模型与冷启动（先读这一节）

### 0.1 执行模型：Lead 就是当前主 Agent

本 skill **不 fork 运行**（`context: fork` 已移除）。原因：forked 子 Agent 只有 **10 个 turn**
的预算（实测 `turn.finished reason=max_turns num_turns=10`），而四阶段工作流需要 25-40 次
工具调用——fork 会在还没写报告前就被掐断，主 Agent 只收到它的开场白，表现为"调研失败/结果截断"。
fork 里同时无法 `AskUserQuestion`（Phase 1 的澄清门必须要它），嵌套 `Agent` 派发也不可靠。

因此：**主 Agent 担任 Lead，亲自跑四阶段；上下文的隔离与膨胀问题交给子 Agent 承担检索扇出**
（Phase 2.5），Lead 只读汇总与账本状态，不亲自吞下原始搜索结果。

### 0.2 前三个动作（硬约束，防探索性空转）

实测一次失败运行里，fork 用 10 个 turn 中的 7 个去 `ls` skill 目录、读目标项目
package.json/tailwind 配置、跑 `--help` —— 真正的检索只剩 3 个 turn。所以：

1. **不要探索 skill 自身**：不 `ls` 脚本目录、不读 `scripts/*.py` 源码、不跑 `--help`。
   本文件就是唯一接口文档，命令照抄即可。
2. **不要为调研对象做代码考古**：目标项目的代码/资产只在结论依赖它时才读（如"适配性"维度）。
3. **第 1 个 turn 就把 Phase 0 的两条命令并行跑完**（环境门 + 引擎自检），
   第 2 个 turn 跑 Phase 1 的 `--plan-only`。**每个 turn 尽量并行发多条命令/多个子 Agent**。
   `--probe` 的退出码就是闸门：`0` 才许进 Phase 1，`3` 表示"环境不足，先引导用户配环境"（见步骤 0.4）。

### 0.3 交付契约（决定成败的一条）

报告**必须落盘**，返回值**必须是短摘要**——见 Phase 6。长正文塞进返回值会被截断，
等价于调研失败。

---

## 一、核心定位

在"智能调研编排层"之上叠加**多智能体协作编排**：

- **子 Agent 并行编排**：Lead 规划 → 按子主题并行 spawn 子 Agent（独立上下文）→ 结果落盘证据账本 → Lead 归并（借鉴 Anthropic Orchestrator-Worker）
- **深度调研专家团**：多视角提问（域专家/怀疑者/实践者/记者/成本）+ 红蓝对抗评审 + 审稿人写-审-修闭环（借鉴 STORM/RedDebate/GPT Researcher）
- **证据账本与分级**：claim→source 可溯源、effort 分级、depth/breadth 旋钮、来源 Tier 分级、发布前校验门
- **智能路由**：三级级联（Rule→Semantic→LLM）自动识别 9 类查询意图，动态生成引擎链
- **编排者角色**：本 skill 调度 MCP 服务器、全局 skill、内置工具，不重复造轮子
- **方法论驱动**：MECE 问题树（6状态）+ CRAAP 评分 + 交叉验证 + CER 结构 + 多信号反思
- **分层降级**：MCP → 学术直连 → Skill → 内置 → 降级引擎（含 curl_cffi TLS 指纹伪装）
- **学术深度**：arXiv 全文(PDF/LaTeX) + Unpaywall OA + Semantic Scholar 引用图谱
- **反爬升级**：curl_cffi TLS 指纹 + Crawl4AI JS 渲染 + Camoufox 强反爬兜底
- **GitHub 深搜**：分桶搜索 + 低星项目挖掘 + 依赖图反向挖掘 + awesome 列表挖掘（不漏项目）
- **国内适配**：百度 SERP + 搜狗微信/知乎 + 百度学术，国内调研最适配
- **推荐度评分**：8 维 GitHub 评分 + 5 维论文评分 + 分组排序 + 雷达图可视化

---

## 二、智能路由

### 2.1 三级级联架构

```
查询输入
  ↓
[L1 规则层] 关键词/正则匹配 → 60-70% 查询在此解决（<1ms，零依赖）
  ↓ 置信度 < 0.8
[L2 语义层] 向量相似度匹配 → 20-25% 查询（20-50ms，可选 sentence-transformers）
  ↓ 置信度 < 0.7
[L3 LLM 层] LLM 判断查询类型 → 5-10% 复杂查询（200-800ms，可选回调）
  ↓
RoutingDecision → 动态引擎链 + 多语言查询变体
```

### 2.2 九类查询-数据源匹配矩阵

| 查询类型 | 关键词特征 | 推荐引擎链 |
|---------|----------|-----------|
| **学术论文** | paper/research/论文/arxiv/doi | arxiv, paper-search, openalex, semantic-scholar, pubmed, **baidu-xueshu** |
| **开源项目** | github/open source/开源/npm | **github-deep-search**, **github-code-search**, oss-finder, tavily, open-websearch |
| **社区口碑** | reddit/评价/口碑/知乎 | agent-reach, last30days, tavily, **sogou-zhihu**, **baidu-serp** |
| **技术文档** | docs/文档/api/tutorial | context7, defuddle, firecrawl |
| **时效新闻** | 最新/今天/近期/2025 | last30days, tavily, websearch, **baidu-serp** |
| **通用搜索** | （默认兜底） | tavily, open-websearch, websearch, **baidu-serp** |
| **定义解释** | 什么是/what is/定义 | tavily, websearch, defuddle, **baidu-serp** |
| **操作指南** | how to/怎么做/教程 | tavily, context7, defuddle |
| **对比分析** | vs/对比/比较 | tavily, agent-reach, arxiv, **sogou-weixin** |



### 2.3 横切关注点

- **时间敏感度**：`realtime`（今天/刚刚/突发）/ `recent`（最近/近期/2025）/ `evergreen`
- **权威性需求**：`high`（论文/官方/doi）/ `medium` / `low`（评价/口碑/论坛）
- **多语言变体**：自动生成中英双语查询变体，提升召回率

### 2.4 断路器（CircuitBreaker）

每个引擎拥有独立断路器，状态机：`CLOSED → OPEN → HALF_OPEN`

- **CLOSED**：正常工作
- **OPEN**：连续失败超阈值，短路拒绝调用
- **HALF_OPEN**：冷却后放行一次试探，成功则 CLOSED，失败则重新 OPEN

### 2.5 路由使用

```bash
# 查看路由分析（不执行搜索）
python "${SKILL_DIR}/scripts/research.py" "RAG 开源实现" --route

# 智能路由自动选择数据源
python "${SKILL_DIR}/scripts/research.py" "最新 LLM 论文" --auto-route

# 深度模式 + 智能路由
python "${SKILL_DIR}/scripts/research.py" "深度调研大语言模型微调" --depth deep --auto-route
```

---

## 三、四阶段工作流

### Phase 0: Pre-flight（环境门 — 必过）

**原则**：按调研场景先验证环境与引擎，就绪后才启动；未就绪先引导配置，不硬跑。

**步骤 0.1 判定场景 → 环境分级（profile）**

| 调研场景 | profile | 必需环境 | 可选增强（缺失仅告警） |
|----------|---------|----------|------------------------|
| 快速浏览 / 通用搜索 | `minimal` | Python + 内置引擎 + 网络 | — |
| **开源项目调研** | `opensource` | Python + 网络（GitHub/OpenAlex 免费直连） | `GITHUB_TOKEN`、`GITEE_TOKEN`；oss-finder/agent-reach 等全局 skill |
| 学术论文调研 | `academic` | Python + 网络（OpenAlex/S2/PubMed 直连） | `UNPAYWALL_EMAIL`、`GITHUB_TOKEN` |
| 全量深度调研 | `full` | Python + 网络 + MCP（setup-mcp.sh --core） | Tavily/Firecrawl/Crawl4AI/`claude`/`npx` |

**步骤 0.2 两条命令并行跑完（同一个 turn 内发出）**

```bash
# ① 环境验证（命令 / 环境变量 / 全局 skill / 模块 / 网络连通）
python "${SKILL_DIR}/scripts/research.py" --env-check --env-profile opensource   # 加 --no-net 跳过网络探测

# ② 引擎功能自检：真实发一次探针查询，验证"今天出不出得来数据"
python "${SKILL_DIR}/scripts/research.py" --probe
```

> 脚本自身强制 UTF-8 输出，**无需**设置 `PYTHONIOENCODING` / `PYTHONUTF8` / `-X utf8`。

**步骤 0.3 为什么必须 --probe（不能只看 --list / --env-check）**

`--list` 的 ✅ 只代表「依赖与配置就绪」，`--env-check` 只探测「域名是否连通」——两者都会
给死引擎开绿灯。实测：Gitee 匿名搜索端点静默返回 `[]`、ModelScope 关键词搜索端点已 404、
arXiv 对部分宽查询回 HTTP 406，而它们在 `--list` 里全是 ✅。`--probe` 用按引擎定制的探针
查询实测，输出四级判定：

> **v6.9：5 个 MCP 源也进闸门**。`--probe` 会对它们真起进程、真握手、真调一次工具，
> 不再只看配置文件在不在——实测有用户 5 个 MCP 一个没连上，`--list` 与旧闸门却全绿。
> 每个 MCP 单次预算 25 秒（`MCP_PROBE_BUDGET`）：首次 `npx`/`uvx` 要下包，超时是预期的，
> 提示会让你先 `bash scripts/setup-mcp.sh --core` 预热再重跑；不预热就当"这个源今天没有"。

| 判定 | 含义 | Lead 动作 |
|------|------|-----------|
| ✅ N 条 | 功能正常（附首条标题，可当场判断相关性） | 纳入 Phase 1 的 `--sources` 分配 |
| ⚠️ 0 结果 | 调通但没数据（查询词无命中 / 契约变更 / 需授权） | 换源或补配置，不得当可用 |
| ❌ 未取到数据 | 附具体原因（`HTTP 406`、`缺少配置: GITEE_TOKEN`、`超时：整场会话 25s 预算内没等到响应`） | 按原因修配置、预热或绕开该源 |
| ⏭ 跳过 | 非搜索类（如 modelscope 模型卡详情） | 按需单独调用 |

`--mcp-check` 现在同样真连一次（打印每个 server 的工具数），**它的 ✅ 才是"连上了"**；
静态配置齐全但握手失败的会明确报 `❌ 连不上 + 原因`。

**步骤 0.4 环境闸门（v6.8：硬停，不是提示）**

`--probe` 自检完会自己判一次"环境够不够开工"，判据是**真的出得来数据**的引擎（不是 `--list`
的 ✅ 数量），三条全满足才放行：

| 判据 | 为什么是硬条件 |
|------|---------------|
| 出数据的引擎 ≥ 3 | 少于 3 个无法做跨源三角验证，结论没有对照 |
| 覆盖 ≥ 2 层 | 同层的几个源往往抓的是同一批网页，数量够而独立性不够 |
| 至少一条一手制品通道（论文库 / 代码仓库） | 缺它则"某仓库/某论文原文说 X"这类归属型 claim 一条都验证不了（实测 110 条全卡 pending） |

**Lead 必须按退出码行动**：

| 退出码 | 含义 | Lead 动作 |
|--------|------|-----------|
| `0` + `✅ 环境可开工` | 闸门放行 | 进 Phase 1；若同时打印了"有 N 个源没配好"，**先用 AskUserQuestion 问用户「现在配 / 就这样开跑」**，得到答复才派子 Agent |
| `3` + `⛔ 环境不足` | 客观不够 | **停下来**：把 blockers 和逐条配置指引转述给用户，等他配好环境后重跑 `--probe`；不许硬开跑，也不许自己代答"那就继续" |
| `1` | 一个引擎都没出数据 | 同上，且必须先修环境 |

用户明确要求带缺口开跑时才加 `--allow-degraded`（此时报告里必须写明数据源受限）；
`--probe --sources a,b` 是局部自检，只报这几个引擎的状态，不做全局判定。

```bash
# 缺失 MCP → 一键配置（免费模式）；只测某几个引擎用 --sources a,b
bash "${SKILL_DIR}/scripts/setup-mcp.sh" --core
python "${SKILL_DIR}/scripts/research.py" --list           # 配置态清单（不等于功能可用）
python "${SKILL_DIR}/scripts/research.py" --probe --sources openalex,baidu-serp
```

> 缺哪个变量、去哪申请、解锁什么，`--probe` 会按引擎逐条打印（同一个动作自动合并成一行），
> 不需要背配置表；配好后重跑直到闸门放行为止。


### Phase 1: Plan（规划）— MECE 问题树 + 6 状态机

**目标**：将模糊主题拆解为互斥穷尽（MECE）的子问题树，每个子问题附可验证假设。

**（秘塔问题链）**：每个子问题拥有 6 状态状态机：

```
pending → searching → verified | conflict | supplementing → completed
```

| 状态 | 含义 |
|------|------|
| `pending` | 待搜索 |
| `searching` | 搜索中 |
| `verified` | 已验证（≥2 独立来源） |
| `conflict` | 矛盾（来源冲突） |
| `supplementing` | 补充中（Drill-down） |
| `completed` | 已完成 |

**步骤**：
1. 主题澄清（AskUserQuestion）：调研目标 / 深度 / 维度 / 时间范围
2. **MECE 拆解由 Lead 亲自做**——`scripts/plan.py` 不替你拆问题树，它只把你给的
   `--dimensions` 展开成骨架并做 MECE 校验。**不传 `--dimensions` 就只能拿到通用骨架**，
   子问题质量直接决定报告质量。
3. 假设生成：每个子问题给出可验证假设
4. 数据源匹配：用 Phase 0 `--probe` 的实际 ✅ 清单做 `--sources` 分配（路由只给建议）
5. 多视角注入：每个子问题默认挂 3 个对抗视角（域专家-准确性 / 怀疑者-矛盾反例 / 实践者-可落地性），`--perspectives 0` 可关闭

**努力程度分级（effort）决策树**（对齐社区 depth/breadth 共识）：

| effort | 子问题数 | breadth（并行子Agent数）| 数据源数 | 反思轮次 | 专家团 | 报告字数 |
|--------|----------|------------------------|----------|----------|--------|----------|
| `quick`（快速） | 2-3 | 2 | 2-3 | 0 | 跳过 | 1500-3000 |
| `standard`（标准，默认） | 4-6 | 4 | 3-5 | 1 | 1 轮 3 视角 | 3000-6000 |
| `deep`（深度） | 7-10 | 8 | 5-8 | 2-3 | 2 轮含冲突消解 | 6000-15000 |
| `exhaustive`（极深） | 10+ | 12 | 8+ | 3+ | red-team 对抗 + 多轮修订 | 15000+ |

**深度策略**（`--depth` 兼容映射）：quick→快速 / standard→标准 / deep→深度 / extreme→极深（exhaustive）

> 决策规则：任务重要性高 / 结论将有决策用途 → 至少 `deep`；时间紧 / 快速浏览 → `quick`。
> `--breadth N` 显式覆盖并行子 Agent 数；`--effort` 与 `--depth` 同时给出时以 `--effort` 为准。
> **子问题数 = `--dimensions` 的个数**：想要 7-10 个子问题就要给 7-10 个维度，否则 breadth 空转。
> **v6.6 起 `--effort` 真正生效**：此前 effort 只影响打印，plan 预设仍按 `--depth`（默认 standard，上限 5）取值，8 个维度会被静默截为 5。现在 effort 优先映射预设（exhaustive↔extreme），超出上限的维度会在 stderr 告警并记入 `plan.dropped_dimensions`。

### Phase 1.5: 计划确认门

**目标**：把选择权交给用户，避免返工。

```
Lead 拆维度 → --plan-only 出计划与待确认清单 → 用户增删/调深度 → 批准 → 才进 Execute
```

1. 运行 `--plan-only`，**必须带上你拆好的 `--dimensions`**（否则只会得到通用骨架，
   与你的主题相关性存疑）：

   ```bash
   python "${SKILL_DIR}/scripts/research.py" "<主题>" --plan-only --effort deep \
     --dimensions "现状与主要玩家,技术路线,生态与成熟度,许可与合规,落地成本,风险与反例" \
     --goal "<用户要拿这份报告做什么决策>"
   ```

2. 用 **AskUserQuestion** 让用户确认或调整：
   - 子问题是否需要增删（MECE 之外还想看什么）
   - `--effort/--breadth` 是否要升降级
   - 专家团视角是否需要增删（`--perspectives`）
3. 用户批准后，才进入 Phase 2 执行


### Phase 2: Execute（执行）— 并行子 Agent + 反思循环

**子 Agent 类型**：

| Agent 类型 | 数据源 | 适用场景 |
|-----------|--------|----------|
| 搜索 Agent | Tavily MCP / open-websearch MCP / Firecrawl MCP | 通用网页搜索 |
| 学术 Agent | arxiv MCP / paper-search MCP / **OpenAlex/S2/PubMed 直连** / **arXiv全文/Unpaywall/S2图谱** | 学术论文+全文+引用 |
| 社区 Agent | agent-reach skill（Reddit/HN/X/知乎/B站） | 社区口碑 |
| 开源 Agent | oss-finder skill + GitHub MCP | 开源项目 |
| 时效 Agent | last30days skill | 近期热点 |
| 文档 Agent | context7 skill / defuddle skill | 库文档/网页提取 |
| 浏览器 Agent | **Crawl4AI Docker / LayeredCrawler** | JS 渲染/反爬 |

**反思循环**（Kimi 式多信号 + 证据充分性停止）：

```
每轮搜索后评估：
  1. 覆盖率是否达标？（≥0.75）
  2. 是否有高优先级空白？ → 最高优先，先补
  3. 证据充分性：每个子主题独立来源 ≥2 且 ≥1 条 verified？不足 → supplementing（优先于覆盖率达标，Salesforce EDR 不提前停止）
  4. 新增 claim 边际收益：本轮新增 claim/上轮 < 0.15 且覆盖率 ≥0.6 → 收敛停止
  5. 边际收益是否递减？（Δ覆盖率 < 0.05 且覆盖率 ≥ 0.6 → 收敛）
  6. 无高优先级空白且覆盖率 ≥ 0.6 → 停止
```

**停止优先级**：高优先级空白 > 证据不足 > 边际收益递减 > 覆盖率达标。

### Phase 2.5: 并行子 Agent 编排

**目标**：解决"单主流程串行调多引擎"的长上下文丢失问题；每个子主题独立上下文、独立检索、结果落盘，再归并。

```
Lead（主 Agent）
 ├─ 拆解子问题（Phase 1 的 MECE 树）
 ├─ 一次性并行 spawn 子 Agent（Agent 工具，subagent_type=general-purpose，每个子问题一个）
 │    ├─ 子 Agent A: research.py 检索「子问题1」+ ledger 落盘
 │    ├─ 子 Agent B: research.py 检索「子问题2」+ ledger 落盘
 │    └─ ...
 ├─ 全部完成后：读 ledger.status → 冲突消解 → 生成 outline
 └─ 进入 Phase 3.5 专家团评审 → 组稿
```

**子 Agent 提示词模板**（直接复制，替换占位符）：

```
你是 deep-research-ultra 的子研究员（Sub-Researcher）。
主题: {subtopic}
视角: {perspective}（域专家/怀疑者/实践者等，见 --perspectives）
指定引擎: {engines}（由 Lead 从 Phase 0 `--probe` 报 ✅ 的引擎中按主题分配）

任务:
1) 用 python "{SKILL_DIR}/scripts/research.py" "{subtopic}" --no-cache 检索（若指定引擎则加 --sources {engines}）
   （v6.10：`--ledger` 只登记证据到 evidence.jsonl，不再把搜索结果的标题写成 claim——
   标题是别人页面的标题，不是你的论断；混进来会让覆盖率与引用统计虚高，实测 391 条 merge 后变 602 条）
2) 用 python "{SKILL_DIR}/scripts/ledger.py" add-claim --session {ledger_dir} --text "<claim>" --topic "{subtopic}" --status pending --perspective "{perspective}" --confidence <0-1>
   再用 add-source 为该 claim 关联 ≥1 个来源 URL（--tier 自动判定）
3) 每条 claim 必须：只记录事实与来源，不做总结断言；发现矛盾标 --status conflict
约束: 你的全部产物写入 {ledger_dir}/{slug}.json 后退出；不写长篇报告。
```

> **status 语义（真实性核心）**：子 Agent 一律写 `pending`——**verified 只能由 Lead 在归并阶段显式赋予**，禁止未验证即标 verified。Lead 有两条合规升级通道，必须按 claim 的证据类型选用：
>
> | 档 | 适用 claim | 判据 | 命令 |
> |----|-----------|------|------|
> | **A · 跨域三角验证** | 「世界事实」类（某机制的行为、某统计数字） | ≥2 个不同注册域来源 | `ledger.py set-status --claim-id <ids> --status verified --note "交叉验证 N 独立来源"`（发现原文写错时加 `--text` 就地更正） |
> | **B · 一手来源 + 反查** | **归属型**（"某仓库 README 现状是 X"/"某论文原文说 Y"）——对象就是单个制品，要求第二个域名来验证它自身是判据错配 | 反查 URL 与既有来源指向同一制品（同域同路径；blob/raw 算同一制品，不同分支/文件不算） | `ledger.py verify-primary --claim-id <ids> --check-url <URL> --check-title <t> --method repo_health` |
>
> 档 B 不是后门：命令会**拒绝**反查域与 claim 既有来源域不一致的情况（拿一篇无关博客"验证"某仓库是升不上去的），并把 `verify_method` 与反查 URL 写进账本留痕。实测一次调研有 ~110 条归属型 claim 因只有档 A 一条路而全卡在 pending，导致发布门覆盖率虚低。**反查必须真实发生**（读页面/源码/API 比对内容），不允许只把 URL 再填一遍。
>
> `--session` 传的是 **`{ledger_dir}` 本身**（里面有 `ledger.jsonl`），不是它的父目录：`set-status`/`verify-primary` 现在会先 `require()`，账本不存在直接报错退出，而不是静默建一个空账本再返回"升级 0 条"（v6.7）。

- **并行派发**：Lead 对全部叶子子问题**一次性并行** `Agent` 调用（每子 Agent 独立上下文）；breadth = `--breadth` 值。**一次 turn 发完**，不要一个子问题一个 turn 串行派
- **Lead 不吞原始结果**：子 Agent 的返回值只该是"写了哪几个分片文件 + 几条 claim/几个源"，
  原始搜索结果留在子 Agent 的上下文里，不进 Lead
- **并发写安全**：子 Agent 各自写独立分片文件 `{ledger_dir}/{slug}.json`，**不直写共享 ledger.jsonl**（多进程并发追加整行不保证原子）；Lead 归并时统一 `ledger.py merge --dir` 收编去重
- **归并**：所有子 Agent 完成后，Lead 运行 `python scripts/ledger.py status --session {ledger_dir}` → 处理 conflict → 按交叉验证结果把达标 claim 升级 verified → 生成 outline
- **证据账本目录约定**：`{workspace}/.research/{session_id}/ledger/`

### Phase 3: Synthesize（合成）— 结构化报告

**报告结构**（参考 `scripts/report.py`）：

```markdown
# {调研主题}

**调研时间**：YYYY-MM-DD HH:MM
**调研深度**：standard（4-6 子问题 / 3-5 数据源 / 1 轮反思）
**调研配置**：effort=standard ｜ breadth=4 ｜ 专家团=3 视角（域专家/怀疑者/实践者）｜ 发布校验=passed
**调研 Agent**：deep-research-ultra
**路由决策**：[rule] 学术论文（置信度 0.95）→ arxiv, paper-search, openalex

---

## 执行摘要
[3-5 句话核心结论]（引用编号：正文结论用 [N] 锚定，与附录来源对应）

## 调研范围与方法
- 主题拆解：MECE 问题树（6 状态）+ 多视角问题注入
- 假设清单：H1, H2, H3...
- 数据源选择理由（智能路由决策）
- 证据账本：`.research/{session}/ledger/`（claim→source 可溯源）

## 1. 子问题 1：{问题} [✅已验证]
### 1.1 关键发现
[CER 结构：Claim → Evidence（[N]） → Reasoning]
### 1.2 来源
| # | 来源 | URL | Tier | CRAAP 评分 | 可信度 |
### 1.3 矛盾点

## N. 子问题 N：{问题} [⚠️待补充]
...

## 时间线
```mermaid
timeline
    title 主题演化时间线
```

## 结论与建议
### 验证的假设
- H1: [假设内容] — 已验证
- ❌ H2: [假设内容] — 被证伪

## 附录 A：MECE 问题树（含 6 状态）
## 附录 B：完整来源列表（含 CRAAP 评分）
## 附录 C：调研质量自评
- 覆盖率：X% ｜ 交叉验证率：X% ｜ 矛盾处理率：X%
- 证据充分子主题：N/M（独立来源 ≥2）
## 附录 D：来源 Tier 分布（`tier.py` 判定）
| Tier | 含义 | 数量 |
|------|------|------|
| 1 | 官方/学术 | N |
| 2 | 权威/官方文档 | N |
| 3 | 一般 | N |
| 4 | 社区/低质 | N ⚠️（占比 ≥30% 需补权威源）|
```

**输出格式**：

```bash
# 默认 HTML（含 Mermaid 图表，体验最佳）
python "${SKILL_DIR}/scripts/research.py" "关键词" --format html

# Markdown / JSON / CSV
python "${SKILL_DIR}/scripts/research.py" "关键词" --format markdown
```

### Phase 3.5: 专家团评审 + 审稿人修订闭环

**目标**：防"自证自话"——每个章节草稿经多角色对抗评审、补查、修订后再定稿。

```
章节草稿(draft)
  → panel.py 生成评审清单（按角色）
  → Lead 以「域专家/怀疑者/实践者」视角逐条消化清单
  → 缺口/疑点 → ledger 标 supplementing → 派补查（子 Agent 或 Lead 直接检索）
  → 修订 → 下一轮（最多 N 轮，N=effort 决定：standard=1 轮，deep=2 轮，exhaustive=red-team）
```

1. 生成评审清单：`python scripts/panel.py perspectives`（5 内置角色）或对大纲：
   `python scripts/panel.py review-outline --input <outline.md> --roles domain_expert,skeptic,practitioner`
2. 每个角色输出结构化 findings（gap / contradiction / evidence_needed），Lead 逐条处理
3. 补查结论写回账本（`ledger.py add-claim --status supplementing`）
4. 修订后进行「引用核对」：确认正文每个 [N] 引用在账本有对应 source

### Phase 4: Reflect（反思）— 持续改进

**停止信号**（参考 `scripts/reflect.py`）：

| 信号 | 判定 | 动作 |
|------|------|------|
| 高优先级空白 | 有 high 空白 | 继续 Drill-down（最优先） |
| 证据不足 | 子主题独立来源 <2（EDR 不提前停止） | supplementing |
| 新增 claim 边际 | 新增/上轮 <0.15 且覆盖 ≥0.6 | 收敛停止 |
| 覆盖率达标 | ≥ 阈值（0.75） | 停止 |
| 边际收益递减 | Δ覆盖率 <0.05 且 ≥0.6 | 收敛停止 |
| 最大轮次 | 达到上限 | 停止 |

**自评指标**：

| 指标 | 目标值 |
|------|--------|
| 覆盖率 | ≥ 90% |
| 交叉验证率 | ≥ 70% |
| 矛盾处理率 | = 100% |
| 平均 CRAAP 分 | ≥ 70 |
| 证据充分子主题占比 | 100% |

### Phase 5: 发布前校验门

**目标**：报告发布前做确定性质量闸门，不通过不能交付。

```bash
# 过门 + 盖防伪戳（v6.11：只有脚本能给报告盖章）
python "${SKILL_DIR}/scripts/validate_report.py" --report report.md --ledger .research/session/ledger --stamp

# 交付前验戳（把这一行输出贴给用户/留在会话里）
python "${SKILL_DIR}/scripts/validate_report.py" --report report.md --ledger .research/session/ledger --verify-stamp
```

| 校验项 | 失败处理 |
|--------|----------|
| 引用一致性：正文 [N] 都在账本有对应来源 | 回到 Phase 3.5 补引用 |
| **引用反查（v6.3）**：编号 N 的来源 URL/标题须出现在报告中（数字在范围内≠可追溯） | 补附录来源映射 |
| **编号不串号（v6.7）**：登记表里同一 `[N]` 不得映射到不同 URL；正文重复引用同一编号属正常写作，不再误报 | 统一编号或拆分 |
| **引用-证据对齐（v6.7，主指标）**：报告引用其来源来立论的 claim，必须已 verified 或已 conflict（矛盾是结论，不是缺陷） | 补 `set-status`/`verify-primary`，或在正文该引用处标 `⚠️` 明示待补证据（标了只告警不阻断） |
| 全量覆盖率 verified/total ≥ 0.6（**v6.7 降级为告警**：分母含未写进报告的过程记录，用它阻断会与"报告可用"矛盾） | 参考告警补验证，不阻断交付 |
| **独立来源强度（v6.3）**：每条 verified claim 独立来源 ≥2；**v6.7 起档 B（`evidence_tier=B` 且有 `verify_method`）豁免**——归属型断言不该被要求第二个域 | 补交叉验证或降级 pending |
| **六维要素（v6.3）**：报告含仓库链接时，风险标签/许可证/维护/适配/落地/量化齐备 | 按 7.0b 六维质量门补写 |
| 必需章节：执行摘要/方法/结论/来源 | 补写章节 |
| 低质源占比：Tier4 < 30%（告警） | 建议补权威源后复核 |
| 执行摘要 ≤ 1200 字 | 精简摘要 |
| **防伪戳（v6.11）**：`--stamp` 只在过门后往 report.md 尾部写一行 `<!-- drux:validated body=… ledger=… claims=N sources=N -->`；`--verify-stamp` 复核正文与账本指纹 | 没戳／正文改过／账本变过 → 重跑 `--stamp`；手抄一行戳骗不过指纹 |

> 校验通过（exit 0）后才向用户交付；`--format html/markdown/json` 均可先导出再校验。
>
> **为什么要有戳**：另一次实跑里，Lead 在写不出报告时落了一份带占位内容的 report.md，并在
> 会话里声称"校验门 passed"——他根本没跑校验。"诚实标注"这条铁律拦不住不碰工具的人，
> 所以把成本抬起来：**"过了校验门"必须是脚本产物，不是一句自述**。交付前先跑
> `--verify-stamp`，它输出的那行 ✅/❌ 才是凭据；没戳＝未校验，直接说"未过门"，别改口。

### Phase 6: 交付契约（落盘 + 短摘要）

**铁律**：报告正文一律落盘，**返回值只给短摘要**。长正文塞进返回值/最终消息会被截断，
等价于调研失败——历史上那次"调研只返回开头一句"就是这个原因。

**产物目录**（一次调研一个 session，全程可续）：

```
{workspace}/.research/{session_id}/
├── ledger/            # claim→source 证据账本（子 Agent 分片 + merge）
├── outline.md         # Phase 3 大纲（可选）
├── report.md          # 交付物（正文）
└── report.html        # 交付物（--format html 时）
```

**落盘顺序**：Lead 依据账本写 `report.md` → `validate_report.py --stamp`（过门即盖戳）→
`--verify-stamp` 复核 → 才回复用户。**报告里那句"校验 passed"必须有戳背书**；
没有戳就写"未过门：<issue 列表>"，不许凭自述交付。
中途快撑不住（上下文/turn/时间接近上限）时，**先把当前版本的 report.md 落盘再说话**，
并在摘要里写明"未完成的部分"——留下可用的半成品，好过什么都不留下。

**最终回复模板（≤25 行，严格按此结构）**：

```
📄 报告：<report.md 的绝对路径>（<字数> 字，<N> 个来源，校验 passed <戳 body=xxxx>）

一句话结论：<用户要的决策答案>

要点
- <结论>（[3][7]）
- <结论>（[1]，⚠️ 单源待补）
- ...（3-5 条）

质量：覆盖率 X% ｜ 交叉验证率 Y% ｜ 矛盾 Z 处已标注 ｜ 引擎 <✅数>/<探测数> 通过自检

未决 / 风险：<还缺什么证据、哪些结论不得直接用于决策>

下一步：<可选：加深某维度 / 补查某条 claim / 出 HTML 版>
```

正文细节、来源全表、MECE 树、Tier 分布都留在文件里，不粘贴到对话。

---

## 四、四层数据源架构（共 32 个数据源：28 个可搜索，20 个支持 --probe 自检，含 5 个 MCP）

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 1: MCP + 学术直连层（11 个引擎）                              │
│  ├── Tavily MCP          AI 搜索 + extract + map + crawl            │
│  ├── Firecrawl MCP       搜索 + scrape + crawl + browser 自动化     │
│  ├── open-websearch MCP  免费、无 Key、Bing/百度/CSDN/掘金等        │
│  ├── arxiv MCP           arXiv 论文                                  │
│  ├── paper-search MCP    14 学术平台聚合                             │
│  ├── OpenAlex            474M+ 作品，直连无需 MCP                    │
│  ├── Semantic Scholar    200M+ 论文 + AI 引用上下文                  │
│  ├── PubMed              36M+ 医学论文                               │
│  ├── arXiv Fulltext      PDF/HTML/LaTeX 全文下载                     │
│  ├── Unpaywall           DOI→合法 OA PDF                             │
│  └── S2 Citation Graph   引用图谱 + intents + influential            │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 2: 全局 Skill + GitHub 深搜 + 国内源层（14 个引擎）           │
│  ├── agent-reach         13 平台社交（X/Reddit/HN/B站/知乎...）     │
│  ├── oss-finder          GitHub/GitLab/Gitee/npm/PyPI               │
│  ├── last30days          近 30 天全网                                │
│  ├── sciverse            学术论文深度检索                            │
│  ├── defuddle            网页转 Markdown（替代 Jina）                │
│  ├── context7            库文档拉取                                  │
│  ├── GitHub Deep Search  分桶+低星+依赖图+awesome（不漏项目）        │
│  ├── GitHub Code Search  GitHub Code Search API（代码级）            │
│  ├── Gitee               仓库搜索（v5 搜索端点需 GITEE_TOKEN）        │
│  ├── ModelScope          模型卡详情（仅精确 id；无关键词搜索端点）     │
│  ├── Baidu SERP          百度搜索（国内主力）                        │
│  ├── Sogou 微信          微信公众号文章                              │
│  ├── Sogou 知乎          知乎问答                                    │
│  └── Baidu 学术          百度学术（国内论文）                        │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3: Claude 内置 + 浏览器自动化层（3 个引擎）                    │
│  ├── WebSearch           实时网络搜索                                │
│  ├── WebFetch            简单网页抓取                                │
│  └── Crawl4AI            Docker 浏览器自动化 + 反检测                │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 4: 降级层（4 个引擎，含 curl_cffi TLS 指纹伪装）              │
│  ├── DuckDuckGo          ddgs Python 库                             │
│  ├── Baidu HTML          百度搜索 HTML 解析                          │
│  ├── Bing HTML           Bing 搜索 HTML 解析                         │
│  └── SearXNG             自建元搜索（Docker）                        │
└─────────────────────────────────────────────────────────────────────┘
```

**降级链**（含断路器）：

```
优先级 1: Tavily MCP（AI 搜索 + 结构化）
   ↓ 断路器 OPEN
优先级 2: open-websearch MCP（免费多引擎）
   ↓ 断路器 OPEN
优先级 3: Claude 内置 WebSearch
   ↓ 断路器 OPEN
优先级 4: ddgs Python 库（curl_cffi TLS 伪装）
```

---

## 五、反爬虫与浏览器自动化

### 5.1 curl_cffi TLS 指纹伪装

所有 HTTP 请求（`_http_get` / `_http_post`）优先使用 curl_cffi 进行 TLS/JA3 指纹伪装：

```python
from curl_cffi import requests as cffi_requests
r = cffi_requests.get(url, impersonate="chrome124")  # 伪装 Chrome 124
```

- 未安装 curl_cffi 时自动降级到 urllib（保留兼容）
- 支持 HTTP GET + POST，统一重试与代理

### 5.2 LayeredCrawler 四级爬取策略

```
Level 1: curl_cffi（轻量 TLS 伪装，90% 场景）
   ↓ 需 JS 渲染
Level 2: Firecrawl MCP（搜索 + scrape）
   ↓ MCP 不可用
Level 3: Crawl4AI Docker（JS 渲染 + magic_mode 反检测）
   ↓ 强反爬
Level 4: Camoufox（C++ 指纹注入，强反爬兜底）
```

### 5.3 Crawl4AI 配置

```bash
# Docker 部署 Crawl4AI
docker run -d --name crawl4ai \
  -p 11235:11235 \
  -e CRAWL4AI_API_TOKEN=your_token \
  unclecode/crawl4ai:latest

# 环境变量
export CRAWL4AI_URL=http://localhost:11235
export CRAWL4AI_API_TOKEN=your_token
```

---

## 六、学术全文与引用图谱

### 6.1 arXiv 全文下载

```python
from engines.academic_fulltext import ArxivFulltextEngine

e = ArxivFulltextEngine()
# 搜索论文（返回元数据 + PDF/HTML/LaTeX URL）
results = e.search("transformer attention", max_results=10)
# 下载 PDF
e.download_pdf("2404.19756", "paper.pdf")
# 获取 LaTeX 源码（tar.gz）
latex = e.fetch_latex("2404.19756")
```

- 数据量：2.4M+ 预印本
- API Key：无需
- 速率限制：3 秒/请求（官方建议）
- 国内可用：✅

### 6.2 Unpaywall 开放获取

```python
from engines.academic_fulltext import UnpaywallEngine

e = UnpaywallEngine()
# DOI → OA PDF URL
result = e.search_by_doi("10.1038/nature12373")
```

- 数据量：1000 万+ OA 文章
- 必需参数：email（`UNPAYWALL_EMAIL` 环境变量）
- 速率限制：100,000 calls/day
- 国内可用：✅

### 6.3 Semantic Scholar 引用图谱

```python
from engines.academic_fulltext import CitationGraphEngine

e = CitationGraphEngine()
# 构建引用关系图
graph = e.build_citation_graph(seed_paper_id="2404.19756", depth=1, max_nodes=30)
# 引用意图分析
intents = e.get_citation_intents(paper_id="2404.19756")
# influential citations
influential = e.get_influential_citations(paper_id="2404.19756")
```

- 数据量：214M 论文
- 功能：引用图谱 + 引用意图（methodology/background/result）+ influential citations
- API Key：可选（无 Key 有速率限制）
- 国内可用：✅

---

## 七、GitHub 深度搜索

### 7.0 开源项目调研——综合工作流（项目 + 论文双查）

**覆盖源矩阵**（开源调研时按需全上，能查到的都查）：

| 类别 | 数据源 | 获取方式 |
|------|--------|----------|
| 海外代码平台 | GitHub 深搜（分桶+低星+依赖图+awesome）、GitHub Code Search | 免费 API，可选 `GITHUB_TOKEN` 提速 |
| **国内代码平台** | **Gitee**（`gitee` 引擎） | 需 `GITEE_TOKEN`（匿名请求实测静默返回 `[]`） |
| **国内模型集市** | **魔搭 ModelScope**（`modelscope` 引擎） | 仅按精确 model id 取模型卡（关键词搜索端点已下线） |
| 多平台聚合 | oss-finder（GitHub/GitLab/Gitee/npm/PyPI） | 全局 skill |
| **算法论文（必查）** | arXiv / OpenAlex / Semantic Scholar（搜索项目名/技术名自动附带论文） | 免费直连 |
| 官方文档 | context7（库文档）、defuddle（官方站抓取）；Tier 1-2 官方域优先 | MCP/skill |
| 社区/论坛 | agent-reach（Reddit/HN/X）、搜狗知乎、百度等国内论坛口碑 | skill / 国内源 |
| Skill 生态网站 | GitHub awesome-* 列表挖掘 + WebSearch 查 skill 目录站 | 深搜 + 内置 |

**"项目 + 论文"双查规则**：每锁定一个候选项目/技术，除项目仓库外，**必须**同时用学术链（arxiv/openalex）检索其关联论文或技术报告（如 RAG → 论文附带），确保"实现 + 原理"互为支撑。

**命令示例**：

```bash
# 一键执行开源调研（引擎清单以 Phase 0 --probe 的 ✅ 结果为准，下例为默认可用的组合）
python "${SKILL_DIR}/scripts/research.py" "RAG 开源实现" --auto-route \
  --sources oss-finder,github-deep-search,openalex,baidu-serp --ledger .research/s1/ledger

# 配了 GITEE_TOKEN 才能用 Gitee；ModelScope 只能按精确 id 取模型卡
python "${SKILL_DIR}/scripts/research.py" "向量数据库" --sources gitee
python "${SKILL_DIR}/scripts/research.py" "Qwen/Qwen2.5-7B" --sources modelscope   # 详情查询
```

**真实性 / 可追溯（硬规则）**：
1. 每个项目 claim 必须关联 **≥1 个官方仓库 URL**（GitHub 或 Gitee 主页），模型类关联 ModelScope 模型卡
2. 项目结论必须隔离"事实（仓库/star/文档原文）"与"推断（架构优劣）"，推断标注置信度
3. 全部证据写证据账本（`--ledger`），发布前过校验门（`validate_report.py`），引用 [N] 与账本一一对应
4. 来源 Tier 分级自动生效：官方仓库/论文 Tier 1-2，论坛/个人博客 Tier 3-4，低质占比 ≥30% 时校验门告警

### 7.0b 开源调研质量门（六维必检，v6.2）

**背景**：AI 开源调研普遍存在「信息失真、适配不足、风险隐形、落地性差」问题。质量门将六类缺陷固化为强制检查项——每个候选项目都过，缺项不得写入结论。

| 维度 | 要防的坑 | 强制动作（每候选项目） |
|------|----------|------------------------|
| ① 事实核实 | 幻觉仓库/接口/指标、虚构 star | 跑 `repo_health.py <repo>`（官方 API 事实 + 检测时间），编号记入账本；AI 不得凭记忆断言 star/提交/版本 |
| ② 适配性 | 无视自身技术栈/版本/环境/团队 | 输出"技术栈对照表"：项目语言/依赖/版本 vs 自有项目，逐项标 兼容/需改造/冲突，说明二次开发成本与依据 |
| ③ 生态健康 | 停更/半停滞/单维护者、无社区兜底 | `repo_health.py` 的 停更预警/归档/Star/OpenIssues 信号 + 生态版图（周边插件/文档质量/问题可查性） |
| ④ 合规安全 | GPL/AGPL 传染、依赖传导、CVE | `repo_health.py` 的 许可证分级 + `--package <ecosystem:name>` OSV CVE 清单；结论标 可用/需法务/谨慎 |
| ⑤ 落地计划 | 只给结论不给路径 | 输出"接入方案"：改造范围 / 代码改动量级 / 数据迁移 / 测试验证 / 灰度与回滚 / 量化指标（基线 vs 目标） |
| ⑥ 方法论审视 | 重替换轻优化、重技术轻业务 | 先问：现有代码增量优化能否满足 ≥80%？候选方案与业务场景/团队能力匹配度（不匹配则降级或排除） |

**执行流程**：

```bash
# 每个候选仓库跑健康扫描（事实 + 停更 + 许可证 + CVE）
# 先配 GITHUB_TOKEN，否则匿名只有 60 次/小时，深跑必被限流：export GITHUB_TOKEN="<PAT>"
python "${SKILL_DIR}/scripts/repo_health.py" "owner/repo" --package "pypi:requests"     # GitHub
python "${SKILL_DIR}/scripts/repo_health.py" "https://gitee.com/oschina/xx" --json       # Gitee
```

> **verdict 五态（v6.12）**：`ok` 才有事实；`not_found`（404）是仓库自身的事实，可当结论用；
> `rate_limited`（429）/`forbidden`（403）/`unreachable`（网络）是**我们没查到**，
> 综合等级一律 `unknown`、退出码 3，且报告里不许写成"该仓库无法核实/疑似停更"。
> 未核实就只有两条路：配好 `GITHUB_TOKEN` 重跑，或在报告里如实标"该仓库事实未核实"。

**输出要求**：
- 结论前置"风险标签"：🔴 高风险（停更/强传染许可证/CVE 未修复）/ 🟠 中风险 / 🟢 低风险；无官方 API 数据支撑的指标一律标注"未核实"
- 推荐清单表格增加列：`风险标签 | 许可证 | 最近提交 | 适配性 | 落地成本(高/中/低) | 量化指标`
- 六维任一缺失 → 校验门拦截（写入账本后重跑 `validate_report.py`）

### 7.1 设计目标：不漏项目

传统搜索只返回高星项目，低星但有价值的项目容易被遗漏。采用**四维挖掘策略**确保全网搜索一个不漏：

| 策略 | 说明 | 解决的问题 |
|------|------|-----------|
| **分桶搜索** | 按 star 数分 4 桶（0-100/100-1k/1k-10k/10k+），每桶独立搜索 | 高星项目垄断结果 |
| **低星挖掘** | 专门搜索 stars:<100 的项目，按最近更新排序 | 低星项目被淹没 |
| **依赖图反向挖掘** | 从种子项目出发，搜索依赖它的项目 | 发现生态中的关键小项目 |
| **awesome 列表挖掘** | 搜索 awesome-* 列表并提取其中的项目链接 | 社区精选不遗漏 |

### 7.2 使用示例

```python
from engines.github_deep_search import GitHubDeepSearchEngine

e = GitHubDeepSearchEngine()
# 基础搜索（分桶 + 低星挖掘）
results = e.search("RAG framework", max_results=20, deep=False)
# 深度搜索（+ 依赖图 + awesome 列表）
results = e.search("RAG framework", max_results=30, deep=True)
```

### 7.3 GitHub Code Search（代码级搜索）

```python
from engines.github_deep_search import GitHubCodeSearchEngine

e = GitHubCodeSearchEngine()
# 搜索包含特定代码的项目
results = e.search("from langchain.chains import RetrievalQA", max_results=10)
```

- 配置：`GITHUB_TOKEN` 环境变量（可选，无 Token 有速率限制 60/h）
- 国内可用：✅（GitHub API 国内可直连）
- 速率限制：有 Token 5000/h，无 Token 60/h

---

## 八、国内内容源

### 8.1 设计目标：国内调研最适配

国内调研场景下，百度/搜狗/知乎/微信公众号/百度学术是最重要的内容源。新增 4 个国内引擎：

| 引擎 | 数据源 | 优先级 | 能力 |
|------|--------|--------|------|
| **BaiduSerpEngine** | 百度搜索 SERP | 80 | 通用搜索（含知乎/CSDN/掘金等） |
| **SogouWeixinEngine** | 搜狗微信搜索 | 85 | 微信公众号文章 |
| **SogouZhihuEngine** | 搜狗知乎搜索 | 82 | 知乎问答 |
| **BaiduXueshuEngine** | 百度学术 | 78 | 国内学术论文 |

### 8.2 使用示例

```python
from engines.cn_sources import BaiduSerpEngine, SogouWeixinEngine, SogouZhihuEngine, BaiduXueshuEngine

# 百度搜索
BaiduSerpEngine().search("RAG 框架对比", max_results=10)
# 微信公众号文章
SogouWeixinEngine().search("大模型微调实践", max_results=10)
# 知乎问答
SogouZhihuEngine().search("LangChain vs LlamaIndex", max_results=10)
# 百度学术
BaiduXueshuEngine().search("transformer attention", max_results=10)
```

### 8.3 反爬虫策略

- **curl_cffi TLS 指纹伪装**：所有国内引擎使用 `impersonate="chrome124"`
- **验证码降级**：搜狗遇到验证码时自动降级到百度
- **User-Agent 轮换**：内置 UA 池，随机轮换
- **请求间隔**：默认 1-2 秒间隔，避免触发频控

### 8.4 配置

```bash
# 国内源无需任何配置，开箱即用
# 可选：配置 GITHUB_TOKEN 增强 GitHub 搜索
export GITHUB_TOKEN=your_token

# 可选：安装 curl_cffi 增强反爬虫
pip install curl_cffi
```

---

## 九、推荐度评分系统

### 9.1 设计目标：推荐度与排序

调研报告需输出推荐度和排序，小众结果可借鉴。实现多维度评分 + 分组排序 + 雷达图可视化。

### 9.2 GitHub 项目推荐度（8 维评分）

| 维度 | 权重（default） | 说明 |
|------|----------------|------|
| popularity（人气） | 0.15 | log10(stars+1) 对数缩放 |
| activity（活跃度） | 0.15 | 最近 commit/push 时间 + release 频率 |
| maintenance（维护） | 0.15 | 是否归档 + issue 响应 + 最后更新 |
| community（社区） | 0.10 | contributors + forks + watchers |
| docs（文档） | 0.10 | README 长度 + 是否有文档站 |
| dependency（依赖健康） | 0.10 | 依赖是否过时（有数据时评） |
| relevance（相关性） | 0.15 | 关键词匹配度 + topic 匹配 |
| ecosystem（生态） | 0.10 | 是否被其他高星项目引用 |

**意图识别权重调整**：

| 意图 | 人气 | 活跃 | 维护 | 社区 | 文档 | 依赖 | 相关 | 生态 |
|------|------|------|------|------|------|------|------|------|
| default | 0.15 | 0.15 | 0.15 | 0.10 | 0.10 | 0.10 | 0.15 | 0.10 |
| novel_approach（创新） | 0.05 | 0.15 | 0.10 | 0.10 | 0.10 | 0.05 | **0.35** | 0.10 |
| production_ready（生产） | **0.20** | **0.20** | **0.20** | 0.10 | 0.10 | 0.10 | 0.05 | 0.05 |
| learning（学习） | 0.10 | 0.10 | 0.10 | 0.10 | **0.20** | 0.05 | **0.25** | 0.10 |

**分组排序**（确保低星项目也有展示机会）：

| 分组 | 阈值 | 说明 |
|------|------|------|
| flagship（旗舰） | stars ≥ 1000 | 高星项目组 |
| mainstream（主流） | 100 ≤ stars < 1000 | 主流项目组 |
| niche（小众） | stars < 100 | 小众项目组（可借鉴） |

**推荐等级**（借鉴 ThoughtWorks Technology Radar 四环模型）：

| 等级 | 总分 | 含义 |
|------|------|------|
| **Adopt（采纳）** | ≥ 75 | 可直接采纳 |
| **Trial（试验）** | ≥ 55 | 值得试验 |
| **Assess（评估）** | ≥ 35 | 需进一步评估 |
| **Hold（谨慎）** | < 35 | 谨慎使用 |

### 9.3 学术论文推荐度（5 维评分）

| 维度 | 权重 | 说明 |
|------|------|------|
| citation_impact（引用影响力） | 0.30 | log10(citations+1) + influential 加权 |
| recency（时效性） | 0.20 | 3 年半衰期指数衰减 |
| authority（来源权威） | 0.20 | 顶会/顶刊识别（NeurIPS/ICML/ACL/Nature/Science...） |
| author_h_index（作者 h-index） | 0.10 | 通讯作者 h-index |
| relevance（相关性） | 0.20 | 标题/摘要关键词匹配 |

**推荐等级**：

| 等级 | 总分 | 含义 |
|------|------|------|
| **Must Read（必读）** | ≥ 80 | 必读论文 |
| **Recommended（推荐）** | ≥ 60 | 推荐阅读 |
| **Optional（可选）** | ≥ 40 | 可选阅读 |
| **Skip（跳过）** | < 40 | 跳过 |

### 9.4 雷达图可视化（SVG）

报告自动生成 SVG 雷达图，多维度对比最多 5 个项目/论文：

```python
from report import RadarChartGenerator

svg = RadarChartGenerator.generate(
    items=[
        {'name': 'Project A', 'dimensions': {'popularity': 90, 'activity': 80, ...}},
        {'name': 'Project B', 'dimensions': {'popularity': 60, 'activity': 95, ...}},
    ],
    dimensions=['popularity', 'activity', 'maintenance', 'community', 'docs', 'dependency', 'relevance', 'ecosystem'],
    dimension_labels={'popularity': '人气', 'activity': '活跃', ...},
    max_items=5,
    size=400,
)
```

- 纯 SVG 生成，不依赖外部库
- 支持暗色模式
- 最多 5 个项目对比，8 种配色

### 9.5 使用示例

```python
from recommend import GitHubRecommender, PaperRecommender, detect_intent

# GitHub 项目推荐度评分
rec = GitHubRecommender()
score = rec.score(repo_data={'stars': 5000, 'pushed_at': '2026-08-01', ...}, query='RAG framework', intent='default')
print(f"总分: {score.total_score}, 等级: {score.grade}, 分组: {score.group}")

# 意图识别
intent = detect_intent("寻找创新的小众 RAG 方案")  # → 'novel_approach'

# 分组排序
ranked = rec.rank_results(results_list, query='RAG framework', intent='novel_approach')
# ranked 按 flagship → mainstream → niche 顺序排列，每组内按总分降序
```

---

## 十、方法论

### 10.1 MECE 问题树 + 6 状态机（秘塔问题链）

- **M**utually **E**xclusive：子问题互不重叠
- **C**ollectively **E**xhaustive：子问题合起来覆盖全部
- **6 状态**：pending → searching → verified/conflict/supplementing → completed

实现：`scripts/plan.py` 的 `PlanGenerator.generate_plan()`（多视角注入 + unanswered_questions）

### 10.2 CRAAP 评分（五维可信度评估）

| 维度 | 含义 | 分值 |
|------|------|------|
| **C**urrency | 时效性 | 0-100 |
| **R**elevance | 相关性 | 0-100 |
| **A**uthority | 权威性（域名 + 作者 + Tier） | 0-100 |
| **A**ccuracy | 准确性（可验证性） | 0-100 |
| **P**urpose | 目的性（偏见检测） | 0-100 |

实现：`scripts/score.py` 的 `CraapScorer.score(result, query)`（五维各 0-100 加权总分，Tier 加权调节）

### 10.3 交叉验证

**硬性规则**：同一结论需要 **≥2 个独立来源**支持。

**独立来源定义（v6.4 语义级）**：按内容指纹去重——同一通稿跨站转载（标题归一化后相同/高相似）只算 **1** 个独立来源；`ledger.status` 的 `effective_sources` 为指纹去重后的有效独立数，sufficient/校验门均以此为准（防转载虚高）。

实现：`scripts/verify.py` 的 `CrossVerifier.verify(results)`（语义聚合→独立来源指纹去重计数→矛盾检测）+ `scripts/similarity.py`（`group_by_similarity` 近义聚类 / `numeric_conflict` 数值矛盾）

### 10.4 多信号反思循环（Kimi 式）

实现：`scripts/reflect.py` 的 `_should_continue()`

**停止信号**：
1. 覆盖率 ≥ 阈值（0.75）
2. 达到最大反思轮次
3. **边际收益递减**：Δ覆盖率 < 0.05 且覆盖率 ≥ 0.6 → 收敛
4. **无高优先级空白**且覆盖率 ≥ 0.6 → 停止

### 10.5 CER 结构（Claim-Evidence-Reasoning）

报告中每个关键结论都应有 CER 结构：
- **Claim**：结论
- **Evidence**：证据（带来源 URL）
- **Reasoning**：推理链

### 10.6 PICO 框架（对比类调研）

- **P**opulation：研究主体
- **I**ntervention：干预措施
- **C**omparison：对比对象
- **O**utcome：评估结果

### 10.7 推荐度评分

- **GitHub 项目**：8 维评分（人气/活跃/维护/社区/文档/依赖/相关/生态）+ 分组排序（旗舰/主流/小众）+ 4 级推荐（Adopt/Trial/Assess/Hold）
- **学术论文**：5 维评分（引用/时效/权威/h-index/相关）+ 4 级推荐（Must Read/Recommended/Optional/Skip）
- **意图识别**：根据查询意图调整权重（novel_approach 降低人气权重、提升相关性权重）

实现：`scripts/recommend.py` 的 `GitHubRecommender` / `PaperRecommender` / `detect_intent`

---

## 十一、与现有 skill 的路由策略

| 用户意图 | 推荐 skill | 备注 |
|---------|-----------|------|
| "深度调研 X" | **deep-research-ultra** | 本 skill，完整 Plan-Execute-Synthesize-Reflect |
| "搜一下 X" / "research first" | research-first | 轻量前置调研 |
| "近 30 天 X 怎么样" | last30days | 时效性调研 |
| "找 X 的学术论文" | sciverse / **本 skill 学术路由** | 学术深度 |
| "找 GitHub 上的 X 项目" | oss-finder / **本 skill 开源路由（含深搜）** | 开源项目（不漏低星） |
| "X 在 Reddit 上怎么样" | agent-reach / **本 skill 社区路由** | 社区口碑 |
| "国内 X 怎么样" | **本 skill 国内源路由** | 百度/搜狗/知乎/微信 |

**智能路由示例**：
- "最新 LLM 论文" → 自动路由到学术链（arxiv + paper-search + openalex + s2 + pubmed + **baidu-xueshu**）
- "RAG 开源实现" → 自动路由到开源链（**github-deep-search** + oss-finder + tavily + open-websearch）
- "国内 RAG 落地实践" → 自动路由到国内链（**baidu-serp + sogou-weixin + sogou-zhihu**）
- "什么是 RAG" → 自动路由到定义链（tavily + websearch + defuddle）

---

## 十二、核心原则（十一条铁律）

1. **澄清优先** — 模糊主题必须先问用户，不能自作主张
2. **MECE 拆解** — 子问题必须互斥穷尽，不重叠不遗漏
3. **智能路由** — 根据查询意图自动选择数据源（理论→学术，开源→GitHub，国内→百度/搜狗）
4. **计划确认门** — 计划先呈现待确认清单，用户增删/批准后才执行
5. **CRAAP 评分** — 每个来源五维评分，标注 Tier 分级
6. **交叉验证** — 同一结论需 ≥2 个独立来源支持
7. **引用可追溯** — 每个关键结论必须带账本 [N] 引用，发布前校验门通过才交付
8. **诚实标注** — 无法验证的信息标注"待确认"，矛盾点明示
9. **多视角对抗** — 复杂调研必须过专家团评审（域专家/怀疑者/实践者），防自证
10. **子 Agent 并行** — effort ≥ standard 时按 breadth 并行派发子研究员，结果落盘
11. **推荐度排序** — GitHub 项目和论文必须输出推荐度评分与分组排序

---

## 十三、环境检测与配置

### 13.1 首次使用必做

```bash
# 1. 配置 MCP（推荐 --core 免费模式）
bash "${SKILL_DIR}/scripts/setup-mcp.sh" --core

# 2. 检查数据源可用性
python "${SKILL_DIR}/scripts/research.py" --mcp-check

# 3. 列出所有可用引擎（共 32 个）
python "${SKILL_DIR}/scripts/research.py" --list

# 4.（可选）安装 curl_cffi 增强 TLS 伪装
pip install curl_cffi

# 5.（可选）配置 GITHUB_TOKEN 增强 GitHub 深度搜索
export GITHUB_TOKEN=your_token
```

### 13.2 配置场景

| 场景 | 推荐操作 |
|------|----------|
| 零配置快速开始 | `bash setup-mcp.sh --core`（免费 MCP）+ 国内源开箱即用 |
| 国内无 VPN | `--core` + curl_cffi + 国内源（百度/搜狗/百度学术无需 VPN） |
| 学术深度调研 | `--core` + 配置 `UNPAYWALL_EMAIL` + Semantic Scholar（可选 Key） |
| 开源项目深搜 | 配置 `GITHUB_TOKEN`（5000/h 速率） |
| 强反爬场景 | Crawl4AI Docker + Camoufox |
| 国内调研 | 国内源自动启用（百度/搜狗微信/搜狗知乎/百度学术） |

---

## 十四、使用示例

### 14.1 智能路由

```bash
# 查看路由分析（不执行搜索）
python "${SKILL_DIR}/scripts/research.py" "RAG 开源实现" --route

# 智能路由自动选择数据源
python "${SKILL_DIR}/scripts/research.py" "最新 LLM 论文" --auto-route

# 深度模式 + 智能路由 + 多轮反思
python "${SKILL_DIR}/scripts/research.py" "深度调研大语言模型微调" --depth deep --auto-route --reflect-rounds 3
```

### 14.2 基本搜索

```bash
# 自动选择数据源（默认 HTML 报告）
python "${SKILL_DIR}/scripts/research.py" "Python Web 框架"

# 指定深度与反思轮数
python "${SKILL_DIR}/scripts/research.py" "AI agent" --depth deep --reflect-rounds 3

# 指定数据源
python "${SKILL_DIR}/scripts/research.py" "AI agent" --sources tavily,arxiv

# 仅生成 MECE 计划（不执行搜索）
python "${SKILL_DIR}/scripts/research.py" "RAG 最佳实践" --plan-only

# 输出到文件
python "${SKILL_DIR}/scripts/research.py" "FastAPI vs Django" --format html -o report.html
```

### 14.3 新增命令（子 Agent 并行 / 专家团 / 证据账本 / 校验）

```bash
# 1. 计划确认门：仅生成计划 + 待确认清单（含 effort/breadth/专家团建议）
python "${SKILL_DIR}/scripts/research.py" "大模型微调成本" --plan-only --effort deep --breadth 8 --perspectives "domain_expert,skeptic,practitioner"

# 2. 子 Agent 编排 + 证据账本落盘（并行派发时每个子 Agent 用自己的 --ledger 目录）
python "${SKILL_DIR}/scripts/research.py" "子主题A" --ledger .research/session/ledger --perspectives domain_expert

# 3. 证据账本管理
python "${SKILL_DIR}/scripts/ledger.py" status --session .research/session/ledger     # 统计/证据充分性
python "${SKILL_DIR}/scripts/ledger.py" export --session .research/session/ledger --format md

# 4. 专家团评审清单生成（供主 Agent 消化执行）
python "${SKILL_DIR}/scripts/panel.py" perspectives                                   # 列出 5 内置角色
python "${SKILL_DIR}/scripts/panel.py" review-outline --input outline.md --roles domain_expert,skeptic,practitioner

# 5. 来源 Tier 分级（独立工具）
python "${SKILL_DIR}/scripts/tier.py" "https://www.gov.cn/x"                          # → Tier 1

# 6. 发布前校验门（exit 0=通过）+ 防伪戳
python "${SKILL_DIR}/scripts/validate_report.py" --report report.md --ledger .research/session/ledger --stamp
python "${SKILL_DIR}/scripts/validate_report.py" --report report.md --ledger .research/session/ledger --verify-stamp
```

### 14.4 路由决策示例

**中文技术问题**（如 "Python Web 框架对比"）：
```
查询类型: comparison
引擎链: tavily, agent-reach, arxiv, sogou-weixin
置信度: 0.95
```

**英文学术问题**（如 "latest LLM research papers"）：
```
查询类型: academic
引擎链: arxiv, paper-search, openalex, semantic-scholar, pubmed, baidu-xueshu
置信度: 0.95
```

**开源项目搜索**（如 "RAG 开源实现"）：
```
查询类型: opensource
引擎链: github-deep-search, github-code-search, oss-finder, tavily, open-websearch
置信度: 0.95
```

**国内调研**（如 "国内 RAG 落地实践"）：
```
查询类型: general（国内适配）
引擎链: baidu-serp, sogou-weixin, sogou-zhihu, baidu-xueshu
置信度: 0.85
```

---

## 十五、代码结构

```
scripts/
├── research.py              # 主入口（--env-check/--probe/--auto-route/--effort/--breadth/--dimensions/--ledger/--min-relevance）
├── console.py               # CLI 强制 UTF-8 输出（Windows GBK 控制台曾直接 UnicodeEncodeError）
├── probe.py                 # 引擎功能自检（探针查询表 + ok/empty/failed 判定）
├── env_check.py             # 环境分级验证（minimal/opensource/academic/full）
├── search.py                # 引擎兼容入口（保留 --sources baidu,bing 等旧参数）
├── setup-mcp.sh             # MCP 一键配置脚本
├── router.py                # 智能路由（三级级联 Rule→Semantic→LLM）
├── recommend.py             # 推荐度评分（GitHub/PaperRecommender + detect_intent）
├── tier.py                  # 来源 Tier 分级（域名校验，score/report/validate 共用）
├── ledger.py                # 证据账本（claim→source 可溯源，多子Agent并发写）
├── similarity.py            # 转载指纹去重 + claim 语义聚类 + 数值矛盾检测
├── repo_health.py           # 仓库健康扫描（官方 API 事实 + 停更 + 许可证传染 + OSV CVE；verdict 五态，限流判 unknown）
├── panel.py                 # 专家团评审清单生成（多视角 + 红蓝对抗契约）
├── validate_report.py       # 发布前校验门（引用一致性/反查/覆盖率/章节/Tier4占比/六维要素）+ 防伪戳 --stamp/--verify-stamp
├── engines/
│   ├── __init__.py          # 引擎导出聚合（32 个数据源，28 个可搜索）
│   ├── base.py              # SearchEngine 抽象基类 + EngineMetadata + EngineRegistry
│   ├── mcp_client.py        # MCP 客户端封装
│   ├── mcp_engines.py       # MCP 服务器封装（Tavily/Firecrawl/open-websearch/arxiv/paper-search）
│   ├── academic_engines.py  # 学术直连（OpenAlex/S2/PubMed）
│   ├── academic_fulltext.py # 学术全文+引用图谱（arXiv全文/Unpaywall/S2图谱）
│   ├── skill_engines.py     # 全局 skill 封装（agent-reach/oss-finder/last30days/sciverse/defuddle/context7）
│   ├── github_deep_search.py# GitHub 深度搜索（分桶+低星+依赖图+awesome）+ Code Search
│   ├── platform_engines.py  # 国内平台（Gitee 需 token / ModelScope 模型卡详情）
│   ├── cn_sources.py        # 国内内容源（百度/搜狗微信/搜狗知乎/百度学术）
│   ├── builtin.py           # Claude 内置工具封装（WebSearch/WebFetch）
│   ├── crawl4ai_engine.py   # Crawl4AI 浏览器自动化 + LayeredCrawler
│   └── fallback.py          # 降级引擎（ddgs/百度/Bing/SearXNG）+ curl_cffi TLS 伪装 + LAST_HTTP_ERROR 诊断
├── plan.py                  # MECE 问题树 + 6 状态机（多视角注入 + 通用维度兜底）
├── score.py                 # CRAAP 五维评分（Tier 加权 + has_low_quality_ratio）
├── verify.py                # 交叉验证（矛盾检测）
├── reflect.py               # 反思循环 + 多信号停止（证据充分性/边际claim收敛）
├── report.py                # 报告生成（元信息 + 账本附录 D + Tier 分布）
├── progress.py              # 进度跟踪 + ETA
├── cache.py                 # LRU 缓存
└── tests/
    ├── test_core.py         # 核心模块单元测试
    ├── test_console.py      # GBK 控制台冒烟（CLI 不崩 + 中文以 UTF-8 落管道）
    ├── test_probe.py        # 功能自检判定（0 结果 ≠ 可用）
    ├── test_mcp_client.py   # MCP 真连接（一会话一进程 / 超时可中断 / 不留孤儿）
    ├── test_ledger_hygiene.py  # 证据/claim 分离 + merge 拒收与去重计数
    ├── test_repo_health_verdict.py # 仓库扫描五态（限流=unknown / 404=真结论 / token 真发出）
    ├── test_validation_stamp.py # 防伪戳（盖戳只在过门后 / 改正文或账本即失效 / 手抄骗不过）
    └── test_v6.py           # tier/ledger/panel/validate/plan/reflect/score/平台引擎/相关性过滤
```

---

## 十六、禁止行为

- ❌ **禁止跳过澄清** — 模糊主题必须先确认
- ❌ **禁止无来源结论** — 每个结论必须有出处
- ❌ **禁止静默降级** — 数据源不可用时必须告知用户（哪个引擎、什么原因、换成了什么）
- ❌ **禁止单源结论** — 关键结论需 ≥2 独立来源
- ❌ **禁止递归调用本 skill** — 子 Agent 的 prompt 中不得包含"深度调研"、"帮我研究"、"全面分析"等触发词
- ❌ **禁止使用 HTML regex 解析** — 已弃用，改用 MCP 或 defuddle 或 Crawl4AI
- ❌ **禁止遗漏低星项目** — 开源调研必须使用 GitHub 深度搜索（分桶+低星+依赖图+awesome）
- ❌ **禁止结论无账本引用** — 复杂调研（effort ≥ standard）结论必须带 [N] 编号并过发布前校验门
- ❌ **禁止跳过专家团** — effort ≥ deep 的调研必须过专家团评审（域专家/怀疑者/实践者）
- ❌ **禁止忽略相关性告警** — 搜索输出「⚠️ N 条与查询词几乎无重叠」时，必须换查询词/补
  `--sources` 重跑，或把相关结论降级为"待确认"；`--min-relevance`（默认 50）不是可调到 0 的装饰
- ❌ **禁止把长报告正文塞进返回值/最终消息** — 一律落盘 report.md，回复只给 Phase 6 的短摘要
- ❌ **禁止跳过 --probe** — `--list`/`--env-check` 的 ✅ 只代表配置就绪，不代表今天出得来数据
- ❌ **禁止越过 Phase 0 环境闸门**（v6.8）— `--probe` 退出码 3 时不许开跑，也不许自行加 `--allow-degraded`；停下来把配置指引给用户，等他配好或明确授权降级
- ❌ **禁止凭自述交付**（v6.11）— 报告尾部没有 `validate_report.py --stamp` 盖下的 `drux:validated` 戳，就不许说"校验门 passed"；没戳只能写"未过门：<issue>"。手抄一行戳过不了 `--verify-stamp` 的指纹复核
- ❌ **禁止把搜索结果当结论**（v6.10）— `--ledger` 只登记证据；claim 必须用 `add-claim` 显式立论并挂来源。要沿用旧行为得自己加 `--auto-claim` 并说明理由
- ❌ **禁止把 MCP 的"配置就绪"当"连上了"**（v6.9）— 只有 `--probe`/`--mcp-check` 真握手拿到结果才算这个源存在；握手超时要先预热（首次 npx/uvx 下包），别静默丢掉这个源
- ❌ **禁止探索性空转** — 不 `ls` skill 目录、不读脚本源码、不跑 `--help`；文档即接口
- ❌ **禁止只跑不落地** — 每个阶段都要落盘（账本/大纲/报告），中断必须留得下可续用的产物

---

## 十七、参考资料

### 内部参考

- [references/mcp-config.md](references/mcp-config.md) — MCP 配置指南
- [references/tool-integration.md](references/tool-integration.md) — 外部工具/skill 集成契约
- [references/optimization-plan-v4.md](references/optimization-plan-v4.md) — 四层架构优化方案
- [references/optimization-plan-v5.md](references/optimization-plan-v5.md) — v5 优化方案
- [references/migration-v3-to-v4.md](references/migration-v3-to-v4.md) — v3→v4 迁移指南
- [references/v6-research-notes.md](references/v6-research-notes.md) — 方法论与开源方案调研笔记（12 前沿模式 + Top 12 开源 + 能力缺口映射）
- [references/intelligent-routing-research.md](references/intelligent-routing-research.md) — 智能路由设计
- [references/大厂方法论落地调研-v2.md](references/大厂方法论落地调研-v2.md) — Kimi/秘塔方法论
- [references/论文全文与引用图谱调研-v2.md](references/论文全文与引用图谱调研-v2.md) — arXiv/Unpaywall/S2
- [references/浏览器自动化与反爬虫调研-v2.md](references/浏览器自动化与反爬虫调研-v2.md) — Crawl4AI/curl_cffi
- [references/GitHub深度搜索技巧调研.md](references/GitHub深度搜索技巧调研.md) — GitHub 深度搜索技巧
- [references/调研报告格式最佳实践调研.md](references/调研报告格式最佳实践调研.md) — 报告格式最佳实践
- [references/国内大厂深度研究方案调研-v3.md](references/国内大厂深度研究方案调研-v3.md) — 国内大厂深度研究
- [references/深度研究开源项目调研-v3.md](references/深度研究开源项目调研-v3.md) — 开源深度研究项目
- [references/国内智能体平台与调研专家团调研.md](references/国内智能体平台与调研专家团调研.md) — 国内智能体平台与专家团
- [references/anti-bot-research-2026.md](references/anti-bot-research-2026.md) — 反爬虫专题调研
- [references/大厂深度研究方法论调研报告.md](references/大厂深度研究方法论调研报告.md) — 大厂方法论（早期调研）
- [references/开源深度研究项目调研报告.md](references/开源深度研究项目调研报告.md) — 开源项目（早期调研）
- [references/科研论文检索方案调研报告.md](references/科研论文检索方案调研报告.md) — 论文检索方案

### 外部参考

- **OpenAI Deep Research**：Plan → Execute → Synthesize 三步范式
- **Anthropic Multi-Agent Research System**：https://www.anthropic.com/engineering/built-multi-agent-research-system（Orchestrator-Worker）
- **GPT Researcher**：https://github.com/assafelovic/gpt-researcher（Editor-Reviewer-Revisor 流水线）
- **Stanford STORM / Co-STORM**：https://github.com/stanford-oval/storm（多视角提问）
- **dzhng/deep-research**：https://github.com/dzhng/deep-research（depth/breadth 旋钮）
- **Salesforce EDR（Don't Stop Early）**：arXiv 2604.24978（证据充分性停止）
- **LangChain open_deep_research**：https://github.com/langchain-ai/open_deep_research
- **字节跳动 DeerFlow 2.0**：https://github.com/bytedance/deer-flow
- **Kimi 研究方法论**：多信号反思 + 边际收益递减检测
- **秘塔 AI 问题链**：6 状态可视化研究日志
- **麦肯锡方法**：MECE 原则、假设驱动、逻辑树
- **CRAAP Test**：信息可信度评估标准
- **CER（Claim-Evidence-Reasoning）**：科学论证结构
- **ThoughtWorks Technology Radar**：四环模型（Adopt/Trial/Assess/Hold）

---

## 十八、测试

```bash
# 运行全部测试
cd "${SKILL_DIR}/scripts"
python -m pytest tests/ -v

# 测试覆盖
# - engines/base.py: EngineMetadata, SearchResult, EngineRegistry
# - cache.py: LRUCache
# - plan.py: IssueTree, PlanGenerator, DataSourceMatcher, 多视角注入
# - score.py: CraapScorer（含 Tier 加权 / has_low_quality_ratio）
# - verify.py: CrossVerifier
# - reflect.py: Reflector（多信号停止 + 证据充分性 / 边际 claim 收敛）
# - report.py: ReportGenerator, MermaidGenerator, RadarChartGenerator
# - progress.py: ProgressTracker, QualityAssessor
# - router.py: QueryPreprocessor, RuleRouter, CircuitBreaker, QueryRouter
# - academic_fulltext.py: ArxivFulltext, Unpaywall, CitationGraph
# - crawl4ai_engine.py: Crawl4aiEngine, LayeredCrawler
# - recommend.py: GitHubRecommender, PaperRecommender, detect_intent
# - engines/github_deep_search.py: GitHubDeepSearchEngine, GitHubCodeSearchEngine
# - engines/cn_sources.py: BaiduSerpEngine, SogouWeixinEngine, SogouZhihuEngine, BaiduXueshuEngine
# - tier.py: domain_tier / tier_label / tier_penalty
# - ledger.py: ResearchLedger（并发追加 / merge / status / export_md）
# - panel.py: PanelReviewer（perspectives / review_outline / review_draft）
# - validate_report.py: validate_report（引用一致性 / 反查 / 覆盖率 / 章节 / Tier4 占比 / 六维要素）
# - console.py: GBK 控制台冒烟（CLI 不崩 + 中文以 UTF-8 落管道）
# - probe.py: 功能自检判定（0 结果 ≠ 可用 / 缺配置可见 / 异常归失败）
# - platform_engines.py: Gitee 需 token / 空数组≠不可用 / ModelScope 仅详情
# - research.py: filter_by_relevance（够用才丢，不够用保留并告警）
# - plan.py: 维度兜底（未命中模板也出 ≥4 个子问题）
```

真实环境验证（联网，非单测）：

```bash
python "${SKILL_DIR}/scripts/research.py" --probe                 # 引擎功能自检
python "${SKILL_DIR}/scripts/research.py" "<主题>" --plan-only --effort standard \
  --dimensions "现状与主要玩家,技术路线,生态与成熟度,风险与局限,落地成本"   # 子问题数应等于维度数
```

---

## 十九、更新历史

更新说明与迁移指南见 [CHANGELOG.md](CHANGELOG.md)。
