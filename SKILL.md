---
name: deep-research-ultra
version: 3.2.0
description: |
  超级深度调研工具，16 个搜索引擎、中英文自动切换、质量评分、迭代搜索、报告生成。
  当用户说"深度调研"、"deep research"、"帮我研究"、"全面分析"、"调研报告"时调用。
context: fork
agent: general-purpose
allowed-tools: Read Write Bash Glob Grep AskUserQuestion Agent
---

# Deep Research Ultra — 超级深度调研工具 v3.2

**16 个搜索引擎 + 中英文自动切换 + 智能评分 + 迭代搜索。**

---

## 架构说明

### 数据源分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Deep Research Ultra — 16 个搜索引擎                  │
├─────────────────────────────────────────────────────────────────────┤
│  中文引擎（7 个）— 中文查询自动选择                                    │
│  ├── 百度          百度搜索，国内可用                                  │
│  ├── 必应          Bing 中国，国内可用                                 │
│  ├── DuckDuckGo    免费，国内可用                                     │
│  ├── 360           360 搜索，国内可用                                  │
│  ├── 搜狗          搜狗搜索，国内可用                                  │
│  ├── 微信          微信公众号文章搜索                                   │
│  └── 神马          神马搜索，移动端                                    │
├─────────────────────────────────────────────────────────────────────┤
│  国际引擎（6 个）— 英文查询自动选择                                    │
│  ├── DuckDuckGo    免费，隐私保护                                     │
│  ├── Brave         免费，隐私保护                                     │
│  ├── Ecosia        免费，环保搜索引擎                                  │
│  ├── Startpage     免费，Google 结果                                  │
│  ├── Yahoo         免费                                              │
│  └── Qwant         免费，隐私保护                                     │
├─────────────────────────────────────────────────────────────────────┤
│  增强引擎（3 个）— 需要配置                                          │
│  ├── Tavily        AI 搜索引擎，需要 API Key                          │
│  ├── Jina          网页内容提取，需要 VPN                              │
│  └── SearXNG       元搜索引擎，需要自建                               │
├─────────────────────────────────────────────────────────────────────┤
│  开源项目搜索                                                        │
│  ├── GitHub CLI    开源项目搜索                                      │
│  ├── npm           Node.js 包搜索                                    │
│  └── PyPI          Python 包查询                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 整合的开源工具

