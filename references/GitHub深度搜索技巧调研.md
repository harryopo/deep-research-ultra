# GitHub 深度搜索技巧调研报告

> 调研目标：解决 deep-research-ultra skill 在调研开源项目时漏掉相关低星项目的问题。
> 核心诉求："深度调研就是全网搜索，一个不漏"。
> 调研日期：2026-08-08
> 调研人：开源项目调研专家（AI）

---

## 概述（为什么要深度搜索）

### 问题背景

当前 `deep-research-ultra` skill 的 `OssFinderEngine`（位于 `scripts/engines/skill_engines.py`）存在以下不足：

1. **仅生成调用模板**：`get_invocation_template()` 只生成一段提示词交给 Claude 通过 `oss-finder` skill 执行，本身不构造高级搜索查询。
2. **无分页机制**：没有翻页获取全部结果的逻辑，可能只取到第一页（默认 10~30 条）。
3. **无多维度组合查询**：不会按 stars 分桶、按 topic、按语言、按时间窗口做多轮组合搜索。
4. **无低星项目专门策略**：`stars_min` 参数只会"提高门槛"，从不会反向用 `stars:<N` 主动挖掘低星但相关的项目。
5. **无交叉验证**：不会用 GitHub API、gh CLI、OSS Insight、Libraries.io 等多源交叉补全。
6. **无依赖图/dependents 挖掘**：不会从种子项目出发反向找谁在用它。

### 后果

- GitHub 搜索默认按 "best-match" 排序，强偏好高星、高活跃项目，低星项目被埋在后面。
- 单次查询 REST API 最多返回 1000 条，且只扫描约 4000 个仓库的子集——单关键词一次搜索根本"搜不全"。
- 结果：漏掉大量低星但高质量、或新创建但高度相关的项目。

### 解决思路

"一个不漏"在工程上无法做到 100%，但可以通过**多维度组合查询 + 分页穷举 + 多源交叉 + 依赖图反向挖掘**逼近覆盖率上限。本报告给出完整方法论与可落地的 skill 改进方案。

---

## 1. GitHub Advanced Search 高级语法

### 1.1 完整语法参考

GitHub 搜索支持限定符（qualifier）自由组合，所有限定符可任意叠加。以下是仓库搜索的核心限定符（来源：GitHub 官方文档 `searching-for-repositories`）。

#### 1.1.1 搜索范围（in:）

| 限定符 | 说明 | 示例 |
|--------|------|------|
| `in:name` | 仓库名匹配 | `in:name llm` |
| `in:description` | 描述匹配 | `in:description "agent framework"` |
| `in:readme` | README 匹配 | `in:readme deep research` |
| `in:topics` | topic 匹配 | `in:topics deep-learning` |
| `in:name,description` | 多字段组合 | `in:name,description rag` |

> 关键点：`in:readme` 是发现"标题不起眼但 README 写清楚了用途"的低星项目的核心手段。

#### 1.1.2 数量类限定符（支持 `>` `>=` `<` `<=` 和范围 `n..m`）

| 限定符 | 说明 | 示例 |
|--------|------|------|
| `stars:n` | 星标数 | `stars:>=10`、`stars:10..100`、`stars:<50` |
| `forks:n` | fork 数 | `forks:>=5` |
| `size:n` | 仓库大小（KB） | `size:<5000`（小而精） |
| `followers:n` | 关注者 | `followers:>=10` |
| `good-first-issues:n` | good first issue 数 | `good-first-issues:>=3` |
| `help-wanted-issues:n` | help wanted 数 | `help-wanted-issues:>=5` |
| `number-topics:n` | topic 数量 | `number-topics:>=3` |

> 日期/数值范围语法：`stars:10..100` 表示 10 到 100；`stars:>=10 stars:<100` 等价。

#### 1.1.3 时间类限定符（格式 `YYYY-MM-DD`，支持 `>` `<` 范围）

| 限定符 | 说明 | 示例 |
|--------|------|------|
| `created:YYYY-MM-DD` | 创建时间 | `created:>2024-01-01`（新项目） |
| `pushed:YYYY-MM-DD` | 最近 push | `pushed:>2025-06-01`（活跃维护） |
| `updated:YYYY-MM-DD` | 更新时间 | `updated:>2025-01-01` |

