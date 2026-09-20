# Deep Research Ultra v3 → v4 迁移指南

> **文档类型**：版本迁移指南
> **适用版本**：v3.2.0 → v4.0.0
> **生成日期**：2026-07-30
> **破坏性变更**：是（架构重构）

---

## 一、迁移概览

### 1.1 核心变化

| 维度 | v3.2.0 | v4.0.0 |
|------|--------|--------|
| **架构** | 16 引擎平铺（单文件 2000+ 行） | 四层架构（MCP → Skill → 内置 → 降级） |
| **工作流** | 澄清 → 搜索 → 报告（3 步） | Plan-Execute-Synthesize-Reflect（4 阶段） |
| **数据源** | HTML regex 解析为主 | MCP 服务器为主，HTML 解析降级为 fallback |
| **评分** | 标题40+内容30+权威20+时效10（关键词匹配） | CRAAP 五维评分 + LLM 语义评分（可选） |
| **验证** | URL 去重 | 交叉验证（≥2 独立来源）+ 矛盾检测 |
| **报告** | markdown/json/csv | HTML（默认，含 Mermaid）+ markdown + json + csv |
| **缓存** | 仅 TTL（1 小时） | TTL + LRU + maxsize（默认 100MB） |
| **测试** | 无 | pytest 单元测试 + evals.json 32 个用例 |

### 1.2 破坏性变更清单

- ❌ **移除 9 个引擎**：brave / ecosia / startpage / so（360）/ sm（神马）/ yahoo / qwant / google / wolfram
- ❌ **弃用 Jina Reader**：改用 `defuddle` skill 或 Firecrawl MCP
- ❌ **弃用 HTML regex 解析**：作为 Layer 4 fallback 保留，但不再是主路径
- ⚠️ **--sources 参数语义变化**：v3 指定引擎名，v4 自动映射到 Layer 4 降级引擎
- ⚠️ **--format 默认值变化**：v3 默认 markdown，v4 默认 html

### 1.3 新增能力

- ✅ MCP 服务器集成（Tavily / Firecrawl / open-websearch / arxiv / paper-search）
- ✅ 全局 Skill 复用（agent-reach / oss-finder / last30days / sciverse / defuddle / context7）
- ✅ MECE 问题树拆解
- ✅ CRAAP 五维评分 + LLM 语义评分
- ✅ 交叉验证 + 矛盾检测
- ✅ 反思循环（Drill-down）
- ✅ HTML 报告 + Mermaid 图表（时间线/问题树/来源分布）
- ✅ 进度跟踪 + ETA 估算
- ✅ 调研质量自评（六维评分）
- ✅ LRU 缓存（带 maxsize 限制）

---

## 二、架构对比

### 2.1 v3.2.0 架构（单文件平铺）

```
┌──────────────────────────────────────┐
│        search.py (2000+ 行)          │
├──────────────────────────────────────┤
│  16 个引擎（HTML 解析为主）           │
│  ├── baidu    bing    duckduckgo    │
│  ├── so       sogou   wechat   sm   │
│  ├── brave    ecosia  startpage     │
│  ├── tavily   jina    gitee         │
│  └── searxng  (yahoo/qwant 未实现)   │
├──────────────────────────────────────┤
│  缓存（TTL 1h，无 maxsize）           │
│  评分（关键词匹配）                   │
│  报告（markdown/json/csv）            │
└──────────────────────────────────────┘
```

### 2.2 v4.0.0 架构（四层 + 四阶段）