| 工具 | 来源 | 用途 | 许可证 | 国内可用 | 需要配置 |
|------|------|------|--------|----------|----------|
| **DuckDuckGo** | [ddgs](https://github.com/deedy5/ddgs) | 网页搜索 | MIT | ✅ | 无需 |
| **Bing** | [bing.com](https://www.bing.com) | 网页搜索 | 免费 | ✅ | 无需 |
| **百度** | [baidu.com](https://www.baidu.com) | 网页搜索 | 免费 | ✅ | 无需 |
| **Tavily** | [tavily.com](https://tavily.com) | AI 搜索引擎 | 商业 | ✅ | API Key |
| **Jina Reader** | [jina.ai](https://jina.ai) | 网页内容提取 | 商业 | ❌ 需VPN | API Key（可选） |
| **SearXNG** | [github.com/searxng](https://github.com/searxng/searxng) | 元搜索引擎聚合 | AGPL-3.0 | ✅ | 自建实例 |
| **oss-finder** | 本项目 | 开源项目搜索 | MIT | ✅ | 无需 |

### 为什么选这些工具

1. **DuckDuckGo** — 免费、无需 API Key、国内可用、支持文本/新闻搜索
2. **Bing** — 免费、国内可用、HTML 解析获取结果
3. **百度** — 免费、国内可用、中文搜索结果丰富
4. **Tavily** — 专为 AI Agent 设计，返回结构化结果，免费额度 1000 次/月
5. **Jina Reader** — 极简 API，擅长网页转 Markdown，但需要 VPN
6. **SearXNG** — 完全免费开源，聚合 70+ 搜索引擎，需自建
7. **oss-finder** — 本项目开发，GitHub/npm/PyPI 项目搜索

### 降级策略

```
用户输入调研主题
      │
      ▼
┌─────────────────┐
│  检测网络环境    │  判断是否能访问国际服务
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  检测 API Key   │  检查 Tavily/Jina 配置
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  自动选择可用数据源                                           │
│                                                              │
│  有 VPN + API Key:                                           │
│    DuckDuckGo + Bing + 百度 + Tavily + Jina + oss-finder     │
│                                                              │
│  有 API Key（无 VPN）:                                        │
│    DuckDuckGo + Bing + 百度 + Tavily + oss-finder            │
│                                                              │
│  无 VPN + 无 API Key:                                         │
│    DuckDuckGo + Bing + 百度 + oss-finder（降级方案）           │
└─────────────────────────────────────────────────────────────┘
```

### 数据流

```
用户输入调研主题
      │
      ▼
┌─────────────────┐
│  澄清问题       │  AskUserQuestion 确认目标/深度/维度（可选）
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  并发搜索       │  search.py 调用 16 个引擎，评分排序
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  生成报告       │  Claude 基于搜索结果生成结构化报告
└─────────────────┘
```

---

## 核心原则

> **search.py 负责搜索和评分，Claude 负责澄清和报告。**
>
> **七条铁律：**
> 1. **澄清优先** — 模糊主题必须先问用户，不能自作主张
> 2. **多源并发** — search.py 自动并发搜索 16 个引擎
> 3. **质量评分** — 标题相关 40 + 内容丰富 30 + 权威性 20 + 时效性 10
> 4. **引用可追溯** — 报告中每个关键结论必须附带来源链接
> 5. **诚实标注** — 无法验证的信息标注"待确认"
> 6. **降级透明** — 数据源不可用时明确告知用户，推荐配置方案
> 7. **缓存优先** — 相同查询 1 小时内直接返回缓存

---

## v3.0 增强特性

### 搜索结果缓存

- 缓存目录：`~/.cache/deep-research/`
- TTL：1 小时
- 缓存键：基于查询 + 数据源 + 参数的 MD5 哈希
- 命中时直接返回，不发起网络请求

```bash
# 正常搜索（自动缓存）
python scripts/search.py "Python Web 框架"

# 禁用缓存
python scripts/search.py "Python Web 框架" --no-cache
```

### 结果质量评分

自动评估每个搜索结果的质量（0-100 分）：

| 维度 | 分值 | 评分标准 |
|------|------|----------|
| 标题相关性 | 40 分 | 查询词与标题的重叠度 |
| 内容丰富度 | 30 分 | 摘要长度（>500 字满分） |
| 来源权威性 | 20 分 | GitHub/知乎/CSDN/StackOverflow 等 |
| 时效性 | 10 分 | 2025-2026 年满分 |

```bash
# 只返回 50 分以上结果
python scripts/search.py "React" --min-score 50
```

### 迭代搜索

结果不足时，自动生成关键词变体重搜：

- 中文 → 英文映射（框架 → framework，最佳实践 → best practices）
- 添加年份变体（2025）
- 添加"最佳"变体

```bash
# 启用迭代搜索
python scripts/search.py "K8s 部署" --iterative
```

### 报告生成

自动生成结构化研究报告：

```bash
# 生成研究报告
python scripts/search.py "Python Web 框架" --format report

# 报告包含：执行摘要、来源分析、质量分布、建议
```

### CSV 导出

```bash
# 导出为 CSV（Excel 可直接打开）
python scripts/search.py "React" --format csv

# 列：序号, 标题, URL, 摘要, 质量分, 来源, 发布日期
```

### 代理支持

```bash
# 使用 HTTP 代理
python scripts/search.py "Google" --proxy http://127.0.0.1:7890
```

### 搜索历史

```bash
# 查看最近 7 天搜索历史
python scripts/search.py --history

# 查看最近 30 天
python scripts/search.py --history --history-days 30
```

### 反馈系统

用户评分改进后续搜索：

```bash
# 提交反馈
python scripts/search.py --feedback "Python Web 框架" --rating 5

# 历史反馈自动关联相似查询
python scripts/search.py "Python Web 框架"  # 显示: 历史反馈: 此类查询评分 5/5
```

### 关键词多样性

子问题自动生成 2-3 组不同关键词，提高覆盖面。

---

## 工作流程

### 环境检测（自动）

**首次使用时自动执行：**

```bash
python "${SKILL_DIR}/scripts/search.py" --check
```

**输出示例：**
```
[检查] 数据源可用性...

[网络环境]
   VPN: [无]
   Google: [不可达]
   Jina: [不可达]
   Tavily: [不可达]

[数据源状态]
   duckduckgo: [可用]
   tavily: [不可用]
   jina: [不可用]
   searxng: [不可用]
```

**根据检测结果推荐配置：**

| 场景 | 推荐操作 |
|------|----------|
| 无 VPN + 无 API Key | 使用 DuckDuckGo + Bing + 百度（默认）|
| 无 VPN + 有 Tavily Key | 使用 DuckDuckGo + Bing + 百度 + Tavily |
| 有 VPN + 无 API Key | 使用 DuckDuckGo + Bing + 百度 + Jina |
| 有 VPN + 有 API Key | 使用全部数据源 |

### 智能引擎选择（Claude Agent 决策）

**你来决定用哪些引擎，不要让 search.py 自己选。**

#### 可用引擎列表

```bash
# 查看所有可用引擎
python "${SKILL_DIR}/scripts/search.py" --list
```

| 引擎 | 擅长领域 | 需要配置 |
|------|----------|----------|
| **baidu** | 中文内容、国内新闻、百度百科 | 无需 |
| **bing** | 通用搜索、技术文档、英文内容 | 无需 |
| **duckduckgo** | 隐私搜索、英文技术内容 | 无需 |
| **so** (360) | 中文内容、国内新闻 | 无需 |
| **sogou** | 中文内容、搜狗百科 | 无需 |
| **wechat** | 微信公众号文章 | 无需 |
| **sm** (神马) | 移动端中文内容 | 无需 |
| **brave** | 英文技术内容、隐私搜索 | 无需 |
| **ecosia** | 英文内容、环保搜索 | 无需 |
| **startpage** | Google 结果、隐私保护 | 无需 |
| **tavily** | AI 搜索、结构化结果 | API Key |
| **jina** | 网页内容提取、全文阅读 | VPN |
| **searxng** | 元搜索引擎、聚合 70+ 引擎 | 自建实例 |

#### 决策示例

**中文技术问题**（如 "Python Web 框架对比"）：
```
--sources baidu,bing,duckduckgo,wechat
```
理由：百度（中文内容）+ Bing（技术文档）+ DuckDuckGo（英文对比）+ 微信（中文技术文章）

**英文学术问题**（如 "latest LLM research papers"）：
```
--sources duckduckgo,brave,ecosia,startpage
```
理由：多个英文引擎覆盖，隐私搜索避免信息茧房

**开源项目搜索**（如 "React table component"）：
```
# 先用 oss-finder 搜项目
python "${SKILL_DIR}/../oss-finder/scripts/search.py" "react table" --stars ">1000"

# 再用搜索引擎找评测文章
python "${SKILL_DIR}/scripts/search.py" "react table comparison 2025" --sources bing,duckduckgo
```

**中文新闻/时事**（如 "2025 年 AI 行业趋势"）：
```
--sources baidu,so,sogou,wechat,bing
```
理由：中文引擎全覆盖，确保信息全面

**深度技术调研**（如 "Kubernetes 生产环境最佳实践"）：
```
# 第一轮：广泛搜索
python "${SKILL_DIR}/scripts/search.py" "Kubernetes production best practices 2025" --sources duckduckgo,bing,brave

# 第二轮：中文经验
python "${SKILL_DIR}/scripts/search.py" "Kubernetes 生产环境 最佳实践" --sources baidu,wechat

# 第三轮：GitHub 实际配置
python "${SKILL_DIR}/../oss-finder/scripts/search.py" "kubernetes production config" --stars ">500"
```

### 并发搜索

#### 搜索命令

```bash
# 指定引擎搜索（推荐，你来选引擎）
python "${SKILL_DIR}/scripts/search.py" "关键词" --sources baidu,bing,duckduckgo

# 搜索所有可用引擎（适合深度调研）
python "${SKILL_DIR}/scripts/search.py" "关键词" --all

# 深度阅读网页
python "${SKILL_DIR}/scripts/search.py" --read "https://example.com"

# 指定输出格式
python "${SKILL_DIR}/scripts/search.py" "关键词" --sources bing --format report

# 列出所有可用引擎
python "${SKILL_DIR}/scripts/search.py" --list
```

#### 子 Agent 调度

**根据调研深度决定子 Agent 数量：**

| 深度 | 子 Agent 数 | 策略 |
|------|-------------|------|
| 快速 | 1-2 个 | 直接搜索，不拆分 |
| 标准 | 3-4 个 | 按语言/主题拆分 |
| 深度 | 5+ 个 | 多维度并行，交叉验证 |

**子 Agent Prompt 模板：**

```
你是深度调研的子 Agent，负责调研以下子问题：

**子问题：** {问题描述}
**所属主题：** {调研主题}
**指定引擎：** {你根据问题选择的引擎列表}

**任务：**
1. 使用指定引擎搜索
2. 阅读并评估来源
3. 提取关键发现（3-5 条）
4. 标注来源可信度

**搜索命令：**
python "${SKILL_DIR}/scripts/search.py" "{你生成的关键词}" --sources {你选择的引擎}

**输出：**
- 关键发现（带来源 URL）
- 矛盾点
- 来源可信度
```

### 生成报告

报告结构：

```markdown
# {调研主题}

**调研时间：** YYYY-MM-DD
**调研深度：** 快速/标准/深度
**数据源：** DuckDuckGo, Tavily, oss-finder, ...

---

## 执行摘要
[核心结论]

## 1. {子问题 1}
[分析 + 引用]

## 2. {子问题 2}
[分析 + 引用]

## N. 结论与建议

## 来源列表
| # | 来源 | URL | 可信度 |
|---|------|-----|--------|
```

---

## 搜索引擎配置

| 引擎 | 类型 | 配置 | 国内可用 |
|------|------|------|----------|
| **DuckDuckGo** | 免费 | `pip install ddgs` | ✅ |
| **Bing** | 免费 | 无需配置 | ✅ |
| **百度** | 免费 | 无需配置 | ✅ |
| **360/搜狗/微信/神马** | 免费 | 无需配置 | ✅ |
| **Brave/Ecosia/Startpage** | 免费 | 无需配置 | ❌ |
| **Tavily** | API Key | `export TAVILY_API_KEY=xxx` | ✅ |
| **Jina** | VPN | `export JINA_API_KEY=xxx` | ❌ |
| **SearXNG** | 自建 | `docker run searxng/searxng` | ✅ |

---

## 使用示例

```bash
# 列出可用引擎
python scripts/search.py --list

# 指定引擎搜索（Claude 智能选择）
python scripts/search.py "Python Web 框架" --sources baidu,bing,duckduckgo

# 搜索所有可用引擎
python scripts/search.py "AI 趋势" --all

# 深度阅读网页
python scripts/search.py --read "https://example.com"

# 生成报告
python scripts/search.py "K8s 最佳实践" --sources bing --format report
```

---

## 禁止行为

- ❌ **禁止跳过澄清** — 模糊主题必须先确认
- ❌ **禁止无来源结论** — 每个结论必须有出处
- ❌ **禁止静默降级** — 数据源不可用时必须告知用户

---

## 参考资料

- DuckDuckGo: https://github.com/deedy5/ddgs (MIT)
- Tavily API: https://docs.tavily.com
- Jina Reader: https://jina.ai/reader
- SearXNG: https://docs.searxng.org