> `pushed` 比 `updated` 更能反映"代码是否还在动"。`created:>YYYY` 是发现新生低星项目的关键。

#### 1.1.4 分类限定符

| 限定符 | 说明 | 示例 |
|--------|------|------|
| `language:NAME` | 语言 | `language:python` |
| `topic:NAME` | topic（精确） | `topic:llm`、`topic:agent` |
| `license:KEYWORD` | 许可证 | `license:mit`、`license:apache-2.0` |
| `user:NAME` | 用户名 | `user:sindresorhus` |
| `org:NAME` | 组织 | `org:microsoft` |
| `repo:OWNER/NAME` | 单仓库 | `repo:langchain-ai/langchain` |

#### 1.1.5 状态限定符

| 限定符 | 说明 | 示例 |
|--------|------|------|
| `archived:true/false` | 是否归档 | `archived:false`（排除归档） |
| `is:public/private` | 可见性 | `is:public` |
| `is:fork` | 是否 fork | `is:fork`（只看 fork） |
| `fork:true/only` | fork 策略 | `fork:true`（含 fork）；默认不含 |
| `mirror:true` | 镜像仓库 | `mirror:true` |

> `fork:true` 与 `include-forks` 是发现"社区 fork 中加了新功能但未被原项目收录"的项目的手段。

### 1.2 低星项目搜索策略

GitHub 默认按 best-match 排序，强偏好高星。要主动挖低星项目，核心是**反向用 stars 上界 + 缩小时间/语言/topic 窗口 + 改排序方式**。

#### 策略一：stars 分桶扫描

把 stars 区间切成多个桶，逐桶搜索，避免高星淹没低星：

```
# 桶1：极低星但近期活跃
keyword in:readme stars:<10 pushed:>2025-06-01 language:python
# 桶2：低星
keyword stars:10..50 pushed:>2025-01-01 language:python
# 桶3：中低星
keyword stars:50..200 language:python
# 桶4：中星
keyword stars:200..1000 language:python
# 桶5：高星（对照组）
keyword stars:>1000 language:python
```

#### 策略二：改排序方式

REST API 支持 `sort=stars/forks/updated/help-wanted-issues/good-first-issues`，`order=asc/desc`。
- `sort=updated&order=desc`：按最近更新，低星新项目会上浮。
- `sort=stars&order=asc`：按星升序——**直接把最低星项目排到最前**，这是挖低星项目最直接的技巧（网页搜索也支持 `?o=asc&s=stars`）。

#### 策略三：时间窗口收窄 + 关键词扩展

低星项目数量巨大，单查询必超 1000 上限。必须按 `created` 时间窗 + 多组同义词拆分查询。

### 1.3 组合查询示例

```
# 找"LLM agent 框架"的所有相关项目（含低星）
# 1. 按描述/README 多关键词组合
"llm agent" in:description,readme language:python stars:<500 pushed:>2024-06-01 archived:false
# 2. 用 OR 扩展同义词
("agent framework" OR "agent sdk" OR "agent toolkit") in:description stars:<300
# 3. 按 topic
topic:llm-agents OR topic:ai-agent OR topic:autonomous-agents
# 4. 找刚创建的（新星）
"deep research" in:readme created:>2025-01-01 stars:<50
# 5. 排除噪声（排除 awesome 列表本身、教程类）
"rag framework" in:description -filename:awesome -filename:curated
```

### 1.4 Code Search 语法（新版）

GitHub Code Search（基于 Blackbird 索引）支持更强的语法，可用于在源码中反向发现项目：

- 布尔运算：`AND`、`OR`、`NOT`，可用括号 `(a OR b) AND NOT c`
- 正则：`/pattern/`（如 `/class.*Agent/`）
- 精确短语：`"sparse index"`
- 限定符：`repo:`、`org:`、`user:`、`enterprise:`、`language:`、`license:`、`path:`（含 glob）、`symbol:`、`content:`、`is:`

> Code Search 用途：搜某个独特 API/类名/配置项，反向找到所有用了它的仓库——这是发现"小众但专精"项目的高效手段。例如搜 `import deep_research_ultra` 可找到所有依赖该库的仓库。

