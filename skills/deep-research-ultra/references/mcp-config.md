# Deep Research Ultra v4.0 — MCP 配置指南

> 本文档介绍如何为深度调研 skill 配置 MCP（Model Context Protocol）服务器。
> MCP 是 Anthropic 推出的开放协议，让 Claude 能够调用外部工具和数据源。

---

## 一、为什么需要 MCP

### v3.x 的问题

v3.x 版本通过 HTML 解析（regex）方式抓取搜索引擎结果，存在以下致命问题：

- 搜索引擎改版前端立即失效
- HTML 解析代码维护成本高（每个引擎 80-100 行相似代码）
- 国内不可达的引擎（Brave/Ecosia/Startpage）只测主页连通性，未测真实搜索
- 缺少权威学术数据源（arXiv/PubMed/Semantic Scholar）

### v4.0 的方案

v4.0 改用 MCP 服务器作为首选数据源：

- **官方/社区维护**：MCP 服务器由数据源官方或活跃社区维护，稳定性远高于自研 HTML 解析
- **结构化输出**：返回 JSON 结构化数据，无需 regex 解析
- **工具丰富**：单个 MCP 通常提供 4-13 个工具（搜索/抓取/爬取/地图等）
- **生态红利**：2025-2026 年 MCP 生态爆发，免费 MCP 数量已超过 50 个

---

## 二、MCP 服务器清单

### 2.1 核心 MCP（推荐配置）

| MCP 服务器 | 免费额度 | 工具数 | 国内可用 | 用途 | 推荐度 |
|-----------|----------|--------|----------|------|--------|
| **open-websearch** | 完全免费、无需 Key | 4 | ✅ | Bing/百度/CSDN/DuckDuckGo/Exa/Brave/掘金多引擎 | ⭐⭐⭐⭐⭐ |
| **Tavily MCP** | 1000 次/月 | 4+ | ✅ | AI 搜索 + 内容提取 + 网站地图 + 爬取 | ⭐⭐⭐⭐⭐ |
| **arxiv-mcp-server** | 完全免费 | 4 | ✅ | arXiv 论文搜索与下载 | ⭐⭐⭐⭐⭐ |
| **paper-search-mcp** | 完全免费 | 多个 | ✅ | 聚合 14 学术平台（arXiv/PubMed/bioRxiv/Semantic Scholar/Crossref/OpenAlex 等） | ⭐⭐⭐⭐⭐ |
| **Firecrawl MCP** | 500 credits/月 | 13 | ✅ | 搜索+抓取+爬取+地图+浏览器交互+自主研究 agent | ⭐⭐⭐⭐ |

### 2.2 增强 MCP（可选）

| MCP 服务器 | 免费额度 | 工具数 | 国内可用 | 用途 |
|-----------|----------|--------|----------|------|
| **Brave Search MCP** | 1000 次/月 | 5+ | ❌ 需代理 | 独立索引、隐私保护、强筛选 |
| **Exa MCP** | 1000 次/月 | 4 | ❌ 需代理 | 神经网络搜索、AI 增强 |
| **Semantic Scholar MCP** | 完全免费 | 4+ | ✅ | 200M+ 论文 + AI 引用上下文 |
| **Scientific-Papers-MCP** | 完全免费 | 5 | ✅ | arXiv/OpenAlex/PMC/bioRxiv/CORE + 引用分析 |
| **mcp-omnisearch** | 取决子 provider | 4 | 取决配置 | 聚合 Tavily/Brave/Kagi/Exa/GitHub/Linkup/Firecrawl |
| **Sequential Thinking MCP** | 免费 | 1 | ✅ | 强制分步推理（深度调研反思） |

### 2.3 弃用方案

| 工具 | 处置 | 理由 |
|------|------|------|
| Jina Reader | ❌ 弃用 | 用 defuddle skill 或 Firecrawl MCP 替代，无需 VPN |
| Brave（HTML 解析） | ❌ 弃用 | 用 Brave Search MCP 替代（如需代理可用） |
| Ecosia/Startpage | ❌ 弃用 | 国内不可达，市场份额极低 |
| 360/神马 | ❌ 弃用 | 市场份额 < 5%，结果重复度高 |

---

## 三、一键配置

### 3.1 使用配置脚本（推荐）

```bash
# 交互式配置全部 MCP
bash scripts/setup-mcp.sh

# 仅配置免费 MCP（无需任何 API Key）
bash scripts/setup-mcp.sh --core

# 配置 Tavily 并指定 Key
bash scripts/setup-mcp.sh --tavily tvly-xxxxxxxxxxxx

# 检查现有配置
bash scripts/setup-mcp.sh --check

# 移除所有已配置的调研 MCP
bash scripts/setup-mcp.sh --uninstall
```

