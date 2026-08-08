# Deep Research Ultra v5.0 优化方案

> 基于 5 份调研报告制定：大厂方法论 / 开源项目 / 科研论文检索 / 反爬虫技术 / 智能路由
> 日期：2026-08-08

---

## 一、核心目标

**智能分配**：根据查询意图自动选择数据源
- 调研知识 → 加载科研论文检索（arXiv/OpenAlex/Semantic Scholar/PubMed）
- 调研开源 → 偏向 GitHub（oss-finder + GitHub MCP + Tavily）
- 理论 + 联网 + 实际结合

---

## 二、P0 改进（核心需求）

### 2.1 智能路由模块（router.py）— 新建

**架构**：三级级联（规则 → 语义 → LLM）

```
查询输入
  ↓
[规则层] 关键词/正则匹配 → 60-70% 查询在此解决（<1ms）
  ↓ 置信度 < 0.8
[语义层] 向量相似度匹配 → 20-25% 查询（20-50ms，可选）
  ↓ 置信度 < 0.7
[LLM 层] LLM 判断查询类型 → 5-10% 复杂查询（200-800ms，可选）
  ↓
RoutingDecision → 动态引擎链
```

**9 类查询-数据源匹配矩阵**：

| 查询类型 | 关键词特征 | 推荐引擎链 |
|---------|----------|-----------|
| 学术论文 | paper/research/论文/研究 | arxiv, paper-search, openalex, semantic-scholar, pubmed |
| 开源项目 | github/open source/开源/库 | oss-finder, tavily, open-websearch |
| 社区口碑 | reddit/评价/口碑/对比 | agent-reach, last30days, tavily |
| 技术文档 | docs/文档/api/教程 | context7, defuddle, firecrawl |
| 时效新闻 | 最新/今天/近期/2025 | last30days, tavily, websearch |
| 通用搜索 | （默认） | tavily, open-websearch, websearch |
| 定义解释 | 什么是/what is/定义 | tavily, websearch, defuddle |
| 操作指南 | how to/怎么做/教程 | tavily, context7, defuddle |
| 对比分析 | vs/对比/比较 | tavily, agent-reach, arxiv |

**断路器降级**：主源失败自动切换备用，CLOSED → OPEN → HALF_OPEN 状态机

### 2.2 反爬虫升级（fallback.py）— 修改

**核心改动**：`_http_get()` 集成 curl_cffi

```python
def _http_get(url, headers=None, timeout=15, max_retries=3, proxy=None,
              impersonate="chrome124"):  # 新增 TLS 指纹伪装
    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, headers=headers, timeout=timeout,
                              proxies={"http": proxy, "https": proxy} if proxy else None,
                              impersonate=impersonate)
        return r.content
    except ImportError:
        # 降级到原 urllib 实现（保留兼容）
        ...
```

**三级分层爬取策略**：
1. curl_cffi（轻量 TLS 伪装，90% 场景）
2. Crawl4AI Docker（JS 渲染 + 反检测，需 Docker）
3. Camoufox（C++ 指纹注入，强反爬兜底）

### 2.3 学术引擎扩展（academic_engines.py）— 新建

**3 个直连引擎**（无需 MCP，直接 REST API）：

| 引擎 | 数据量 | API Key | 功能 |
|------|--------|---------|------|
| OpenAlexEngine | 474M+ 作品 | 无需 | 元数据 + 引用分析 + 概念 |
| SemanticScholarEngine | 200M+ 论文 | 可选 | AI 引用上下文 + TLDR + influential citations |
| PubmedEngine | 36M+ 医学 | 无需 | E-utilities + MeSH 词表 |

**优势**：不依赖 MCP 配置，直连免费 API，国内可用

---

## 三、P1 改进（方法论升级）

### 3.1 透明研究计划（Gemini 式）
- Phase 1 生成 MECE 问题树后，展示给用户审阅
- 用户可修改/增删子问题
- 确认后再执行搜索

### 3.2 即时反思（Kimi 式）
- Phase 4 增强反思：重新阅读自身报告
- 自审逻辑一致性、证据充分性、矛盾点、遗漏维度
- 发现问题反馈到执行阶段定向补充

### 3.3 问题链可视化（秘塔式）
- 每个推理节点记录：子问题 / 搜索查询 / 证据 / 来源 / 置信度 / 状态
- 状态标注：✅已验证 / ⚠️待补充 / ❌矛盾
- 输出可追溯研究日志

### 3.4 多 LLM 分工配置（llm_config.py）— 新建

4 角色分工：
- **Summarization**：快速摘要（用小模型，如 Haiku）
- **Research**：研究分析（用强模型，如 Sonnet/Opus）
- **Compression**：上下文压缩（用小模型）
- **Final Report**：最终报告（用强模型）

多 Provider 路由：OpenAI / DeepSeek / Kimi / OpenRouter / vLLM

---

## 四、P2 改进（高级特性）

### 4.1 递归深度探索（dzhng/deep-research 式）
- `--breadth N --depth N` 参数控制递归
- 每层生成子查询，递归搜索
- breadth=3, depth=2 = 最多 3×3=9 次搜索

### 4.2 多视角提问（STORM 式）
- 不直接让 LLM 提问
- 先发现多视角（如：用户/开发者/安全/性能视角）
- 模拟 writer-expert 对话生成问题

### 4.3 动态思维导图
- 用层级思维导图组织信息
- 降低长对话认知负荷

---

## 五、实施计划

### 阶段 1：P0 核心改进
1. 新建 `scripts/router.py` — 智能路由模块
2. 修改 `scripts/engines/fallback.py` — curl_cffi 集成
3. 新建 `scripts/engines/academic_engines.py` — 学术直连引擎
4. 更新 `scripts/engines/__init__.py` — 导出新引擎
5. 更新 `scripts/research.py` — 集成路由
6. 更新 `scripts/requirements.txt` — 添加 curl_cffi

### 阶段 2：P1 方法论升级
7. 修改 `scripts/plan.py` — 透明研究计划
8. 修改 `scripts/reflect.py` — 即时反思
9. 新建 `scripts/llm_config.py` — 多 LLM 分工

### 阶段 3：文档与测试
10. 更新 `SKILL.md` — v5.0 文档
11. 更新 `scripts/tests/test_core.py` — 新模块测试
12. 更新 `references/` — 归档调研报告

---

## 六、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| scripts/router.py | 新建 | 智能路由模块（三级级联） |
| scripts/engines/academic_engines.py | 新建 | 学术直连引擎（OpenAlex/S2/PubMed） |
| scripts/engines/fallback.py | 修改 | curl_cffi 集成 |
| scripts/engines/__init__.py | 修改 | 导出新引擎 |
| scripts/research.py | 修改 | 集成路由 + 新引擎注册 |
| scripts/requirements.txt | 修改 | 添加 curl_cffi |
| scripts/llm_config.py | 新建 | 多 LLM 分工配置（P1） |
| SKILL.md | 修改 | v5.0 文档 |
| scripts/tests/test_core.py | 修改 | 新模块测试 |

---

## 七、调研报告索引

1. [大厂深度研究方法论调研报告.md](大厂深度研究方法论调研报告.md) — 7 家厂商方法论分析
2. [开源深度研究项目调研报告.md](开源深度研究项目调研报告.md) — 10 个开源项目评估
3. [科研论文检索方案调研报告.md](科研论文检索方案调研报告.md) — 9 MCP + 8 API + 6 工具
4. [anti-bot-research-2026.md](anti-bot-research-2026.md) — 20+ 反爬虫方案
5. [intelligent-routing-research.md](intelligent-routing-research.md) — 路由策略与架构设计
