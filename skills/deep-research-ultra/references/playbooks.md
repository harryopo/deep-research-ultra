# Playbooks — deep-research-ultra 操作手册

> 本文件收纳**查手册时才看**的内容：各引擎/工具的完整用法、命令示例、
> 代码结构清单、测试命令。**每轮调研不需要通读**——Lead 执行时照抄
> `SKILL.md` 各 Phase 里的命令即可；只有在配环境、调某个引擎、
> 或要理解某个模块时，才来这里查。
>
> 迁移自 SKILL.md（v6.64）。SKILL.md 只保留执行规则与硬约束，
> 两者内容同源，改动请同时更新。

---

## 五、反爬虫与浏览器自动化

### 5.1 curl_cffi TLS 指纹伪装

所有 HTTP 请求（`_http_get` / `_http_post`）优先使用 curl_cffi 进行 TLS/JA3 指纹伪装：

```python
from curl_cffi import requests as cffi_requests
r = cffi_requests.get(url, impersonate="chrome124")  # 伪装 Chrome 124
```

- curl_cffi 是**必需依赖**（`--env-check` 四个 profile 都把它当硬缺失来判）。没装时 urllib 仍能发请求，
  但实测同一批 arXiv URL 一律 HTTP 406、装上后同样这些 URL 全部拿到内容——留着"降级"只会让 Lead
  把传输层被拦误判成"这个源不行"。补装：`pip install curl_cffi`
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

---

## 六、学术全文与引用图谱

### 6.1 arXiv 全文下载

```python
from engines.academic_fulltext import ArxivFulltextEngine

e = ArxivFulltextEngine()
# 搜索论文（返回元数据 + PDF/HTML/LaTeX URL）
results = e.search("transformer attention", max_results=10)
# 下载 PDF
e.download_pdf("2404.19756", "paper.pdf")          # 落盘前四道校验：非 PDF / 太小 / 截断 / 不是这一篇 → 返回 None 且不写盘
# 获取 LaTeX 源码（tar.gz）
latex = e.fetch_latex("2404.19756")
```

- 数据量：2.4M+ 预印本
- API Key：无需
- 速率限制：3 秒/请求（官方建议）
- 国内可用：✅

**这个引擎的两条实情**（别照名字理解）：

- `search()` 只回**元数据**（标题/摘要/PDF·HTML 链接），全文必须由 `download_pdf` / `fetch_latex`
  按论文编号另取。`research.py --sources arxiv-fulltext` 走的是 `search()`，它不会下全文。
- **HTTP 406 取决于查询形态与频率，不是"这个主题没论文"**（2026-09-24 逐发隔离实测）：
  同一台机器、同一个裸 urllib 请求，`search_query=cat:cs.CL` 单发回 200（带不带 `sortBy` 都一样），
  而 `all:electron` / `ti:electron` / `abs:...` / 多词 AND **单发也恒回 406**；
  连发 4 发以上（间隔 ≤6s）时连分类式都被打成 406。所以 406 有两因：查询形态、请求频率。
  处置顺序：① 隔 ≥90 秒单发重跑；② arXiv 查询改分类式（`cat:cs.CL`），别用裸关键词整句；
  ③ 两条都试过再换 OpenAlex / Semantic Scholar / paper-search。**探针 ✅ 只代表分类式那一刻能通，
  不代表本主题的关键词查询到得了**。

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