---

## 2. GitHub CLI 搜索能力

`gh` CLI 是最易自动化、最适合接入流水线的工具。

### 2.1 gh search repos

```bash
gh search repos [<query>] [flags]
```

关键 flags（来源：`cli.github.com/manual/gh_search_repos`）：

| Flag | 说明 |
|------|------|
| `--stars <number>` | 星标数过滤（`">=10"`、`"10..100"`） |
| `--forks <number>` | fork 数 |
| `--followers <number>` | 关注者 |
| `--size <string>` | 仓库大小（KB） |
| `--language <string>` | 语言 |
| `--topic <strings>` | topic |
| `--license <strings>` | 许可证 |
| `--created <date>` | 创建时间 |
| `--updated <date>` | 最近更新 |
| `--owner <strings>` | 所有者 |
| `--number-topics <number>` | topic 数 |
| `--good-first-issues <number>` | good first issue |
| `--help-wanted-issues <number>` | help wanted |
| `--archived` | 归档状态 |
| `--include-forks <string>` | `{false|true|only}` |
| `--visibility <strings>` | `{public|private|internal}` |
| `--match <strings>` | `{name|description|readme}` |
| `--sort <string>` | `{forks|help-wanted-issues|stars|updated}` |
| `--order <string>` | `{asc|desc}`（默认 desc） |
| `-L, --limit <int>` | 最多取数（默认 30） |
| `--json <fields>` | JSON 输出指定字段 |
| `-w, --web` | 在浏览器打开 |

JSON 字段：`createdAt, description, forksCount, fullName, isArchived, isFork, language, license, name, openIssuesCount, owner, pushedAt, size, stargazersCount, updatedAt, url, visibility, watchersCount` 等。

#### 低星挖掘示例

```bash
# 按星升序，直接捞低星
gh search repos "llm agent" --language=python --sort=stars --order=asc --limit=100 --json fullName,stargazersCount,description,pushedAt

# 多桶分页
gh search repos "deep research" in:readme stars:<10 pushed:>2025-06-01 --limit=100
gh search repos "deep research" in:readme stars:10..50 --limit=100

# 用原生语法排除
gh search repos "rag" -- -topic:awesome -filename:awesome
```

### 2.2 gh search code

```bash
gh search code <query> [flags]
```

flags：`--extension`、`--filename`、`--language`、`--match {file|path}`、`--owner`、`--repo`、`--size`、`--limit`。

```bash
# 搜源码里引用某库的仓库
gh search code "deep_research_ultra" --language=python --limit=100 --json repository,path,url
# 搜独特类名
gh search code "class DeepResearchEngine" --limit=50
```

> 注意：`gh search code` 走的是 legacy code search，新 Blackbird 语法（regex 等）尚不支持，需用 REST API `/search/code` 或网页。

### 2.3 gh search topics

```bash
gh search topics [<query>] [flags]
```

按 topic 名搜索，返回 topic 的 `related` topics 与 `created/curated` 数。用于发现可用的 topic 标签后再用 `topic:` 精搜仓库。

### 2.4 gh api（GraphQL / REST）

`gh api` 可直接调用任意 REST 端点或 GraphQL，是分页穷举的主力：

```bash
# REST 分页穷举
gh api '/search/repositories?q=llm+agent+language:python+stars:<100&sort=stars&order=asc&per_page=100&page=1'

# GraphQL
gh api graphql -f query='
{
  search(query: "llm agent language:python stars:<100", type: REPOSITORY, first: 100) {
    repositoryCount
    edges { node { ... on Repository { nameWithOwner stargazerCount description pushedAt url } } }
    pageInfo { endCursor hasNextPage }
  }
}'
```

### 2.5 分页与导出

- `gh search repos --limit` 最大受后端约束（通常单命令可到 100~1000，但底层分页 100/页）。
- 翻全部结果需用 `gh api` + `page` 参数或 GraphQL `cursor` 分页，直到 `hasNextPage=false`。
- 导出：`--json ... > results.json`，再交给 Python 评分去重。

---

## 3. GitHub API 搜索

### 3.1 REST API

端点：