```
┌──────────────────────────────────────────────────────────────┐
│                   Deep Research Ultra v4.0                    │
├──────────────────────────────────────────────────────────────┤
│  Phase 0: 前置配置                                            │
│  ├── MCP 健康检查  ├── Skill 可用性检查  ├── 网络检测          │
│  └── 调研记忆加载（super-memory）                             │
├──────────────────────────────────────────────────────────────┤
│  Phase 1: Plan（规划）— MECE 问题树                           │
│  ├── 主题澄清  ├── MECE 拆解  ├── 假设生成  ├── 数据源匹配    │
│  └── scripts/plan.py                                          │
├──────────────────────────────────────────────────────────────┤
│  Phase 2: Execute（执行）— 并行子 Agent + 反思循环             │
│  ├── 搜索 Agent  ├── 学术 Agent  ├── 社区 Agent              │
│  ├── 开源 Agent  ├── 时效 Agent  ├── 反思循环（Drill-down）   │
│  └── scripts/engines/ + scripts/reflect.py                    │
├──────────────────────────────────────────────────────────────┤
│  Phase 3: Synthesize（合成）— 结构化报告                       │
│  ├── 执行摘要  ├── CER 结构  ├── 矛盾标注  ├── 时间线         │
│  └── scripts/report.py + scripts/score.py + scripts/verify.py│
├──────────────────────────────────────────────────────────────┤
│  Phase 4: Reflect（反思）— 持续改进                             │
│  ├── 质量自评  ├── 反馈收集  ├── super-memory 归档            │
│  └── scripts/progress.py                                      │
└──────────────────────────────────────────────────────────────┘

数据源四层架构：
  Layer 1: MCP（tavily/firecrawl/open-websearch/arxiv/paper-search）
  Layer 2: Skill（agent-reach/oss-finder/last30days/sciverse/defuddle/context7）
  Layer 3: 内置（WebSearch/WebFetch/Task）
  Layer 4: 降级（ddgs/baidu-html/bing-html/searxng）
```

---

## 三、文件结构变化

### 3.1 新增文件

```
projects/deep-research-ultra/
├── scripts/
│   ├── engines/                    # 🆕 引擎模块包
│   │   ├── __init__.py             # 🆕 包导出
│   │   ├── base.py                 # 🆕 SearchEngine 抽象基类 + EngineRegistry
│   │   ├── mcp_client.py           # 🆕 MCP 客户端（JSON-RPC over subprocess）
│   │   ├── mcp_engines.py          # 🆕 Layer 1：5 个 MCP 引擎
│   │   ├── skill_engines.py        # 🆕 Layer 2：6 个 Skill 引擎
│   │   ├── builtin.py              # 🆕 Layer 3：WebSearch/WebFetch
│   │   └── fallback.py             # 🆕 Layer 4：ddgs/baidu/bing/searxng
│   ├── plan.py                     # 🆕 MECE 问题树 + PlanGenerator
│   ├── score.py                    # 🆕 CRAAP 五维评分 + LLM 语义评分
│   ├── verify.py                   # 🆕 交叉验证 + 矛盾检测
│   ├── reflect.py                  # 🆕 反思循环 + Drill-down
│   ├── report.py                   # 🆕 HTML/Mermaid 报告生成
│   ├── progress.py                 # 🆕 进度跟踪 + ETA + 质量自评
│   ├── cache.py                    # 🆕 LRU 缓存（TTL + maxsize）
│   ├── setup-mcp.sh                # 🆕 MCP 一键配置脚本
│   └── tests/
│       └── test_core.py            # 🆕 pytest 单元测试
├── references/
│   ├── mcp-config.md               # 🆕 MCP 配置指南
│   ├── optimization-plan-v4.md     # 🆕 v4 优化方案
│   └── migration-v3-to-v4.md       # 🆕 本文档
└── evals/
    └── evals.json                  # 🔄 更新为 v4.0（32 个用例）
```

### 3.2 保留文件

- `scripts/search.py` — 保留作为 v3 兼容入口和 Layer 4 降级实现
- `SKILL.md` — 更新为 v4.0 主入口
- `references/tool-integration.md` — 保留
- `LICENSE` / `README.md` / `requirements.txt` — 保留

### 3.3 删除文件

无（v3 代码全部保留为 fallback，未删除）

---

## 四、引擎迁移对照表

### 4.1 v3 引擎 → v4 处置

