# project_memory.md — deep-research-ultra v5.2

> 本项目记忆文件，记录开发决策、踩坑和经验，方便跨会话恢复。

---

## 版本历史

- **v5.2**（2026-08-08）：GitHub 深度搜索 + 国内内容源 + 推荐度评分系统
- **v5.1**：论文全文下载 + 引用图谱 + Crawl4AI 浏览器自动化 + curl_cffi TLS 指纹伪装
- **v5.0**：智能路由（三级级联）+ 四层数据源架构 + 96 项测试

---

## 核心架构

### 四层数据源架构

1. **MCP 层**：github、duckduckgo、google、semantic-scholar 等
2. **学术直连层**：arXiv API、Unpaywall API、Semantic Scholar API
3. **Skill 层**：内置的 30 个引擎（github_search、hackernews 等）
4. **降级层**：fallback、curl_cffi TLS 伪装

### 智能路由（三级级联）

- **L1 规则层**：关键词/正则匹配，60-70% 查询在此解决（<1ms）
- **L2 语义层**：向量相似度匹配，20-25% 查询（20-50ms）
- **L3 LLM 层**：LLM 判断，5-10% 复杂查询（200-800ms）

### 9 类查询意图

学术论文、开源项目、技术方案、竞品分析、技术选型、前沿趋势、最佳实践、案例研究、行业报告

---

## v5.2 新增功能

### 1. GitHub 深度搜索（`scripts/engines/github_deep_search.py`）

- **分桶搜索**：star 分桶（0-100/100-500/500-1000/1000+），每桶独立搜索
- **低星项目挖掘**：优先挖掘 0-100 star 潜力项目
- **依赖图反向挖掘**：通过依赖关系发现关联项目
- **awesome 列表挖掘**：从 awesome-xxx 列表发现项目
- **GitHub Code Search API**：代码级搜索

### 2. 国内内容源（`scripts/engines/cn_sources.py`）

- **百度搜索 SERP**：国内搜索主力，含知乎/CSDN/掘金等
- **搜狗微信搜索**：微信公众号文章搜索
- **搜狗知乎搜索**：知乎问答搜索
- **百度学术**：国内学术论文搜索

### 3. 推荐度评分系统（`scripts/recommend.py`）

- **GitHub 8 维评分**：stars, forks, issues, PRs, commits, contributors, license, freshness
- **论文 5 维评分**：citations, journal_impact, recency, relevance, OA_status
- **分组排序**：按查询类型分组，组内排序
- **雷达图可视化**：SVG 雷达图展示多维度评分

---

## 部署流程（三步部署）

### 1. 全局部署

```powershell
# 从 projects/deep-research-ultra 目录
Copy-Item -Path "." -Destination "C:\Users\Lenovo\.agents\skills\deep-research-ultra" -Recurse -Force
Copy-Item -Path "." -Destination "C:\Users\Lenovo\.trae\skills\deep-research-ultra" -Recurse -Force
```

**注意**：Windows 沙箱环境对全局目录写入有权限限制，新建文件可以，覆盖已存在文件可能被阻止。

### 2. GitHub 推送

```bash
cd projects/deep-research-ultra
git remote set-url origin git@github.com:harryopo/deep-research-ultra.git
git add .
git commit -m "feat: deep-research-ultra v5.2 release"
git push origin main
```

### 3. GitHub Pages 部署

```bash
# Clone 主 Pages 仓库
git clone https://ghfast.top/https://github.com/harryopo/harryopo.github.io.git tmp-pages
cd tmp-pages

# 复制 deep-research-ultra 的 index.html
copy ..\projects\deep-research-ultra\index.html deep-research-ultra\index.html

# 更新导航（如有其他页面需同步）

# 提交推送
git add deep-research-ultra/index.html
git commit -m "deploy(deep-research-ultra): update webpage to v5.2"
git push
```

**Pages 地址**：`https://harryopo.github.io/deep-research-ultra/`

---

## 关键文件说明

| 文件 | 用途 |
|------|------|
| `SKILL.md` | Skill 主入口：触发条件、使用说明、约束 |
| `scripts/engines/*.py` | 各搜索引擎实现 |
| `scripts/github_deep_search.py` | GitHub 深度搜索（v5.2） |
| `scripts/cn_sources.py` | 国内内容源（v5.2） |
| `scripts/recommend.py` | 推荐度评分系统（v5.2） |
| `scripts/router.py` | 智能路由（v5.0） |
| `scripts/plan.py` | 问题树状态机（v5.1） |
| `scripts/reflect.py` | 多信号反思（v5.1） |
| `scripts/report.py` | 报告生成（含雷达图） |
| `evals/evals.json` | 测试用例（96 项） |
| `index.html` | 宣传网页（部署到 GitHub Pages） |

---

## 踩坑记录

### 1. Windows 沙箱权限限制

- **问题**：`Copy-Item` 覆盖已存在的文件被路径安全策略阻止
- **解决**：单独复制新文件（不存在于目标目录的）可以成功；或用 `robocopy` 替代

### 2. SSH 推送不稳定

- **问题**：国内网络环境 SSH 偶有不稳定
- **解决**：优先使用 SSH；若超时，临时切换到 HTTPS + `pushurl` 方案

### 3. GitHub Pages 子路径冲突

- **问题**：若存在同名 Project Pages 仓库，会优先于 User Pages
- **解决**：确认无冲突；在 `harryopo.github.io` 主仓库根目录放 `deep-research-ultra/` 子目录

### 4. 网页内容未更新

- **问题**：Pages 部署后网页内容仍显示旧版本
- **原因**：忘记将新版 `index.html` 复制到 Pages 仓库并 push
- **解决**：每次更新网页后，记得同步到 `harryopo.github.io/deep-research-ultra/index.html` 并 push

---

## 测试覆盖

- **96 项测试**：覆盖 30 个引擎 + 路由 + 评分 + 报告
- **运行方式**：`pytest projects/deep-research-ultra/ -v`
- **测试文件**：`evals/evals.json` + `scripts/tests/`

---

## 下一步计划

- [ ] 增加更多国内内容源（豆瓣、微博、头条等）
- [ ] GitHub 深度搜索增加 PR/MR 活跃度分析
- [ ] 推荐度评分增加用户自定义权重
- [ ] 报告生成增加 PDF 导出
- [ ] 增加缓存机制（1 小时 TTL）