| 端点 | 用途 |
|------|------|
| `GET /search/repositories` | 搜仓库 |
| `GET /search/code` | 搜代码（需认证，10 req/min） |
| `GET /search/issues` | 搜 issue/PR |
| `GET /search/commits` | 搜提交信息 |
| `GET /search/users` | 搜用户 |
| `GET /search/topics` | 搜 topic |
| `GET /search/labels` | 搜 label |

#### 关键限制（务必遵守，否则丢数据）

1. **最多 1000 条/查询**：单 query 最多返回 1000 条（10 页 × 100）。要超过必须拆分查询。
2. **速率限制**：认证 30 req/min（code 10 req/min），未认证 10 req/min。
3. **查询长度**：≤256 字符（不含限定符）。
4. **布尔运算符上限**：最多 5 个 `AND/OR/NOT`。
5. **搜索范围裁剪**：为保性能，后端只扫描约 4000 个匹配仓库的子集——单关键词覆盖不全。
6. **`incomplete_results: true`**：超时会返回已找到的部分结果并置此标记。

#### 分页策略

```
per_page=100，page=1..10（最多取满 1000）
解析 Link header 判断是否还有下一页
```

### 3.2 GraphQL API

GraphQL 的 `search` connection 更灵活，可在单次请求中嵌套拉取关联数据（star、dependents、languages、repositoryTopics），减少请求次数。

```graphql
query($q: String!, $cursor: String) {
  search(query: $q, type: REPOSITORY, first: 100, after: $cursor) {
    repositoryCount
    nodes {
      ... on Repository {
        nameWithOwner
        description
        stargazerCount
        forkCount
        updatedAt
        pushedAt
        primaryLanguage { name }
        licenseInfo { spdxId }
        repositoryTopics(first: 10) { nodes { topic { name } } }
        url
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
```

- 限制：5000 points/hour，单查询 node 数上限 500000。
- 用 `endCursor` + `hasNextPage` 翻页，无 1000 条硬上限的"页面"概念，但单 connection 仍受结果集规模约束，实践中需拆分 query。

### 3.3 速率限制与分页策略

| 维度 | REST | GraphQL |
|------|------|---------|
| 认证速率 | 30/min（search），10/min（code） | 5000 points/hour |
| 单查询上限 | 1000 条 | 受 node/cost 限制 |
| 分页 | page+per_page + Link header | cursor (after/hasNextPage) |
| 推荐场景 | 简单分桶穷举 | 需嵌套关联数据时 |

**避免限流的工程实践**：
- 用 token 池轮换（多个 PAT）。
- 请求间加 `sleep`，控制 ≤25 req/min 留余量。
- 优先 GraphQL 减少 RTT。
- 缓存查询结果（deep-research-ultra 已有 `cache.py`，可复用）。

---

## 4. 替代搜索引擎与工具

### 4.1 OSS Insight（ossinsight.io）

PingCAP 开源，分析 GitHub 50 亿+ 事件数据（VLDB 2024 论文）。

能力：
- **Data Explorer**：自然语言问 GitHub 数据（GPT 驱动），如"2025 年最活跃的 Python agent 项目"。
- **/analyze/{owner}/{repo}**：单仓库深度画像（star 增长、贡献者地理分布、PR/issue 响应时长）。
- **/collections**：主题合集（如"LLM Infra"），适合发现主题内被低估项目。
- **Trending**：按语言/时间窗的活跃趋势，比 GitHub Trending 维度更丰富。

接入：有公开 REST API（`https://api.ossinsight.io/v1`），返回 JSON，适合做"活跃度评分"补充源。

### 4.2 SearchCode（searchcode.com）

跨 GitHub/GitLab/Bitbucket/CodePlex 等的代码搜索引擎，支持按语言、仓库过滤。适合反向查"哪个仓库用了某个独特 API"。

### 4.3 Libraries.io

连接 npm、PyPI、Go modules、Maven、Cargo、Packagist 等 30+ 包管理器，索引 180 万+ 项目。

能力：
- 包的 **dependents** 列表（谁依赖了它）与 **dependents count**。
- **sourcerank** 评分（综合 star、fork、贡献者、release、文档）。
- API：`/api/:platform/:name/dependents`、`/api/search?q=...`。