| v3 引擎 | v3 实现方式 | v4 处置 | v4 替代方案 |
|---------|-----------|---------|-------------|
| baidu | HTML regex | ⚠️ 降级为 Layer 4 | open-websearch MCP / Tavily MCP |
| bing | HTML regex | ⚠️ 降级为 Layer 4 | open-websearch MCP / Tavily MCP |
| duckduckgo | ddgs 库 | ⚠️ 降级为 Layer 4 | open-websearch MCP / Tavily MCP |
| tavily | HTTP API | ✅ 升级为 Layer 1 MCP | TavilyMcpEngine |
| jina | HTTP API | ❌ 弃用 | defuddle skill / Firecrawl MCP |
| gitee | HTTP API | ❌ 移除 | oss-finder skill |
| searxng | HTTP API | ⚠️ 降级为 Layer 4 | SearXNGEngine（保留） |
| brave | HTML regex | ❌ 弃用 | Brave Search MCP（需代理） |
| ecosia | HTML regex | ❌ 弃用 | 无（国内不可达） |
| startpage | HTML regex | ❌ 弃用 | 无（国内不可达） |
| so（360） | HTML regex | ❌ 弃用 | 无（份额 < 2%） |
| sm（神马） | HTML regex | ❌ 弃用 | 无（份额小） |
| sogou | HTML regex | ❌ 弃用 | agent-reach（微信公众号） |
| wechat | HTML regex | ❌ 弃用 | agent-reach skill |
| yahoo | 未实现 | ❌ 移除文档承诺 | 无 |
| qwant | 未实现 | ❌ 移除文档承诺 | 无 |
| google | 未实现 | ❌ 移除文档承诺 | WebSearch 内置工具 |
| wolfram | 未实现 | ❌ 移除文档承诺 | WebSearch 内置工具 |

### 4.2 v4 新增引擎

| 引擎 | Layer | 实现文件 | 能力 |
|------|-------|---------|------|
| TavilyMcpEngine | 1 | mcp_engines.py | search/extract/crawl |
| FirecrawlMcpEngine | 1 | mcp_engines.py | search/extract/crawl |
| OpenWebsearchMcpEngine | 1 | mcp_engines.py | search（免费无 Key） |
| ArxivMcpEngine | 1 | mcp_engines.py | academic search |
| PaperSearchMcpEngine | 1 | mcp_engines.py | academic search（14 平台） |
| AgentReachEngine | 2 | skill_engines.py | community（13 平台） |
| OssFinderEngine | 2 | skill_engines.py | opensource search |
| Last30DaysEngine | 2 | skill_engines.py | time-sensitive search |
| SciverseEngine | 2 | skill_engines.py | academic deep search |
| DefuddleEngine | 2 | skill_engines.py | extract（网页转 MD） |
| Context7Engine | 2 | skill_engines.py | docs（库文档） |
| WebSearchEngine | 3 | builtin.py | search（Claude 内置） |
| WebFetchEngine | 3 | builtin.py | extract（Claude 内置） |
| BaiduHtmlEngine | 4 | fallback.py | search（HTML 解析） |
| BingHtmlEngine | 4 | fallback.py | search（HTML 解析） |
| SearXNGEngine | 4 | fallback.py | search（自建） |

---

## 五、CLI 参数迁移

### 5.1 参数对照

| v3 参数 | v4 参数 | 变化说明 |
|---------|---------|---------|
| `--sources baidu,bing` | `--sources baidu,bing`（兼容） | ⚠️ 自动映射到 Layer 4，显示降级提示 |
| `--format markdown`（默认） | `--format html`（默认） | ⚠️ 默认格式改为 HTML |
| `--format markdown` | `--format markdown` | ✅ 保留 |
| `--format json` | `--format json` | ✅ 保留 |
| `--format csv` | `--format csv` | ✅ 保留 |
| `--format html` | `--format html` | ✅ 新增（含 Mermaid） |
| `--max-results 10` | `--max-results 10` | ✅ 保留 |
| `--proxy http://...` | `--proxy http://...` | ✅ 保留 |
| `--history` | `--history` | ✅ 保留 |
| `--feedback 5` | `--feedback 5` | ✅ 保留 |
| `--min-score 70` | `--min-score 70` | ✅ 保留（语义改为 CRAAP 总分） |
| 无 | `--depth quick/standard/deep` | 🆕 新增：调研深度 |
| 无 | `--llm-score` | 🆕 新增：LLM 语义评分（默认关闭） |
| 无 | `--mcp-check` | 🆕 新增：MCP 健康检查 |
| 无 | `--plan-only` | 🆕 新增：仅生成 MECE 计划不执行 |
| 无 | `--reflect-rounds 3` | 🆕 新增：反思循环轮数 |