> **这不算选型调研时**（v6.15）：报告里的仓库链接只是被**引作证据**（讲某个实现怎么做的、
> 抄了哪段校验逻辑），不是在几个候选里挑一个用——在正文写一行 `选型调研: 否` 即豁免六维。
> 豁免**不豁免溯源**：每个仓库链接仍要能在账本 `sources` 里找到对应来源，找不到就拦。
> 反向同理：真要选型调研就写 `选型调研: 是`，六维照旧逐候选补齐；什么都不写按选型处理。

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
# 必装：curl_cffi（全部引擎共用的 TLS 指纹伪装，不装则 arXiv 一律 406）
pip install curl_cffi
# 可选：配置 GITHUB_TOKEN 增强 GitHub 搜索
export GITHUB_TOKEN=your_token
```

---

---

## 九、推荐度评分系统

### 9.1 设计目标：推荐度与排序

调研报告需输出推荐度和排序，小众结果可借鉴。实现多维度评分 + 分组排序 + 雷达图可视化。

### 9.2 GitHub 项目推荐度（8 维评分）

| 维度 | 权重（default） | 说明 |
|------|----------------|------|
| popularity（人气） | 0.15 | log10(stars+1) 对数缩放 |
| activity（活跃度） | 0.15 | 最近 commit/push 时间 + release 频率 |
| maintenance（维护） | 0.15 | 是否归档 + issue 响应 + **最后推送时间 `pushed_at`**（v6.43 起不再用 `updated_at`：那是元数据被动过的时间，改描述、加 star 都会推后它，实测八个月没提交的仓库按它评成 90/100） |
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

---

---

## 一·补、检索词写法（Phase 1 派单前必读）

从 SKILL.md 搬来（v6.81，同批还并入了泛词堆的量化复盘）。

### 1.6 检索词要按语料语言给（`--source-query`）

相关性打分算的是**字面词覆盖**。把一句中文主题原样发给 arXiv/OpenAlex/Semantic Scholar，
命中的英文论文必然被判成噪声——实测同一批人工确认切题的论文，中文提问下 relevance
23.6/34.5/28.6，换英文提问 29.2/58.3/47.5；按 relevance<50 的规则，中文提问时 3/3 全成噪声，
这就是"验证率 0%"的来路。内置词典（`router.py` 的 `zh_to_en`，34 个通用词）翻不动
证据/溯源/可追溯/引用/幻觉 这类专业词，**翻译这件事由 Lead 做**。

派单前把每个引擎该收的词写清楚，未点名的引擎仍收主题查询：

```bash
python "${SKILL_DIR}/scripts/research.py" "AI 编码 Agent 的证据溯源做法" \
  --sources arxiv-fulltext,openalex,baidu-xueshu \
  --source-query "arxiv-fulltext=LLM agent hallucination source attribution" \
  --source-query "openalex=claim source attribution agentic coding" \
  --source-query "baidu-xueshu=AI 编码智能体 证据溯源 引用对齐"