### 3.2 前置依赖

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| **Node.js + npx** | 运行 npx 类 MCP | https://nodejs.org/ |
| **Python + uvx** | 运行 arxiv-mcp-server | `pip install uv` |
| **Claude Code CLI** | 配置 MCP | https://claude.ai/code |

### 3.3 验证配置

```bash
# 查看 MCP 列表
claude mcp list

# 在 Claude Code 中测试
# 启动 Claude Code 后，MCP 工具会自动可用
```

---

## 四、手动配置（如脚本失败）

### 4.1 Tavily MCP

```bash
# 获取 API Key：https://app.tavily.com
# 免费额度：1000 次/月

claude mcp add tavily \
    -e TAVILY_API_KEY=tvly-xxxxxxxxxxxx \
    -- npx -y tavily-mcp@latest
```

**工具列表：**
- `tavily-search` — AI 搜索（basic/advanced 深度）
- `tavily-extract` — 从 URL 提取内容
- `tavily-map` — 网站地图发现
- `tavily-crawl` — 网站爬取

### 4.2 open-websearch MCP（完全免费）

```bash
# 无需 API Key，开箱即用
claude mcp add open-websearch \
    -e DEFAULT_SEARCH_ENGINE=bing \
    -e MODE=stdio \
    -- npx -y open-websearch@latest
```

**工具列表：**
- `search` — 多引擎搜索（Bing/百度/CSDN/DuckDuckGo/Exa/Brave/掘金）
- `fetchCsdnArticle` — 抓取 CSDN 文章
- `fetchLinuxDoArticle` — 抓取 Linux.do 文章
- `fetchGithubReadme` — 抓取 GitHub README

### 4.3 arXiv MCP

```bash
# 需要先安装 uv
pip install uv

claude mcp add arxiv -- uvx arxiv-mcp-server
```

**工具列表：**
- `search_papers` — 搜索 arXiv 论文
- `download_paper` — 下载论文 PDF
- `list_papers` — 列出已下载论文
- `read_paper` — 读取论文内容

### 4.4 paper-search MCP

```bash
claude mcp add paper-search -- npx -y paper-search-mcp-nodejs
```

**支持平台（14 个）：**
- arXiv / PubMed / bioRxiv / medRxiv
- Semantic Scholar / Google Scholar
- OpenAlex / Crossref / CORE
- Europe PMC / PMC / DOAJ
- Microsoft Academic / Unpaywall

### 4.5 Firecrawl MCP

```bash
# 获取 API Key：https://www.firecrawl.dev/
# 免费额度：500 credits/月

claude mcp add firecrawl \
    -e FIRECRAWL_API_KEY=fc-xxxxxxxxxxxx \
    -- npx -y firecrawl-mcp
```

**工具列表（13 个）：**
- `firecrawl_search` — 搜索
- `firecrawl_scrape` — 抓取单个 URL
- `firecrawl_crawl` — 爬取整个网站
- `firecrawl_map` — 网站地图
- `firecrawl_extract` — 结构化提取
- `firecrawl_check_crawl_status` — 检查爬取状态
- 以及更多（共 13 个工具）

---

## 五、降级策略

当 MCP 不可用时，按以下优先级降级：

```
优先级 1: Tavily MCP（AI 搜索 + 结构化）
   ↓ 不可用
优先级 2: Firecrawl MCP（搜索 + scrape）
   ↓ 不可用
优先级 3: open-websearch MCP（免费多引擎）
   ↓ 不可用
优先级 4: Claude 内置 WebSearch（兜底）
   ↓ 不可用
优先级 5: ddgs Python 库（最后手段）
```

### 场景对应的推荐配置

| 场景 | 推荐配置 |
|------|----------|
| **零配置快速开始** | 仅 `--core`（open-websearch + arxiv + paper-search） |
| **国内无 VPN** | `--core` + Tavily（可选） |
| **有 VPN** | `--core` + Tavily + Firecrawl + Brave Search MCP |
| **学术调研** | `--core` + Semantic Scholar MCP + Scientific-Papers-MCP |
| **新闻/时事** | `--core` + last30days skill |
| **社区口碑** | `--core` + agent-reach skill |

---

## 六、配置示例：.mcp.json