### 5.2 v3 兼容性保证

v3 的 CLI 语法在 v4 中**完全兼容**：

```bash
# v3 语法（v4 仍可用，自动降级到 Layer 4）
python scripts/search.py "AI agent" --sources baidu,bing,duckduckgo --format markdown

# v4 推荐语法（使用 MCP）
python scripts/search.py "AI agent" --depth standard --format html
```

---

## 六、API 迁移

### 6.1 Python API 变化

#### v3 调用方式

```python
from search import search, format_results

results = search("AI agent", sources=['baidu', 'bing'], max_results=10)
print(format_results(results, format='markdown'))
```

#### v4 推荐调用方式

```python
from engines import EngineRegistry, TavilyMcpEngine, WebSearchEngine
from plan import PlanGenerator
from score import CraapScorer
from verify import CrossVerifier
from reflect import Reflector
from report import ReportGenerator

# 1. 注册引擎
registry = EngineRegistry()
registry.register(TavilyMcpEngine())      # Layer 1（如已配置）
registry.register(WebSearchEngine())       # Layer 3（始终可用）

# 2. 生成 MECE 计划
gen = PlanGenerator()
plan = gen.generate_plan(topic="AI agent 框架", depth="standard")

# 3. 执行搜索（按降级链）
chain = registry.get_fallback_chain()
all_results = []
for engine in chain:
    if engine.has_capability('search'):
        results = engine.search(plan.topic, max_results=10)
        if results:
            all_results.extend(results)
            break  # 命中即停（或继续聚合）

# 4. CRAAP 评分
scorer = CraapScorer()
for r in all_results:
            r.craap_score = scorer.score(r, query=plan.topic)

# 5. 交叉验证
verifier = CrossVerifier()
verification = verifier.verify(all_results, query=plan.topic)

# 6. 生成报告
reporter = ReportGenerator()
html = reporter.generate(plan, all_results, verification, format='html')
```

### 6.2 数据结构变化

#### SearchResult（v4 新增字段）

```python
@dataclass
class SearchResult:
    # v3 字段（保留）
    title: str
    url: str
    content: str
    source: str
    score: float = 0.0
    published_date: str = ''
    # v4 新增字段
    craap_score: Optional[Dict] = None    # CRAAP 五维评分
    author: str = ''                       # 作者
    engine: str = ''                       # 实际使用的引擎
    raw: Dict = field(default_factory=dict)  # 原始数据
```

---

## 七、迁移步骤

### 7.1 推荐迁移路径（5 步）

#### Step 1：备份 v3 配置

```bash
# 备份 v3 缓存和历史
cp -r ~/.cache/deep-research ~/.cache/deep-research-v3-backup
```

#### Step 2：配置 MCP 服务器（推荐）

```bash
# 一键配置核心 MCP（免费）
cd projects/deep-research-ultra
bash scripts/setup-mcp.sh --core

# 或配置全部 MCP（含需 API Key 的）
bash scripts/setup-mcp.sh --all
```

详见 `references/mcp-config.md`。

#### Step 3：验证 MCP 配置

```bash
# 检查 MCP 健康状态
python scripts/search.py --mcp-check
```

预期输出：

```
✅ open-websearch: 可用
✅ arxiv: 可用
✅ paper-search: 可用
⚠️ tavily: 未配置 TAVILY_API_KEY
⚠️ firecrawl: 未配置 FIRECRAWL_API_KEY
```

#### Step 4：运行 v4 调研