> 用于"种子包 → 反向找所有使用者"的依赖图挖掘，比 GitHub dependents 页面更结构化。

### 4.4 其他工具

| 工具 | 用途 | URL |
|------|------|-----|
| GitHub Trending | 趋势项目 | github.com/trending |
| GitStar Ranking | star 排名（按语言/地区/时间） | gitstar-ranking.com |
| star-history | star 增长曲线，判断是否"爆发式增长" | star-history.com |
| Snyk Advisor | 包质量评分（维护/社区/安全） | snyk.io/advisor |
| Socket.dev | 包安全分析 | socket.dev |
| repobeats | 项目活跃度仪表盘 | repobeats.axiom.co |
| Gitee/GitLab 搜索 | 国内/私有仓库补充 | gitee.com、gitlab.com/explore |
| HelloGitHub | 中文社区精选月刊 | hellogithub.com |

---

## 5. Awesome 列表挖掘

### 5.1 定位相关 awesome 列表

- 顶层目录：`github.com/sindresorhus/awesome`
- 搜索：`awesome-{keyword} in:name stars:>100`（如 `awesome-llm`、`awesome-agents`）
- Awesome 自身也是仓库，可解析其 README 中的链接。

### 5.2 提取项目清单

awesome 列表是 Markdown，结构规律（`- [名称](URL) - 描述`）。提取方法：

1. 用 `gh api` 拉 README 原文。
2. 正则提取所有 `https://github.com/{owner}/{repo}` 链接。
3. 批量查 star/活跃度（GraphQL 批量查询）。

### 5.3 自动化挖掘

```
种子关键词 → 搜 awesome-{kw} → 拉 README → 提取所有 GitHub 链接
→ 批量 GraphQL 查元数据 → 去重 → 合并进候选池
```

优势：awesome 列表经过人工策展，低星但被收录的项目天然是"高质量低星"，正好补 GitHub 搜索的盲区。

### 5.4 质量评估

- star 数 + 最近提交（awesome 列表本身也要活着）。
- 收录项目数与死链率（死链多 = 失效列表）。

---

## 6. 依赖图分析

### 6.1 GitHub Dependency Graph / Dependents

- 路径：仓库 → Insights → Dependency graph → Dependents（`/{owner}/{repo}/network/dependents`）。
- 页面显示 `used by N packages`，可按包管理器过滤。
- **没有公开 REST API 列出全部 dependents**，只能爬网页分页（有反爬，需节流）。

### 6.2 Libraries.io dependents API

```
GET https://libraries.io/api/{platform}/{name}/dependents?api_key=KEY
```

返回结构化 dependents 列表，比爬 GitHub 页面稳定。适合"种子库 → 反向找生态"。

### 6.3 包管理器原生

- npm：`npm view <pkg> dependents`、`npms.io` API
- PyPI：无原生 dependents，用 Libraries.io
- Go：`pkg.go.dev/{module}?tab=importedby`
- Maven：`mvnrepository.com`

### 6.4 双向挖掘策略

```
种子项目 → 正向：分析它的 package.json/requirements.txt 依赖 → 找到它依赖的相关库
         → 反向：找谁依赖了它 → 这些依赖者往往同领域，值得纳入候选
```

正向找"上游库"（更基础/更通用），反向找"同领域应用"（更多场景变体）。

---

## 7. 低星高质量项目识别

### 7.1 评估指标

| 维度 | 指标 | 信号 |
|------|------|------|
| 活跃度 | pushed_at 近期、commit 频率、release 频率 | `pushed:>2025-06-01` 且月 commit≥3 |
| 维护响应 | issue/PR 中位响应时长、open/close 比 | close 率高、响应 <7d |
| 贡献者 | contributors 数量、是否有外部贡献者 | ≥2 贡献者 = 非单人孤岛 |
| 代码质量 | 有无 CI、测试覆盖、lint、有 Release | 有 `.github/workflows`、有 tests/ |
| 文档 | README 完整度、是否有 docs/、示例 | README >500 行、有 quickstart |
| 引用度 | 被 awesome 收录、被高星项目依赖、被论文引用 | libraries.io dependents≥1 |
| 规范 | license、CODE_OF_CONDUCT、issue template | 有 license = 可商用 |

