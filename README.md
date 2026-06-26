# Deep Research Ultra — 超级深度调研工具 v3.2

> **16 个搜索引擎 + Claude 智能选引擎 + 质量评分 + 迭代搜索 + 报告生成**

🚀 **[点击查看教程网页](https://harryopo.github.io/deep-research-ultra/)**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-orange.svg)](https://claude.ai/code)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-教程网页-green.svg)](https://harryopo.github.io/deep-research-ultra/)

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🔍 **16 个搜索引擎** | 中文 7 个 + 国际 6 个 + 增强 3 个 |
| 🧠 **Claude 智能选引擎** | 根据查询语言/主题自动选择最佳引擎组合 |
| 📊 **质量评分** | 标题相关性(40) + 内容丰富度(30) + 来源权威性(20) + 时效性(10) |
| 🔄 **迭代搜索** | 结果不足时自动生成关键词变体重搜 |
| 📝 **报告生成** | 自动生成结构化研究报告 |
| 💾 **结果缓存** | 1 小时 TTL，避免重复请求 |
| 📤 **CSV 导出** | Excel 可直接打开 |
| 🌐 **代理支持** | HTTP/HTTPS 代理 |
| 📜 **搜索历史** | 查看最近 7/30 天记录 |
| 💬 **反馈系统** | 用户评分改进后续搜索 |

---

## 📦 安装

### 前置条件

- Python 3.8+
- Claude Code（用于调用 Skill）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/deep-research-ultra.git
cd deep-research-ultra

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 检查数据源可用性
python scripts/search.py --check
```

### 依赖说明

| 依赖 | 用途 | 必需 |
|------|------|------|
| `ddgs` | DuckDuckGo 搜索 | ✅ 是 |
| `requests` | HTTP 请求 | ✅ 是 |
| `beautifulsoup4` | HTML 解析 | ✅ 是 |

---

## ⚙️ 配置

### 配置层级

```
┌─────────────────────────────────────────────────────────────────┐
│                    配置层级                                        │
├─────────────────────────────────────────────────────────────────┤
│  层级 1：免费层（无需配置）                                        │
│  ├── DuckDuckGo — 国内可用，无需 API Key                          │
│  ├── Bing — 国内可用，无需 API Key                                │
│  ├── 百度 — 国内可用，无需 API Key                                │
│  ├── 360/搜狗/微信/神马 — 国内可用                                │
│  └── GitHub CLI/npm/PyPI — 开源项目搜索                           │
├─────────────────────────────────────────────────────────────────┤
│  层级 2：增强层（需要 API Key）                                    │
│  ├── Tavily — AI 搜索引擎，免费 1000 次/月                        │
│  └── Jina Reader — 网页内容提取，需要 VPN                         │
├─────────────────────────────────────────────────────────────────┤
│  层级 3：自建层（需要部署）                                        │
│  └── SearXNG — 元搜索引擎，Docker 部署                            │
└─────────────────────────────────────────────────────────────────┘
```

### 环境变量配置

创建 `.env` 文件或设置系统环境变量：

```bash
# ========== 增强层配置（可选）==========

# Tavily AI 搜索（推荐，免费 1000 次/月）
# 获取地址：https://app.tavily.com
export TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxx

# Jina Reader 网页内容提取（需要 VPN）
# 获取地址：https://jina.ai
export JINA_API_KEY=jina_xxxxxxxxxxxxxxxxxxxxx

# ========== 代理配置（可选）==========

# HTTP 代理（用于访问国际服务）
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890

# ========== SearXNG 自建配置（可选）==========

# SearXNG 实例地址
export SEARXNG_URL=http://localhost:8080
```

### VPN 推荐配置

> **💡 提示：** 开启 VPN 可解锁更多搜索引擎（Jina、Brave、Ecosia、Startpage）

| VPN 工具 | 推荐端口 | 说明 |
|----------|----------|------|
| **Clash** | 7890 | 推荐，支持 HTTP/SOCKS5 |
| **V2Ray** | 10809 | 支持 HTTP 代理 |
| **Shadowsocks** | 1080 | SOCKS5 代理 |

```bash
# Clash 默认配置
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890

# 或使用代理参数
python scripts/search.py "query" --proxy http://127.0.0.1:7890
```

---

## 🚀 使用方法

### 作为 Claude Code Skill 使用（推荐）

```bash
# 在 Claude Code 中调用
/deep-research 调研一下 2025 年最值得学习的 Python Web 框架

# 或使用触发词
帮我深度研究一下 Kubernetes 生产环境最佳实践
```

### 命令行使用

```bash
# 列出所有可用引擎
python scripts/search.py --list

# 指定引擎搜索（推荐）
python scripts/search.py "Python Web 框架" --sources baidu,bing,duckduckgo

# 搜索所有可用引擎
python scripts/search.py "AI 技术趋势" --all

# 生成研究报告
python scripts/search.py "K8s 最佳实践" --format report

# 导出 CSV
python scripts/search.py "React" --format csv

# 只返回高质量结果（50 分以上）
python scripts/search.py "React" --min-score 50

# 迭代搜索（冷门话题）
python scripts/search.py "K8s 部署" --iterative

# 使用代理
python scripts/search.py "Google" --proxy http://127.0.0.1:7890

# 查看搜索历史
python scripts/search.py --history

# 提交反馈
python scripts/search.py --feedback "Python Web 框架" --rating 5
```

### 搜索引擎选择指南

| 场景 | 推荐引擎 | 命令示例 |
|------|----------|----------|
| **中文技术问题** | baidu,bing,duckduckgo,wechat | `--sources baidu,bing,duckduckgo,wechat` |
| **英文学术问题** | duckduckgo,brave,ecosia,startpage | `--sources duckduckgo,brave,ecosia,startpage` |
| **开源项目搜索** | github + bing | 先用 oss-finder，再用搜索引擎 |
| **中文新闻/时事** | baidu,so,sogou,wechat,bing | `--sources baidu,so,sogou,wechat,bing` |
| **深度技术调研** | 多轮搜索 | 第一轮英文，第二轮中文，第三轮 GitHub |

---

## 📊 输出格式

### JSON 格式（默认）

```json
{
  "query": "Python Web 框架",
  "sources": ["duckduckgo", "bing", "baidu"],
  "results": [
    {
      "title": "FastAPI - Web framework",
      "url": "https://fastapi.tiangolo.com",
      "snippet": "FastAPI framework, high performance...",
      "source": "duckduckgo",
      "score": 85
    }
  ],
  "total": 10,
  "cached": false
}
```

### 报告格式

```bash
python scripts/search.py "AI agent" --format report
```

输出：
```
# AI Agent 调研报告

**调研时间：** 2026-06-26
**数据源：** DuckDuckGo, Bing, 百度

## 执行摘要
[核心结论]

## 来源分析
| 来源 | 数量 | 平均质量分 |
|------|------|-----------|
| DuckDuckGo | 5 | 72 |
| Bing | 3 | 68 |

## 建议
[基于搜索结果的建议]
```

### CSV 格式

```bash
python scripts/search.py "React" --format csv
```

列：`序号, 标题, URL, 摘要, 质量分, 来源, 发布日期`

---

## 🔧 高级功能

### 搜索结果缓存

- 缓存目录：`~/.cache/deep-research/`
- TTL：1 小时
- 命中时直接返回，不发起网络请求

```bash
# 禁用缓存
python scripts/search.py "query" --no-cache
```

### 结果质量评分

自动评估每个搜索结果（0-100 分）：

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
python scripts/search.py "K8s 部署" --iterative
```

---

## 📁 项目结构

```
deep-research-ultra/
├── SKILL.md              # Claude Code Skill 定义
├── README.md             # 本文件
├── requirements.txt      # Python 依赖
├── .gitignore            # Git 忽略规则
├── LICENSE               # MIT 许可证
├── scripts/
│   └── search.py         # 核心搜索脚本（75KB）
├── evals/
│   └── evals.json        # 测试用例
├── references/
│   └── *.md              # 参考文档
└── research/
    └── *.md              # 调研报告输出
```

---

## 🆚 与竞品对比

| 特性 | Deep Research Ultra | Perplexity | Phind |
|------|---------------------|------------|-------|
| **搜索引擎数量** | 16 个 | 1 个 | 1 个 |
| **中文优化** | ✅ 7 个中文引擎 | ⚠️ 有限 | ⚠️ 有限 |
| **免费使用** | ✅ 完全免费 | ❌ 付费 | ⚠️ 有限 |
| **Claude Code 集成** | ✅ 原生 Skill | ❌ | ❌ |
| **质量评分** | ✅ 0-100 分 | ❌ | ❌ |
| **迭代搜索** | ✅ 自动变体 | ❌ | ❌ |
| **报告生成** | ✅ 结构化报告 | ✅ | ✅ |
| **代理支持** | ✅ HTTP/HTTPS | ❌ | ❌ |
| **搜索历史** | ✅ 7/30 天 | ❌ | ❌ |

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

### 贡献指南

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'Add amazing feature'`
4. 推送分支：`git push origin feature/amazing-feature`
5. 提交 Pull Request

### 添加新搜索引擎

```python
# 在 scripts/search.py 中添加新引擎
class NewEngine:
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        # 实现搜索逻辑
        pass
```

---

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE)。

### 整合的开源工具

| 工具 | 许可证 | 来源 |
|------|--------|------|
| DuckDuckGo (ddgs) | MIT | https://github.com/deedy5/ddgs |
| SearXNG | AGPL-3.0 | https://github.com/searxng/searxng |
| oss-finder | MIT | 本项目 |

### 商业服务（有免费额度）

- Tavily: https://tavily.com（免费 1000 次/月）
- Jina: https://jina.ai（免费 20 RPM）

---

## 🔗 相关项目

- **[oss-finder](https://github.com/YOUR_USERNAME/oss-finder)** — 开源项目搜索工具
- **[skill-workspace](https://github.com/YOUR_USERNAME/skill-workspace)** — Skill 开发工作台

---

## 📞 支持

- 🐛 [提交 Bug](https://github.com/YOUR_USERNAME/deep-research-ultra/issues)
- 💡 [功能建议](https://github.com/YOUR_USERNAME/deep-research-ultra/issues)
- 📖 [文档](https://github.com/YOUR_USERNAME/deep-research-ultra/wiki)

---

## 🙏 致谢

感谢以下开源项目：

- [DuckDuckGo (ddgs)](https://github.com/deedy5/ddgs) — 免费搜索 API
- [SearXNG](https://github.com/searxng/searxng) — 元搜索引擎
- [Tavily](https://tavily.com) — AI 搜索引擎
- [Jina](https://jina.ai) — 网页内容提取

---

**⭐ 如果这个项目对你有帮助，请给个 Star！**