```bash
# 标准深度调研（HTML 报告）
python scripts/search.py "深度调研 2025 年 AI Agent 框架" --depth standard

# 深度模式（多轮反思）
python scripts/search.py "深度调研大语言模型微调" --depth deep --reflect-rounds 3

# 仅生成 MECE 计划
python scripts/search.py "深度调研 RAG 最佳实践" --plan-only
```

#### Step 5：运行单元测试（可选）

```bash
cd scripts
python -m pytest tests/ -v
```

### 7.2 渐进式迁移（保守方案）

如果不想立即配置 MCP，可继续使用 v3 语法，v4 会自动降级：

```bash
# v3 语法仍可用（降级到 Layer 4）
python scripts/search.py "AI" --sources baidu,bing,duckduckgo

# 输出会显示降级提示：
# ⚠️ 当前使用降级模式（Layer 4: HTML 解析）
# 💡 建议运行 setup-mcp.sh --core 配置 MCP 以获得更稳定的结果
```

---

## 八、回滚方案

如需回滚到 v3.2.0：

```bash
# 1. 恢复 v3 缓存
cp -r ~/.cache/deep-research-v3-backup/* ~/.cache/deep-research/

# 2. 使用 v3 入口（search.py 保留 v3 逻辑）
python scripts/search.py "关键词" --sources baidu,bing --format markdown

# 3. v4 模块不会影响 v3 调用（独立模块）
```

---

## 九、常见问题

### Q1：v3 的缓存能被 v4 读取吗？

**能**。v4 的 `LRUCache` 兼容 v3 的缓存格式（JSON 文件），但会忽略 v3 缺少的新字段（如 `_accessed_at`）。建议清理旧缓存重新生成：

```bash
rm -rf ~/.cache/deep-research/*.json
```

### Q2：未配置 MCP 时 v4 还能用吗？

**能**。v4 会自动降级到 Layer 3（Claude 内置 WebSearch/WebFetch）或 Layer 4（ddgs/HTML 解析），但结果质量和稳定性会下降。

### Q3：v4 的 CRAAP 评分和 v3 的评分能对应吗？

**不能直接对应**。v3 评分是 0-100 的关键词匹配分；v4 是 CRAAP 五维评分（每维 0-100，加权总分 0-100）。两者数值含义不同，不要混用。

### Q4：v3 的 `--sources yahoo` 在 v4 会怎样？

**会显示警告并跳过**。Yahoo 在 v3 就未实现，v4 明确从文档中移除：

```
⚠️ 引擎 'yahoo' 在 v4 中已移除（v3 未实现）
💡 可用引擎：tavily, firecrawl, open-websearch, arxiv, ...
```

### Q5：v4 的 HTML 报告需要联网加载 Mermaid.js 吗？

**不需要**。Mermaid.js 已内联到 HTML 中（CDN fallback），离线可用。

### Q6：如何禁用 LLM 语义评分？

默认就是禁用的。如需启用：`--llm-score`。注意会消耗额外 token。

---

## 十、迁移检查清单

- [ ] 备份 v3 缓存目录
- [ ] 运行 `bash scripts/setup-mcp.sh --core` 配置免费 MCP
- [ ] 运行 `python scripts/search.py --mcp-check` 验证 MCP
- [ ] 运行 `python -m pytest tests/ -v` 验证单元测试
- [ ] 用 v4 语法执行一次标准调研
- [ ] 检查 HTML 报告是否包含 Mermaid 图表
- [ ] 检查报告中是否有 CRAAP 评分和交叉验证标注
- [ ] （可选）配置 Tavily/Firecrawl API Key 获得更强能力
- [ ] （可选）启用 `--llm-score` 提升评分准确性
- [ ] 更新项目文档中的调用示例

---

## 十一、联系与反馈

- 问题反馈：在项目 issue 中报告
- 文档错误：直接修改本文件并提交 PR
- v3 兼容性问题：v3 语法保证兼容至 v4.x，v5 可能移除

---

**文档版本**：v1.0
**最后更新**：2026-07-30
