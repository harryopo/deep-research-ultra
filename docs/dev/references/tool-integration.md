# Deep Research — 工具集成指南

## 工具链概览

Deep Research 整合了以下工具，实现多源并行调研：

| 工具 | 用途 | 调用方式 |
|------|------|----------|
| oss-finder | 开源项目搜索 | `python scripts/search.py` |
| crawl4ai | 网页深度阅读 | MCP 工具 |
| agent-reach | 社交媒体搜索 | CLI 命令 |
| WebFetch | 简单网页抓取 | 内置工具 |
| Agent | 子 Agent 并行 | Claude Code Agent |

---

## 1. oss-finder 集成

### 用途
搜索 GitHub/GitLab/Gitee/npm/PyPI 上的开源项目。

### 调用方式

```bash
# 基本搜索
python "${OSS_FINDER_DIR}/scripts/search.py" "react table" --stars ">1000" --limit 10 --format json

# 按创建时间筛选
python "${OSS_FINDER_DIR}/scripts/search.py" "ai agent" --created-after "2025-01-01" --stars ">500" --limit 10

# 跨平台搜索
python "${OSS_FINDER_DIR}/scripts/search.py" "web framework" --platform all --limit 20
```

### 适用场景
- 技术选型：搜索并对比开源工具/框架
- 生态分析：统计 stars/forks/issues 趋势
- 新项目发现：按创建时间筛选新兴项目

---

## 2. crawl4ai MCP 集成

### 用途
深度阅读网页内容，支持 JavaScript 渲染。

### 调用方式

```
使用 MCP 工具：
- crawl4ai_crawl: 抓取单个 URL
- crawl4ai_map: 发现网站结构
```

### 适用场景
- 阅读技术博客/文档
- 抓取基准测试数据
- 提取文章关键内容

---

## 3. agent-reach 集成

### 用途
搜索社交媒体平台的讨论内容。

### 调用方式

```bash
# Twitter 搜索
agent-reach twitter search "python web framework" --limit 10

# Reddit 搜索
agent-reach reddit search "best react state management" --limit 10

# B站搜索
agent-reach bilibili search "Python 教程" --limit 10
```

### 适用场景
- 社区讨论热度分析
- 用户反馈和口碑
- 实际使用案例

---

## 4. 子 Agent 并行策略

### 设计原则

1. **独立性** — 每个子 Agent 负责一个独立子问题，不依赖其他 Agent 的结果
2. **并行性** — 独立子问题必须并行执行，不串行等待
3. **收敛性** — 所有 Agent 完成后，主 Agent 综合分析

### Prompt 结构

```
你是深度调研的子 Agent #{id}，负责调研以下子问题：

**子问题：** {问题描述}
**所属主题：** {调研主题}
**数据源：** {指定的工具}

**任务：**
1. 使用指定工具搜索相关信息
2. 阅读并评估来源
3. 提取关键发现（3-5 条）
4. 标注来源可信度

**输出格式：**
返回结构化的调研结果，包含：
- 关键发现（带来源 URL）
- 矛盾点/待验证信息
- 来源可信度评估
```

### 执行流程

```
主 Agent
  ├─ 拆解子问题 (3-5 个)
  ├─ 并行启动子 Agents
  │   ├─ Agent 1: 子问题 1 + 数据源 A
  │   ├─ Agent 2: 子问题 2 + 数据源 B
  │   ├─ Agent 3: 子问题 3 + 数据源 C
  │   └─ Agent N: ...
  ├─ 收集所有结果
  ├─ 交叉验证 + 矛盾处理
  └─ 生成报告
```

---

## 5. 搜索策略

### 关键词组合

每个子问题使用 2-3 组不同关键词：

```
子问题：FastAPI 的生产环境最佳实践

关键词组合：
1. "FastAPI production best practices 2025"
2. "FastAPI 部署 生产环境"
3. "FastAPI vs Django production"
```

### 来源多样性

| 来源类型 | 目标数量 | 优先级 |
|----------|----------|--------|
| 官方文档 | 1-2 | 高 |
| 技术博客 | 3-5 | 中 |
| GitHub 项目 | 2-3 | 中 |
| 社交讨论 | 3-5 | 低 |
| 学术论文 | 0-2 | 视主题 |

### 交叉验证

同一结论需要至少 2 个独立来源支持：
- ✅ 两个不同博客都提到 FastAPI 性能优于 Django
- ❌ 只有一个来源声称某框架已废弃