### 7.2 评分算法建议

综合分数（0~100），加权求和：

```
score =
  0.25 * activity_score      # 基于 pushed/commit/release 频率
  0.20 * responsiveness_score # issue/PR 响应
  0.15 * contributor_score    # 贡献者数
  0.15 * code_quality_score  # CI/测试/文档
  0.10 * reference_score     # 被引用/被依赖
  0.10 * documentation_score
  0.05 * star_growth_score   # star-history 斜率（而非绝对值）
```

关键：**star 绝对值不进主分**，只看 `star_growth`（斜率）。低星但近 3 个月 star 上升快 = 潜力股。

数据来源：GraphQL 拉仓库元数据 + OSS Insight 拉活跃度 + Libraries.io 拉 dependents。

---

## 8. 多源交叉搜索策略

### 8.1 代码托管平台

GitHub + Gitee + GitLab + Bitbucket 并行：
- Gitee 对国内项目友好（国内开发者首选）。
- GitLab 有大量私有/企业项目与镜像。
- 用各平台搜索 API，结果按 URL 去重。

### 8.2 包管理器

npm + PyPI + Go modules + Maven + Cargo + Packagist：
- 包是项目的"正式发布态"，搜包能找到稳定项目。
- 用 Libraries.io 统一接口聚合。

### 8.3 内容平台（社区口碑）

- Reddit（r/programming、r/Python 等）
- Hacker News
- V2EX、掘金、知乎、CSDN
- 小红书（中文用户口碑）
- B 站技术 UP 主推荐

> deep-research-ultra 已有 `AgentReachEngine` 覆盖 13 平台，可复用做"口碑验证"：候选项目在社区是否被提及、评价如何。

### 8.4 学术来源

- arXiv 论文的代码链接（`paperswithcode.com`）
- 论文引用的实现仓库
- deep-research-ultra 已有 `SciverseEngine` 覆盖。

### 8.5 去重与合并

跨源结果按规范化 URL（去掉末尾 `/`、统一大小写 owner）去重，合并元数据，保留多源证据（被几个源提及 = 可信度）。

---

## 9. 自动化搜索流水线设计

### 9.1 流水线架构

```
┌─────────────────────────────────────────────────────────────┐
│  Stage 0: 种子输入                                           │
│  - 关键词、种子仓库、种子包、领域 topic                       │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 1: 查询扩展                                          │
│  - 同义词/缩写扩展 (agent↔assistant↔copilot)                 │
│  - topic 候选 (gh search topics)                            │
│  - 语言候选 (python/ts/go/rust)                            │
│  - stars 分桶 [<10, 10..50, 50..200, 200..1k, >1k]          │
│  - 时间窗 [created>2024, created 2023, 更早]               │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 2: 多维度组合查询（并行）                             │
│  A. gh search repos (多桶 × 多语言 × 多 topic × 升降序)      │
│  B. gh api REST 分页穷举 (sort=stars&order=asc 挖低星)       │
│  C. GraphQL cursor 分页 (拉关联元数据)                       │
│  D. gh search code (反查独特 API 引用)                      │
│  E. OSS Insight (活跃度/合集)                                │
│  F. Libraries.io (包搜索 + dependents)                      │
│  G. Awesome 列表解析                                          │
│  H. 依赖图双向挖掘 (种子→依赖/被依赖)                        │
│  I. 社区口碑 (AgentReachEngine)                              │
│  J. 学术来源 (SciverseEngine)                                │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 3: 去重与合并                                         │
│  - 规范化 URL 去重                                          │
│  - 多源证据计数 (被 N 个源提及)                              │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 4: 评分（§7 算法）                                    │
│  - 活跃度/响应/贡献者/代码质量/引用/文档/star增长            │
│  - 低星不扣分，star 增长斜率加分                             │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 5: 排序与报告                                         │
│  - 按综合分排序                                              │
│  - 标注"低星高潜"标记                                        │
│  - 输出候选池                                                │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 搜索策略伪代码

```python
def github_deep_search(seed_keywords, seed_repos=None, seed_packages=None):
    candidates = {}  # key=normalized_repo_url

    # Stage 1: 查询扩展
    queries = expand_queries(seed_keywords)
    # 返回: [(keyword, language, topic, star_bucket, time_window, sort)]

    # Stage 2: 多维度并行搜索
    for q in queries:
        # 2A/2B: gh search repos 多桶，含升序挖低星
        for sort, order in [("stars","asc"), ("updated","desc"), ("stars","desc")]:
            results = gh_search_repos_paginate(q, sort=sort, order=order, max_pages=10)
            merge(candidates, results, source="gh_repos")

        # 2D: code search 反查引用
        code_hits = gh_search_code(q.keyword, language=q.language)
        merge(candidates, code_hits, source="gh_code")

    # 2E: OSS Insight 活跃度补充
    enrich_with_ossinsight(candidates)

    # 2F: Libraries.io 包 + dependents
    for pkg in search_libraries_io(seed_keywords):
        merge(candidates, pkg, source="libraries_io")
        for dep in get_dependents(pkg):
            merge(candidates, dep, source="libraries_dependents")

    # 2G: Awesome 列表
    for awesome_repo in find_awesome_lists(seed_keywords):
        links = extract_github_links_from_readme(awesome_repo)
        merge(candidates, links, source="awesome")

    # 2H: 依赖图双向
    for seed in seed_repos or []:
        deps = get_repo_dependencies(seed)        # 正向
        dependents = get_dependents(seed)          # 反向
        merge(candidates, deps + dependents, source="dep_graph")

    # Stage 3: 去重（已随 merge 完成）+ 证据计数

    # Stage 4: 评分
    for repo in candidates.values():
        repo.score = score_repo(repo)   # §7 算法，低星不扣分

    # Stage 5: 排序
    return sorted(candidates.values(), key=lambda r: r.score, reverse=True)
