# Deep Research Ultra — 超级深度调研工具 v4.0

> **Plan-Execute-Synthesize-Reflect 四阶段深度调研范式**
> **MCP 服务器 + 全局 Skill + 内置工具 + 降级引擎的四层数据源架构**

🚀 **[点击查看教程网页](https://harryopo.github.io/deep-research-ultra/)**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-orange.svg)](https://claude.ai/code)
[![Version](https://img.shields.io/badge/version-4.0.0-brightgreen.svg)]()

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🧠 **四阶段工作流** | Plan → Execute → Synthesize → Reflect 深度调研范式 |
| 🏗️ **四层数据源** | MCP 服务器 → 全局 Skill → Claude 内置 → 降级引擎 |
| 🌲 **MECE 问题树** | 麦肯锡 MECE 原则拆解主题，互斥穷尽不遗漏 |
| 📊 **CRAAP 评分** | 五维可信度评估（时效/相关/权威/准确/目的） |
| ✓ **交叉验证** | 同一结论需 ≥2 个独立来源支持，矛盾点自动标注 |
| 🔄 **反思循环** | Drill-down 决策，覆盖率不足时自动生成深挖问题 |
| 📝 **结构化报告** | CER 结构（Claim-Evidence-Reasoning）+ Mermaid 可视化 |
| 🔌 **MCP 集成** | Tavily/Firecrawl/open-websearch/arxiv/paper-search |
| 🎨 **Skill 复用** | agent-reach/sciverse/oss-finder/last30days/defuddle/context7 |
| 💾 **智能缓存** | LRU + TTL + 磁盘持久化，避免重复请求 |
| 📊 **进度跟踪** | 实时 ETA 估算 + 质量自评（覆盖率/验证率/矛盾处理率） |

---

## 📦 安装

### 前置条件

- Python 3.10+
- Claude Code 或 TRAE（用于调用 Skill 与 MCP）
- Node.js 16+（用于运行 MCP 服务器，通过 npx）
- uv/uvx（可选，用于 Python 类 MCP 服务器）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/deep-research-ultra.git
cd deep-research-ultra

# 2. 安装 Python 依赖（仅 ddgs 一个第三方库）
pip install -r requirements.txt

# 3. 一键配置 MCP（推荐 --core 免费模式，3 分钟完成）
bash scripts/setup-mcp.sh --core

# 4. 检查数据源可用性
python scripts/research.py --mcp-check

# 5. 列出所有引擎
python scripts/research.py --list
```

### 依赖说明

| 依赖 | 用途 | 必需 |
|------|------|------|
| `ddgs` | DuckDuckGo 搜索（Layer 4 降级引擎） | ✅ 是 |
| Python 标准库 | urllib/json/subprocess（核心模块） | ✅ 内置 |
| `mcp` | 独立调用 MCP 服务器（不通过 Claude） | ❌ 可选 |
| `jieba` | 中文分词（提升评分准确性） | ❌ 可选 |

> 💡 v4.0 核心模块仅依赖 Python 标准库 + ddgs，最小化依赖体积。

---

## ⚙️ 配置

### 四层数据源架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: MCP 服务器层（首选，结构化、稳定）                     │
│  ├── Tavily MCP        AI 搜索 + extract + map + crawl          │
│  ├── Firecrawl MCP     搜索 + scrape + crawl + browser 自动化   │
│  ├── open-websearch    免费、无 Key、Bing/百度/CSDN/掘金等      │
│  ├── arxiv MCP         arXiv 论文                                │
│  └── paper-search MCP  14 学术平台聚合                           │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: 全局 Skill 层（已存在，直接复用）                      │
│  ├── agent-reach       13 平台社交（X/Reddit/HN/B站/知乎...）   │
│  ├── oss-finder        GitHub/GitLab/Gitee/npm/PyPI             │
│  ├── last30days        近 30 天全网                              │
│  ├── sciverse          学术论文深度检索                          │
│  ├── defuddle          网页转 Markdown（替代 Jina Reader）       │
│  └── context7          库文档拉取                                │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: Claude 内置工具层                                      │
│  ├── WebSearch         实时网络搜索                              │
│  ├── WebFetch          简单网页抓取                              │
│  └── Task (subagent)   并行子 Agent                             │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4: 自建/降级层（仅当上面都不可用时）                      │
│  ├── DuckDuckGo       ddgs Python 库（免费、无需 Key）          │
│  ├── 百度/Bing HTML   HTML 解析（最后手段，易失效）              │
│  └── SearXNG          自建元搜索（Docker 部署）                  │
└─────────────────────────────────────────────────────────────────┘
```

### 配置场景

| 场景 | 推荐操作 |
|------|----------|
| 零配置快速开始 | `bash setup-mcp.sh --core`（免费 MCP） |
| 国内无 VPN | `--core` + Tavily（可选） |
| 有 VPN | `--core` + Tavily + Firecrawl + Brave Search MCP |
| 学术调研 | `--core` + Semantic Scholar MCP + Scientific-Papers-MCP |

详见 [references/mcp-config.md](references/mcp-config.md)

### 环境变量配置

```bash
# ========== Layer 1: MCP 增强层（可选）==========

# Tavily AI 搜索（推荐，免费 1000 次/月）
# 获取地址：https://app.tavily.com
export TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxx

# Firecrawl 搜索 + 抓取（免费 500 credits/月）
# 获取地址：https://firecrawl.dev
export FIRECRAWL_API_KEY=fc-xxxxxxxxxxxxxxxxxxxxx

# ========== Layer 4: 降级层（可选）==========

# SearXNG 自建实例地址
export SEARXNG_URL=http://localhost:8080

# ========== 代理配置（可选）==========

# HTTP 代理（用于访问国际服务）
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

---

## 🚀 使用方法

### 作为 Claude Code / TRAE Skill 使用（推荐）

```bash
# 在 Claude Code 中调用
/deep-research-ultra 深度调研 2025 年最值得学习的 Python Web 框架

# 或使用触发词
帮我深度研究一下 Kubernetes 生产环境最佳实践
全面分析 FastAPI vs Django REST Framework 的性能对比
```

### 命令行使用（v4 推荐）

```bash
# 自动选择数据源（推荐，默认 HTML 报告）
python scripts/research.py "Python Web 框架"

# 指定深度与反思轮数
python scripts/research.py "AI agent" --depth deep --reflect-rounds 3

# 指定数据源（v4 引擎名）
python scripts/research.py "AI agent" --sources tavily,arxiv

# 搜索所有可用数据源（聚合模式）
python scripts/research.py "AI 趋势" --all

# 仅生成 MECE 计划（不执行搜索）
python scripts/research.py "RAG 最佳实践" --plan-only

# 输出到文件（HTML 报告推荐）
python scripts/research.py "FastAPI vs Django" --format html -o report.html

# v3 兼容（自动映射到 Layer 4 降级引擎）
python scripts/research.py "AI" --sources baidu,bing,duckduckgo --format markdown
```

### 引擎决策示例

| 场景 | 推荐数据源 | 理由 |
|------|-----------|------|
| **中文技术问题** | `open-websearch,tavily,agent-reach` | 中文内容 + 结构化 + 社区口碑 |
| **英文学术问题** | `arxiv,paper-search,sciverse` | 三个学术数据源全覆盖 |
| **开源项目搜索** | `oss-finder,tavily,open-websearch` | 项目搜索 + 评测文章 |
| **近期热点** | `last30days,agent-reach,tavily` | 时效性 + 社区讨论 |

---

## 📊 输出格式

### HTML 格式（v4 默认，含 Mermaid 图表）

```bash
python scripts/research.py "AI agent" --format html -o report.html
```

包含：
- MECE 问题树可视化（Mermaid graph）
- 时间线图表（Mermaid timeline）
- CRAAP 评分表
- 来源分布图
- 矛盾点标注

### Markdown 格式（适合归档）

```bash
python scripts/research.py "AI agent" --format markdown
```

### JSON 格式（适合 API 集成）

```bash
python scripts/research.py "AI agent" --format json
```

### CSV 格式（适合 Excel 分析）

```bash
python scripts/research.py "AI agent" --format csv
```

---

## 🧠 四阶段工作流

### Phase 1: Plan（规划）— MECE 问题树

将模糊主题拆解为互斥穷尽（MECE）的子问题树，每个子问题附可验证假设。

```bash
python scripts/research.py "RAG 最佳实践" --plan-only --depth standard
```

输出：
- MECE 问题树（含假设、数据源匹配）
- MECE 验证（重叠度、覆盖度评分）
- Mermaid 可视化图

### Phase 2: Execute（执行）— 并行子 Agent + 反思循环

并行调度子 Agent 收集证据，每轮搜索后 LLM 评估是否需要 Drill-down。

### Phase 3: Synthesize（合成）— 结构化报告

基于证据池生成 CER 结构报告：
- **Claim**：结论
- **Evidence**：证据（带来源 URL + CRAAP 评分）
- **Reasoning**：推理链

### Phase 4: Reflect（反思）— 持续改进

调研质量自评 + 用户反馈 + 记忆归档。

| 指标 | 计算方式 | 目标值 |
|------|----------|--------|
| 覆盖率 | 已有证据的子问题数 / 总子问题数 | ≥ 90% |
| 交叉验证率 | 有 ≥2 独立来源的结论数 / 总结论数 | ≥ 70% |
| 矛盾处理率 | 已处理矛盾数 / 发现矛盾数 | = 100% |
| 平均 CRAAP 分 | 所有来源 CRAAP 均分 | ≥ 70 |

---

## 🔧 高级功能

### 深度策略

| 深度 | 子问题数 | 数据源数 | 反思轮次 | 报告字数 | 预计耗时 |
|------|----------|----------|----------|----------|----------|
| quick | 2-3 | 2-3 | 0 | 1500-3000 | 1-3 分钟 |
| standard | 4-6 | 3-5 | 1 | 3000-6000 | 5-8 分钟 |
| deep | 7-10 | 5-8 | 2-3 | 6000-15000 | 10-20 分钟 |
| extreme | 10+ | 8+ | 3+ | 15000+ | 20-40 分钟 |

### CRAAP 五维评分

| 维度 | 含义 | 分值 |
|------|------|------|
| **C**urrency | 时效性 | 0-20 |
| **R**elevance | 相关性 | 0-20 |
| **A**uthority | 权威性 | 0-20 |
| **A**ccuracy | 准确性 | 0-20 |
| **P**urpose | 目的性 | 0-20 |

```bash
# 启用 LLM 语义评分（更准确，但消耗 token）
python scripts/research.py "关键词" --llm-score
```

### 智能缓存

- 缓存目录：`~/.cache/deep-research/`
- TTL：1 小时
- LRU 淘汰：maxsize 100
- 线程安全 + 磁盘持久化

```bash
# 禁用缓存
python scripts/research.py "query" --no-cache
```

---

## 📁 项目结构

```
deep-research-ultra/
├── SKILL.md                    # Claude Code Skill 定义（v4.0）
├── README.md                   # 本文件
├── requirements.txt            # Python 依赖（仅 ddgs）
├── LICENSE                     # MIT 许可证
├── scripts/
│   ├── research.py             # v4 主入口（CLI）
│   ├── search.py               # v3 兼容入口（保留）
│   ├── setup-mcp.sh            # MCP 一键配置脚本
│   ├── engines/
│   │   ├── base.py             # SearchEngine 抽象基类 + EngineRegistry
│   │   ├── mcp_client.py       # MCP 客户端封装
│   │   ├── mcp_engines.py      # MCP 服务器封装（5 个）
│   │   ├── skill_engines.py    # 全局 skill 封装（6 个）
│   │   ├── builtin.py          # Claude 内置工具封装
│   │   └── fallback.py         # 降级引擎（4 个）
│   ├── plan.py                 # MECE 问题树 + PlanGenerator
│   ├── score.py                # CRAAP 五维评分
│   ├── verify.py               # 交叉验证 + 矛盾检测
│   ├── reflect.py              # 反思循环 + Drill-down
│   ├── report.py               # 报告生成（md/html/csv + Mermaid）
│   ├── progress.py             # 进度跟踪 + ETA 估算
│   ├── cache.py                # LRU 缓存
│   └── tests/
│       └── test_core.py        # 单元测试（63 个用例）
├── evals/
│   └── evals.json              # 评测集（32 个场景）
└── references/
    ├── mcp-config.md           # MCP 配置指南
    ├── tool-integration.md     # 工具集成指南
    ├── optimization-plan-v4.md # v4.0 优化方案
    └── migration-v3-to-v4.md   # v3 → v4 迁移指南
```

---

## 🆚 与竞品对比

| 特性 | Deep Research Ultra v4 | Perplexity | OpenAI Deep Research | LangChain open_deep_research |
|------|------------------------|------------|---------------------|------------------------------|
| **架构** | 四层 + 四阶段 | 单引擎 | 闭源 | 单框架 |
| **MECE 问题树** | ✅ | ❌ | ❌ | ❌ |
| **CRAAP 评分** | ✅ 五维 | ❌ | ❌ | ❌ |
| **交叉验证** | ✅ ≥2 独立源 | ❌ | ❌ | ❌ |
| **反思循环** | ✅ 最多 3 轮 | ❌ | ✅ | ✅ |
| **MCP 集成** | ✅ 5 个 MCP | ❌ | ❌ | ❌ |
| **Skill 复用** | ✅ 6 个 skill | ❌ | ❌ | ❌ |
| **中文优化** | ✅ 多引擎 | ⚠️ 有限 | ⚠️ 有限 | ❌ |
| **免费使用** | ✅ 完全免费 | ❌ 付费 | ❌ 付费 | ✅ 开源 |
| **Claude Code 集成** | ✅ 原生 Skill | ❌ | ❌ | ❌ |
| **报告格式** | HTML/MD/JSON/CSV | 文本 | 文本 | 文本 |
| **Mermaid 可视化** | ✅ | ❌ | ❌ | ❌ |

---

## 🧪 测试

```bash
# 运行单元测试（63 个用例）
cd scripts && python -m pytest tests/test_core.py -v

# 端到端测试（dry-run）
python scripts/research.py --mcp-check
python scripts/research.py "测试" --plan-only --depth quick
python scripts/research.py "测试" --depth quick --format html -o test.html
```

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

### 添加新引擎

```python
# 在 scripts/engines/ 下创建新引擎类
from engines.base import SearchEngine, EngineMetadata, SearchResult

class NewEngine(SearchEngine):
    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="new-engine",
            layer=4,  # 1=MCP, 2=Skill, 3=内置, 4=降级
            description="新引擎描述",
            capabilities=["search"],
            priority=400,
        )

    def is_available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 10, **kwargs):
        # 实现搜索逻辑
        return [SearchResult(title=..., url=..., content=..., source='new-engine')]
```

然后在 `research.py` 的 `build_registry()` 中注册。

---

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE)。

### 整合的开源工具

| 工具 | 许可证 | 来源 |
|------|--------|------|
| DuckDuckGo (ddgs) | MIT | https://github.com/deedy5/ddgs |
| SearXNG | AGPL-3.0 | https://github.com/searxng/searxng |
| Tavily MCP | MIT | https://github.com/tavily-ai/tavily-mcp |
| Firecrawl MCP | MIT | https://github.com/mendableai/firecrawl-mcp |
| open-websearch MCP | MIT | https://github.com/nicholishen/open-websearch |

### 商业服务（有免费额度）

- Tavily: https://tavily.com（免费 1000 次/月）
- Firecrawl: https://firecrawl.dev（免费 500 credits/月）

---

## 📚 参考资料

### 内部参考

- [references/mcp-config.md](references/mcp-config.md) — MCP 配置指南
- [references/tool-integration.md](references/tool-integration.md) — 工具集成指南
- [references/optimization-plan-v4.md](references/optimization-plan-v4.md) — v4.0 优化方案
- [references/migration-v3-to-v4.md](references/migration-v3-to-v4.md) — v3 → v4 迁移指南

### 外部参考

- **OpenAI Deep Research 官方指导**：Plan → Execute → Synthesize 三步范式
- **LangChain open_deep_research**：https://github.com/langchain-ai/open_deep_research
- **字节跳动 DeerFlow 2.0**：https://github.com/bytedance/deer-flow
- **麦肯锡方法**：MECE 原则、假设驱动、逻辑树、金字塔原理
- **CRAAP Test**：信息可信度评估标准
- **CER（Claim-Evidence-Reasoning）**：科学论证结构

---

## 🔗 相关项目

- **[oss-finder](https://github.com/YOUR_USERNAME/oss-finder)** — 开源项目搜索工具
- **[agent-reach](https://github.com/YOUR_USERNAME/agent-reach)** — 社交媒体搜索工具
- **[skill-workspace](https://github.com/YOUR_USERNAME/skill-workspace)** — Skill 开发工作台

---

## 📞 支持

- 🐛 [提交 Bug](https://github.com/YOUR_USERNAME/deep-research-ultra/issues)
- 💡 [功能建议](https://github.com/YOUR_USERNAME/deep-research-ultra/issues)
- 📖 [文档](https://github.com/YOUR_USERNAME/deep-research-ultra/wiki)

---

## 🙏 致谢

感谢以下开源项目与方法论：

- [DuckDuckGo (ddgs)](https://github.com/deedy5/ddgs) — 免费搜索 API
- [SearXNG](https://github.com/searxng/searxng) — 元搜索引擎
- [Tavily](https://tavily.com) — AI 搜索引擎
- [Firecrawl](https://firecrawl.dev) — 网页抓取与浏览器自动化
- 麦肯锡 MECE 原则 — 问题拆解方法论
- CRAAP Test — 信息可信度评估标准
- CER Framework — 科学论证结构

---

**⭐ 如果这个项目对你有帮助，请给个 Star！**

---

*v4.0 · 2026-07-30 · 基于 Plan-Execute-Synthesize-Reflect 范式*