```

英文学术库给英文词，国内平台（baidu-xueshu / sogou-weixin / baidu-serp）给中文词。
每个引擎的相关性按**它自己收到的词**判，账本也记这条词（`evidence.jsonl` 的 `query`），
所以按账本重跑能复现出同一批命中。`--source-query` 里写错引擎名会直接告警——
不吭声的话那个引擎照旧收中文主题词，看起来搜过了，实际换词没生效。

⚠️ 换词只保证"命中随词变"，不保证你换到的是切题的词。拿"AI 编码 Agent 的证据溯源"这个主题
在 OpenAlex 上做了 6 种给法 × 2 种端点的对照实验，量出来的东西直接决定怎么写词：

| 给法 | 全文端点带回什么 | 字段限定端点（只搜标题+摘要） |
|------|------------------|-------------------------------|
| 中文整句主题 | 地球科学AI、企业白皮书…切题 0/5 | **0 命中** |
| 中文短术语对 | 智能电网、花岗岩、刀具寿命…切题 0/5 | 药品质控、放疗质控…切题 0/5 |
| 十个英文词堆一句 | 医学AI隐私、医疗LLM投毒…切题 1/5 | **0 命中** |
| 英文术语对 | 幻觉综述若干（非编码领域）切题 1/5 | 幻觉缓解、agentic RAG 忠实度 |
| **英文机制短句** | **《ChatGPT 生成的参考文献造假》**、溯源记忆、可验证检索 | 同上三条 |
| 英文领域锚 | 泛 AI Agent 分类学 切题 0/5 | 《CITAE：逐段可验证的 RAG 平台》 |

三条可执行结论：

1. **给一句"机制描述"，不要堆词**。真正切题的命中全部来自
   `verifying generated code citations against sources` 这种主谓宾齐备的短英文句；
   十个词堆成一句反而带回落回医学与泛综述。
2. **长词串做字段限定必然 0 命中**（`title_and_abstract.search` 是 AND 语义，
   与 D5 那条 GitHub 仓库搜索长查询恒 0 命中同一机制）。词多就退回全文端点。
3. **中文词在英文库无解**：字段限定 0 命中，全文检索带回地质与电网论文——
   这不是调参问题，只能换语言（所以有 `--source-query`）。

派单前用 `--probe --sources <引擎> --theme-query "<候选词>"` 预演，看首条标题像不像本题的东西。
相关度分数只当过滤器：实验里分数升高的那次（短短语 42.1）命中反而更偏，
**不许拿 relevance 升高当证据质量达标的凭据**。

🚫 **三条"让工具自动取词"的路子已实测否决，别再重做**（同一主题，逐条人工判切题）：

| 路子 | 做法 | 实测结果 |
|------|------|----------|
| 词典翻译 | `router.py` 的 `zh_to_en` 生成变体 | 34 个通用词，专业词零覆盖；命中也是中英混排串 |
| 引文扩引 | 锚定一篇切题论文走 OpenAlex `related_to` | 10 条全是"多学科研究团队/门诊"，precision 0/10 |
| 取主题词 | 读锚定论文自己的 `primary_topic` / `concepts` 当查询词 | 标签是"AI in Healthcare and Education"这类宽簇名，precision 0/10 |

三条输给的是同一件事：**Lead 手写的那句机制描述**（`verifying generated code citations
against sources`）至少把种子论文与 `Citationchaser` 这类近邻工具带回来了，而机械扩出来的
都是文献计量邻居、不是主题邻居。所以检索词的判断留给 Lead，工具只负责把词送到对的引擎、
并按这条词打分与记账。

> 缺哪个变量、去哪申请、解锁什么，`--probe` 会按引擎逐条打印（同一个动作自动合并成一行），
> 不需要背配置表；配好后重跑直到闸门放行为止。

##### 泛词堆：为什么"把词写全"反而更容易捞到噪声（v6.81）

上面第 1 条结论说"给一句机制描述，不要堆词"。这条有个反直觉的推论，值得单独说：
**堆得越全，越容易被泛词带偏**——因为相关性按字面词覆盖打分，查询里每多一个
`benchmark` / `dataset` / `evaluation`，就多一分把**任何领域的 benchmark 论文**
捞进来的机会，而那些论文确实"覆盖了"你的词。

实跑（2026-10-12，臂 1 指标维度）把这条量了出来。查询写
`rag evaluation benchmark dataset faithfulness`，29 条落盘里混进：

- `L-FAME: Longitudinal Focused Attention Meditation EEG Dataset`（EEG 冥想数据集）
- `Bitstream-Corrupted Video Recovery: A Novel Benchmark Dataset and Method`（视频恢复）
- `VRSBench: …Remote Sensing Image`（遥感影像）

**这两条噪声的相关性分别排第 4/29 与第 10/29，高于真正切题的 MultiHop-RAG（第 5）
与 CPRet（第 6）。** 也就是说：不是阈值定低了，是**排序本身就是错的**。

三条可执行结论：

1. **查询里至少留一个"领域特征词"**——`retrieval-augmented`、`RAG` 这种别人论文里
   不容易撞上的词。别让查询全部由通用名词构成。
2. **别指望相关性分数替你做判断**。三条修法实测下来全部无效：
   - 「要求关键词与查询有实际交集」→ 那两条噪声**本来就有关键词交集**，一条都拦不住
   - 「把阈值调高」→ 64 分的噪声排在第 4，降阈值也留着它
   - 「必须命中领域特征词」→ 只能剔掉 3 条里的 2 条，`L-FAME` 的摘要里含
     retrieval/generation，规则漏掉最严重的那个

   所以**改评分公式要有样本支撑**。手上只有 29 条里 3 条标注过的噪声时，调权重就是猜——
   这个项目有现成的前车之鉴：v6.70「宣称 34 源 vs 实出 14，是宣传口径问题……是我的修法
   不如现状」。
3. **`craap_score`(total) 不是 relevance 的代理**，别拿它排"哪条最切题"：实算同一批
   29 条，两张名次只有 1/29 逐位重合（`Evaluation Methodology` 的 total 83.2 看着体面，
   relevance 只有 30）。账本现已同时存 `relevance` 与 `relevance_capped`，按前者读；
   `relevance_capped=True` 表示判定器没听懂这个语料，**不是"评出来不相关"**。
   `research.py` 每次检索后也会打一行「📐 相关性分布」，明说"留下的里还有多少低于阈值"。


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

# 3. 证据账本（写命令签名照抄，不必再跑 --help）
python "${SKILL_DIR}/scripts/ledger.py" init --session <ledger目录>
python "${SKILL_DIR}/scripts/ledger.py" add-claim --session <dir> --text "<claim>" \
    [--topic <t>] [--status pending|verified|conflict] [--perspective <p>] \
    [--confidence <0-1>] [--id <id>] [--note <n>]
python "${SKILL_DIR}/scripts/ledger.py" add-source --session <dir> --claim-id <id> --url <绝对URL> \
    [--title <t>] [--tier <1-4>] [--craap <分数>]        # tier 不传则按域名自动判定
    # 点不回原文的一律退 2 拒收（站内相对链接 /link?url=…、javascript:、"见前面报告"），
    # 与 merge 同一道闸门：这种字符串一旦入账就占一个引用编号，报告必须列进来源登记表
python "${SKILL_DIR}/scripts/ledger.py" set-status --session <dir> --claim-id <id>[,<id>...] \
    [--status <s>] [--note <n>] [--text "<就地更正后的原文>"] [--scope "<成立范围>"]
    # 只给 --text/--scope 时状态不动；改错一句话不该顺手把 pending 判成 verified
python "${SKILL_DIR}/scripts/ledger.py" verify-primary --session <dir> --claim-id <id>[,<id>...] \
    --check-url <同一制品的另一通道URL> [--check-title <t>] [--method <手段>]
python "${SKILL_DIR}/scripts/ledger.py" link-identity --session <dir> --claim-id <id>[,<id>...] \
    --anchor <账本已有来源URL> --target <反查URL>
    # 跨标识符判同（预印本↔期刊 DOI 这类）：查书目记录的 externalIds 并写 type=identity 凭据进账本，
    # 绑成功后再对目标 URL 跑 verify-primary
python "${SKILL_DIR}/scripts/ledger.py" content-identity --session <dir> --claim-id <id>[,<id>...] \
    --anchor <账本已有来源URL> --target <另一主机的同一内容URL>
    # 跨主机且无标识符的一对（文档站页面↔仓库 .md 源文件）：凭这条 claim 的逐字片段
    # 在两侧正文都命中判同；指错文件/空壳页/纯转述一律拒
python "${SKILL_DIR}/scripts/ledger.py" merge --session <dir> --dir <分片所在目录> [--claim-cap N]
python "${SKILL_DIR}/scripts/ledger.py" status --session <dir> [--topic <t>]   # 无 --topic 出 {"topics":…,"totals":…}
python "${SKILL_DIR}/scripts/ledger.py" status --session <dir> --needs-cross    # 逐条列出"只挂了一个注册域"的孤证
    # v6.50：status 只报主题总数，不指出**具体哪几条 claim 只差一个跨域来源**。
    # 归并后先跑这条，它直接给出该派哪几轮交叉补强——别再人工翻 claim 逐个查域。
    # 口径同档 A：按不同注册域计，同一作品的多个通道（arXiv /abs 与 /pdf、
    # 仓库页与 raw）折叠成一个域。verified 与 conflict 不出现在清单里。
python "${SKILL_DIR}/scripts/ledger.py" export --session <dir> --format json|md [--out <path>]

# 4. 专家团评审清单生成（供主 Agent 消化执行）
python "${SKILL_DIR}/scripts/panel.py" perspectives                                   # 列出 5 内置角色
python "${SKILL_DIR}/scripts/panel.py" review-outline --input outline.md --roles domain_expert,skeptic,practitioner
python "${SKILL_DIR}/scripts/panel.py" supplement-questions --input <file|text> [--roles r1,r2]
python "${SKILL_DIR}/scripts/panel.py" review-draft --input <file|text> --role <role>
    # supplement-questions 出"该补哪些问题"，review-draft 按单一角色审草稿（默认 domain_expert）

# 5. 来源 Tier 分级（独立工具）
python "${SKILL_DIR}/scripts/tier.py" "https://www.gov.cn/x"                          # → Tier 1

# 6. 报告骨架（v6.14）：引用编号 + 来源登记表由账本直出，Lead 只补带【待写】标记的段落
#    （v6.15：未验证 claim 渲染成 ⚠️ 仅作线索，不再逐条留待写标记）
python "${SKILL_DIR}/scripts/skeleton.py" .research/session/ledger -o report.md --title "报告标题"

# 6b. 引文逐字对账（v6.44）：账本每段『…』与报告每段「…」都必须在存档的原始材料里逐字命中
#     只折叠空白、不换字符形态（0–3 写成 0-3 就算 MISS）；材料没存档 → 退 2，不报通过
#     自造口径写〔…〕：它不是引文承诺，两套引号识别都不收（v6.46）
python "${SKILL_DIR}/scripts/verify_quotes.py" --ledger .research/session/ledger --raw .research/session/raw
python "${SKILL_DIR}/scripts/verify_quotes.py" --report report.md --raw .research/session/raw

# 6c. L4 canary 哨兵（v6.53）：会话假凭据，检测注入是否外传——发布门前必过
#     令牌只在 canary.txt 里是合法的；出现在其他任何文件＝注入生效实证，停止交付
python "${SKILL_DIR}/scripts/canary.py" init --session .research/session
python "${SKILL_DIR}/scripts/canary.py" token --session .research/session
python "${SKILL_DIR}/scripts/canary.py" check --session .research/session [--report report.md] [--extra 文件]...
#     两个来源一起查：--ledger 与 --report 至少给一个，都不给 → 退 2（没东西可查不等于通过）
python "${SKILL_DIR}/scripts/verify_quotes.py" --ledger .research/session/ledger --report report.md --raw .research/session/raw

# 7. 发布前校验门（exit 0=通过）+ 防伪戳
python "${SKILL_DIR}/scripts/validate_report.py" --report report.md --ledger .research/session/ledger --raw .research/session/raw --stamp
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

> **github-deep-search 会改写查询词**（v6.15 起把改写说清楚）：GitHub 仓库搜索把多词按 AND 同时匹配
> name/description/readme，> 3 词的自然语言查询恒 0 命中，所以引擎首轮就把查询压到 ≤3 个词，
> 并在 stderr 列出**实际发出去的查询**和**被丢掉的词**。每条结果带 `query` 字段＝命中它的那条查询：
> 判相关性时看这个字段，别看原始问题——命中是三个词捞来的，与原始问题的差距要由 Lead 认。
> 嫌它压得太狠，就自己传 ≤3 词的短查询（引擎对短查询不动手）。

**国内调研**（如 "国内 RAG 落地实践"）：
```
查询类型: general（国内适配）
引擎链: baidu-serp, sogou-weixin, sogou-zhihu, baidu-xueshu
置信度: 0.85
```

---

---

## 十五、代码结构

```
scripts/
├── research.py              # 主入口（--env-check/--probe/--theme-query/--auto-route/--effort/--breadth/--dimensions/--ledger/--min-relevance/--source-query）
├── console.py               # CLI 强制 UTF-8 输出（Windows GBK 控制台曾直接 UnicodeEncodeError）
├── probe.py                 # 引擎功能自检（探针查询表 + ok/empty/failed 判定）+ 主题级预演（按实际查询词分"活着"与"到得到数据"）
├── env_check.py             # 环境分级验证（minimal/opensource/academic/full）
├── search.py                # 引擎兼容入口（保留 --sources baidu,bing 等旧参数）
├── setup-mcp.sh             # MCP 一键配置脚本（默认写当前目录 .mcp.json，--via-claude 才走宿主 CLI）
├── mcp_config_writer.py     # .mcp.json 读写器（--server/--env/--remove/--list，宿主无关）
├── check_serp_patterns.py   # HTML 抓取类源改版预警：真取一次页面，分开报
│                            # 「通道失败 / 页面有自然结果但解析不出条目 / 风控回外壳页」
│                            # 出现"解析器过期"判定时退出码 2（--peek NAME 可看页面首段）
├── router.py                # 智能路由（三级级联 Rule→Semantic→LLM）
├── recommend.py             # 推荐度评分（GitHub/PaperRecommender + detect_intent）
├── tier.py                  # 来源 Tier 分级（域名校验，score/report/validate 共用）
├── ledger.py                # 证据账本（claim→source 可溯源，多子Agent并发写）
├── similarity.py            # 转载指纹去重 + claim 语义聚类 + 数值矛盾检测
├── repo_health.py           # 仓库健康扫描（官方 API 事实 + 停更 + 许可证传染 + OSV CVE；verdict 五态，限流判 unknown）
├── panel.py                 # 专家团评审清单生成（多视角 + 红蓝对抗契约）
├── validate_report.py       # 发布前校验门（引用一致性/反查/覆盖率/章节/Tier4占比/六维要素/占位标记）+ 防伪戳 --stamp/--verify-stamp
├── skeleton.py              # 报告骨架生成（v6.14）：从账本出引用编号+来源登记表，正文留【待写】给 Lead（v6.48：conflict 行带出账本留痕，没留痕才写"未裁决"）
├── verify_quotes.py         # 引文逐字对账（v6.44）：账本『…』与报告「…」段须在存档原始材料里逐字命中（v6.46 起含 --report；v6.47 短段列未对账），缺材料或缺待查文本退 2
├── engines/
│   ├── __init__.py          # 引擎导出聚合（34 个数据源，29 个可搜索）
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
    ├── test_env_guidance_no_card.py # 环境指引：带免费额度的源必须同时写明免绑卡自查
    ├── test_pdf_artifact.py   # 制品校验（PDF 魔数/篇幅/完整性/论文 ID 一致；LaTeX 认 gzip）
    ├── test_repo_health_verdict.py # 仓库扫描五态（限流=unknown / 404=真结论 / token 真发出）
    ├── test_validation_stamp.py # 防伪戳（盖戳只在过门后 / 改正文或账本即失效 / 手抄骗不过）
    ├── test_skeleton.py     # 骨架（引用=账本编号 / 登记表不串号 / 【待写】过不了门 / 无账本硬停）
    └── test_v6.py           # tier/ledger/panel/validate/plan/reflect/score/平台引擎/相关性过滤
```

---

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
# - validate_report.py: validate_report（引用一致性 / 反查 / 覆盖率 / 章节 / Tier4 占比 / 六维要素 / 引文逐字对账）
# - verify_quotes.py: check_quotes（账本 claim + 报告正文的『「“段 vs 存档原始材料，逐字命中才算过；misses 用 where 报到行号，短于阈值的段列 unchecked）
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

---

## 十九、更新历史

更新说明与迁移指南见 [CHANGELOG.md](CHANGELOG.md)。

---