```

### 9.3 避免信息过载

- **桶上限**：每个查询桶取 top 100，避免单桶爆炸。
- **早停**：某桶已命中已知高质量项目则降低该桶权重。
- **分层呈现**：高星核心 / 中星主流 / 低星高潜 三层分组输出，而非一个长列表。
- **缓存**：复用 `cache.py`，相同查询 24h 内不重跑。

---

## 对 deep-research-ultra skill 的改进建议

以下建议具体到代码模块，基于现有结构（`scripts/engines/skill_engines.py` 中的 `OssFinderEngine`）。

### 建议 1：新增 `GitHubDeepSearchEngine`（核心改进）

**文件**：`scripts/engines/github_deep_search.py`（新增）

**职责**：实现 §9 流水线的 GitHub 部分，取代 `OssFinderEngine` 的简单模板调用。

```python
class GitHubDeepSearchEngine(SearchEngine):
    """
    GitHub 深度搜索引擎 — 不漏项目的核心引擎
    通过 gh CLI + REST API + GraphQL 多维度组合穷举
    """
    def search(self, query, max_results=200, **kwargs):
        # 1. 查询扩展（同义词/topic/语言/星桶/时间窗）
        # 2. 多桶 × 多排序 并行 gh search repos + gh api 分页
        # 3. code search 反查引用
        # 4. 去重合并
        # 5. 返回 SearchResult 列表（含 source 多源标记）
```

**关键实现点**：
- 用 `RunCommand` 调 `gh search repos --json ... --sort=stars --order=asc` 主动挖低星。
- 用 `gh api '/search/repositories?...&page=N&per_page=100'` 翻满 10 页。
- 用 GraphQL `search` connection 嵌套拉元数据减少请求。
- 速率控制：`sleep` + token 轮换，遵守 30 req/min。

### 建议 2：增强 `OssFinderEngine` 的调用模板

**文件**：`scripts/engines/skill_engines.py`（修改 `OssFinderEngine.get_invocation_template`）

当前模板只传 `stars_min`（只升不降）。改为传**完整分桶策略**：

```python
def get_invocation_template(self, **kwargs):
    query = kwargs.get("query", "")
    # 生成多桶查询指令，明确要求"低星桶用 stars:<N + sort=stars&order=asc"
    star_buckets = [("<10", "asc"), ("10..50", "asc"),
                    ("50..200", "desc"), ("200..1k", "desc"), (">1k", "desc")]
    instruction = (
        f"对 '{query}' 执行分桶穷举搜索：\n"
        f"对每个 stars 桶: gh search repos '{query}' --stars={bucket} "
        f"--sort=stars --order={order} --limit=100 --json fullName,stargazersCount,description,pushedAt\n"
        f"务必包含 stars:<10 的低星桶并按星升序，避免漏掉低星项目\n"
    )