如需项目级配置（团队共享），可在项目根目录创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "open-websearch": {
      "command": "npx",
      "args": ["-y", "open-websearch@latest"],
      "env": {
        "DEFAULT_SEARCH_ENGINE": "bing",
        "MODE": "stdio"
      }
    },
    "arxiv": {
      "command": "uvx",
      "args": ["arxiv-mcp-server"]
    },
    "paper-search": {
      "command": "npx",
      "args": ["-y", "paper-search-mcp-nodejs"]
    },
    "tavily": {
      "command": "npx",
      "args": ["-y", "tavily-mcp@latest"],
      "env": {
        "TAVILY_API_KEY": "${TAVILY_API_KEY}"
      }
    }
  }
}
```

> ⚠️ **注意**：`.mcp.json` 中的 `${VAR}` 语法会从环境变量读取，避免硬编码 Key。

---

## 七、故障排查

### 7.1 MCP 工具未出现在 Claude Code 中

**原因 1：未重启 Claude Code 会话**

```bash
# 配置 MCP 后必须重启 Claude Code 会话
# 退出当前会话，重新启动
```

**原因 2：MCP 服务器启动失败**

```bash
# 检查 MCP 状态
claude mcp list

# 查看 MCP 日志
claude mcp logs <mcp-name>
```

### 7.2 npx 下载超时

```bash
# 使用国内镜像
npm config set registry https://registry.npmmirror.com

# 或使用 cnpm
npm install -g cnpm --registry=https://registry.npmmirror.com
```

### 7.3 uvx 未安装

```bash
# 安装 uv（Python 包管理器）
pip install uv

# 验证
uvx --version
```

### 7.4 Tavily API 调用失败

- **401 Unauthorized**：API Key 错误，检查 `TAVILY_API_KEY` 环境变量
- **429 Too Many Requests**：超出免费额度（1000 次/月），下月重置或升级套餐
- **超时**：检查网络，必要时配置代理

### 7.5 arXiv MCP 无法下载论文

```bash
# 检查 arxiv-mcp-server 是否运行
claude mcp list

# 手动测试
uvx arxiv-mcp-server --help
```

---

## 八、与全局 Skill 的协作

MCP 服务器是数据源层，全局 skill 是数据增强层。两者协同工作：

| 数据源类型 | MCP 服务器 | 全局 Skill |
|-----------|-----------|-----------|
| 网页搜索 | Tavily / open-websearch / Firecrawl | multi-search-engine（旧） |
| 学术论文 | arxiv / paper-search / Semantic Scholar | sciverse |
| 社交媒体 | — | agent-reach（13 平台） |
| 开源项目 | — | oss-finder |
| 时效热点 | — | last30days |
| 网页内容提取 | Firecrawl / Tavily extract | defuddle / context7 |
| 浏览器自动化 | — | agent-browser |

**协同示例**：

```
调研主题：FastAPI vs Django REST Framework

Phase 1: Plan（MECE 问题树）
  Q1: 性能对比
  Q2: 生态对比
  Q3: 生产案例

Phase 2: Execute（多源并行）
  Q1 数据源：
    - Tavily MCP（搜索性能基准测试文章）
    - arxiv MCP（搜索相关论文）
    - oss-finder（搜索两个框架的 stars/commits）
  
  Q2 数据源：
    - open-websearch MCP（搜索中文技术博客）
    - agent-reach（搜索 Reddit/HN 上的讨论）
    - context7（拉取两个框架的最新文档）
  
  Q3 数据源：
    - Firecrawl MCP（爬取官方案例页面）
    - last30days（最近 30 天的相关讨论）
    - agent-reach（搜索 B站/YouTube 的视频教程）

Phase 3: Synthesize（合成报告）
  - CRAAP 评分
  - 交叉验证
  - CER 结构
```

---

## 九、参考资源

### 9.1 MCP 官方文档

- **MCP 规范**：https://modelcontextprotocol.io/
- **Anthropic MCP 介绍**：https://www.anthropic.com/news/model-context-protocol
- **Claude Code MCP 配置**：https://docs.anthropic.com/claude/docs/claude-code-mcp

### 9.2 MCP 服务器仓库

- **Tavily MCP**：https://github.com/tavily-ai/tavily-mcp
- **open-websearch**：https://github.com/Aas-ee/open-webSearch
- **arxiv-mcp-server**：https://github.com/blazickjp/arxiv-mcp-server（2.4k stars）
- **paper-search-mcp**：https://github.com/openags/paper-search-mcp（796 stars）
- **Firecrawl MCP**：https://github.com/mendableai/firecrawl-mcp-server
- **Brave Search MCP**：https://github.com/brave/brave-search-mcp
- **Exa MCP**：https://github.com/exa-labs/exa-mcp-server
- **Semantic Scholar MCP**：https://github.com/JackKuo666/semanticscholar-MCP-Server
- **Scientific-Papers-MCP**：https://github.com/benedict2310/Scientific-Papers-MCP

### 9.3 MCP 目录站

- **mcp.so**：https://mcp.so（最大 MCP 目录）
- **Smithery**：https://smithery.ai（MCP 一键安装）
- **PulseMCP**：https://www.pulsemcp.com（MCP 评测）

---

*v4.0 MCP 配置指南 · 2026-07-30*