```

### 建议 3：新增查询扩展与评分模块

**文件**：`scripts/query_expander.py`（新增）

- `expand_queries(keyword)` → 生成 `(keyword, language, topic, star_bucket, time_window, sort)` 组合。
- 内置同义词表（可后续接入 LLM 扩展）。

**文件**：`scripts/engines/base.py`（扩展 `SearchResult`）

给 `SearchResult` 增加：`sources: List[str]`（多源证据）、`activity_score`、`reference_score`、`star_growth`、`low_star_high_potential: bool`。

### 建议 4：新增依赖图挖掘引擎

**文件**：`scripts/engines/dep_graph_engine.py`（新增）

- 输入种子仓库，正向拉依赖（解析 `package.json`/`requirements.txt`/`go.mod`）。
- 反向用 Libraries.io API 拉 dependents。
- 合并进候选池。

### 建议 5：新增 Awesome 列表挖掘引擎

**文件**：`scripts/engines/awesome_miner.py`（新增）

- `find_awesome_lists(keyword)` → `gh search repos "awesome-{keyword}"`
- `extract_github_links(readme)` → 正则提取 + 批量 GraphQL 查元数据。

### 建议 6：路由层集成

**文件**：`scripts/router.py`（修改）

在 OSS 调研场景下，把 `OssFinderEngine`（低优先级 fallback）替换为 `GitHubDeepSearchEngine`（主力）+ `DepGraphEngine` + `AwesomeMiner` + `LibrariesIoEngine` 并行，结果去重合并后交给 `score.py` 评分。

### 建议 7：评分器增加低星高潜标记

**文件**：`scripts/score.py`（修改）

- 实现 §7.2 评分算法。
- 增加 `low_star_high_potential` 旗标：`stars < 100 且 activity_score > 阈值 且 star_growth 斜率 > 0`。
- 排序时该旗标项目单独成组，保证不被高星淹没。

---

## 关键限制速查（避免踩坑）

| 限制 | 值 | 应对 |
|------|-----|------|
| REST 单查询结果上限 | 1000 条 | 拆分查询（分桶/分语言/分时间） |
| REST 查询长度 | ≤256 字符 | 精简关键词，限定符不算 |
| REST 布尔运算符 | ≤5 个 AND/OR/NOT | 拆成多个查询 |
| REST 搜索速率 | 30/min（code 10/min） | token 池 + sleep |
| GraphQL | 5000 points/hour | 优先 GraphQL 减少 RTT |
| dependents 列表 | 无公开 API | 爬网页 or Libraries.io |
| 搜索范围裁剪 | 后端只扫 ~4000 仓库子集 | 多维度拆分绕过 |
| `incomplete_results` | 超时返回部分结果 | 检查标记并补查 |

---

## 参考资料

- GitHub 官方：搜索仓库 https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories
- GitHub 官方：搜索语法 https://docs.github.com/en/search-github/getting-started-with-searching-on-github/understanding-the-search-syntax
- GitHub 官方：Code Search 语法 https://docs.github.com/en/search-github/github-code-search/understanding-github-code-search-syntax
- GitHub 官方：REST Search API https://docs.github.com/en/rest/search/search
- GitHub 官方：GraphQL API https://docs.github.com/en/graphql
- GitHub 官方：Starring API（2026 新访问限制）https://docs.github.com/en/rest/activity/starring
- gh CLI：search repos https://cli.github.com/manual/gh_search_repos
- gh CLI：search code https://cli.github.com/manual/gh_search_code
- OSS Insight https://ossinsight.io（VLDB 2024 论文）
- Libraries.io https://libraries.io
- SearchCode https://searchcode.com
- star-history https://star-history.com
- GitStar Ranking https://gitstar-ranking.com
- 现有 skill 代码：`projects/deep-research-ultra/scripts/engines/skill_engines.py`（`OssFinderEngine` 在第 224 行）
