# v6.0 调研笔记 — 深度调研方法论与开源方案（2026-09-18）

> 本文档归档 deep-research-ultra v5.2 → v6.0 升级前的联网调研结论：
> 12 个前沿模式 + Top 12 开源项目 + 8 项能力缺口映射。作为 v6.0 设计依据。

---

## 一、12 个前沿深度调研模式

| # | 模式 | 出处/来源 | 核心机制 | v6.0 落地 |
|---|------|----------|---------|-----------|
| 1 | Orchestrator-Worker | Anthropic 工程博客 | Lead 总管 + 并行 spawn 子 Agent，独立上下文各自检索，Lead 综合 | Phase 2.5 子 Agent 并行编排 |
| 2 | 独立上下文 + 记忆落盘 | Anthropic | 子 Agent 输出写文件系统、绕过主协调者，防长上下文丢失 | ledger.py 结果落盘 |
| 3 | 可编辑计划/协作规划 | Gemini Deep Research | 先生成计划让用户增删步骤再执行 | Phase 1.5 计划确认门 |
| 4 | 迭代检索-知识缺口识别-再搜 | Gemini 3 Pro / Perplexity | 检索→读→识别 gap→再搜，直至充分 | 反思循环 + 证据充分性停止 |
| 5 | 多视角专家提问（STORM） | Stanford NAACL 2024（arxiv 2402.14207） | 5 种 persona 各自提问，条理性 +25% | plan.py 多视角注入 + panel.py |
| 6 | 同行评审/红蓝对抗收敛 | STORM step4 + RedDebate（arxiv 2506.11083） | 置信度 1-10、最弱论点、偏置、缺失视角 | Phase 3.5 专家团评审闭环 |
| 7 | 分节审查-修订闭环 | GPT Researcher（LangGraph） | Editor 定大纲→每节 Researcher→Reviewer→Revisor→Writer | Phase 3.5 章节写-审-修 |
| 8 | 独立 CitationAgent | Anthropic | 检索内容与引文分离，专设代理定位引用 | validate_report 引用一致性校验 |
| 9 | LLM-as-Judge 端状态评测 | Anthropic | 按最终状态打 0-1 分 + pass/fail | validate_report 校验门 |
| 10 | 树搜索/MCTS 规划 | LATS ICML2024（arxiv 2310.04406） | MCTS+ReAct+自反思+LM 值函数 | （v6.0 未落地，留待 v6.1） |
| 11 | 证据充分性终止条件 | Salesforce EDR（arxiv 2604.24978） | outline 反思→依赖引导→证据充分性判据再停，专治过早停止 | reflect.py evidence_sufficiency |
| 12 | 双层模型协同 + 规模缩放 | 秘塔 / Anthropic | 小模型拆步 + 大模型检索整合；按难度缩子 Agent 数 | effort 分级 + breadth 旋钮 |

### 必采纳（已落地 v6.0）
1. **子研究并行 + 独立上下文 + 结果落盘**（模式 1+2）→ Phase 2.5 + ledger.py
2. **分节"写-审-修"闭环**（模式 7）→ Phase 3.5
3. **证据充分性停止 + 独立引用核对**（模式 11+8）→ reflect.py + validate_report.py
4. **计划确认/主动澄清门**（模式 3）→ Phase 1.5
5. **按需 RAM 的红蓝/多视角批判**（模式 5+6）→ panel.py + effort 门控

---

## 二、Top 12 开源项目 / SKill 借鉴

| 项目 | Star | 架构要点 | 借鉴点 |
|------|------|---------|--------|
| GPT Researcher | ★29k | Planner→Executor→Publisher，recursive deep 模式 | reviewer-revisor 流水线 |
| dzhng/deep-research | ★19k | 500 行递归：clarify→并行SERP→learnings→recurse | depth/breadth 显式旋钮 |
| STORM / Co-STORM | ★9k | 多视角问题生成→模拟专家对话→逐节成文 | 视角引导提问 |
| OpenManus | ★40k | MetaGPT 团队，四层架构，ReAct+Planning | 分层解耦 |
| OWL（camel-ai） | ★20k | GAIA≈69%，lazy browser use | 廉价工具优先（浏览器最贵） |
| Auto-Deep-Research（HKUDS） | ★10k | 多代理 + 协调器，自主/交互两模式 | 中央协调器拆分子任务 |
| LangChain OpenDeepResearcher | ★6k | LangGraph，自带多架构自评测 | 自建脚手架并回归跑分 |
| local-deep-researcher | ★3-4k | 全本地 Ollama/LM Studio | token 预算硬约束 |
| HF smolagents | ★5k | CodeAgent 代码动作省 30% 步数 | 代码动作为媒介 |
| Tongyi DeepResearch | - | GAIA 70.9 / BrowseComp 43.4，三阶段训练 | 检索改写 + 上下文压缩 |
| 199-biotechnologies/claude-deep-research-skill | - | 8 阶段 + 决策树 + effort 分级 + 回归门 | 决策树优先执行 |
| B143KC47/deep-research-skill | - | research_ledger.py 证据账本 | 可审计证据账本 |
| Weizhena/Deep-Research-skills | - | /research → /research-deep → /research-report 三阶段 | 每项一个 subagent 返回 JSON |

---

## 三、能力缺口 → v6.0 落地映射

| v5.2 缺口 | v6.0 变更 | 实现文件 |
|-----------|----------|---------|
| 无并行子 Agent / 上下文丢失 | 子 Agent 并行编排 + 结果落盘 | SKILL.md Phase 2.5 + ledger.py |
| 无多视角/专家角色 | 多视角注入 + 专家团评审闭环 | plan.py + panel.py + Phase 3.5 |
| 无证据账本 / 不可溯源 | claim→source 账本 | ledger.py |
| 无 effort/breadth 旋钮 | effort 分级 + depth/breadth | research.py --effort/--breadth |
| 来源无 Tier 分级 | Tier 1-4 域名判定 | tier.py + score.py 集成 |
| 无证据充分性判据 | 独立来源≥2 才 verified | reflect.py evidence_sufficiency |
| 无计划确认门 | 待确认清单 + AskUserQuestion | Phase 1.5 + cmd_plan_only |
| 引用无独立核对 | 发布前校验门 | validate_report.py |

---

## 四、关键来源

- Anthropic：https://www.anthropic.com/engineering/built-multi-agent-research-system
- Gemini 协作规划：https://aistudio.google.com/learn/deep-research-developer-guide
- Gemini API 深研：https://blog.google/technology/developers/deep-research-agent-gemini-api/
- Perplexity 特性：https://suprmind.ai/hub/perplexity/features/
- STORM：https://arxiv.org/abs/2402.14207
- RedDebate：https://arxiv.org/html/2506.11083v3
- LATS：https://arxiv.org/pdf/2310.04406v3.pdf
- Salesforce EDR：https://arxiv.org/html/2604.24978
- GPT Researcher：https://github.com/assafelovic/gpt-researcher
- dzhng/deep-research：https://github.com/dzhng/deep-research
- STORM：https://github.com/stanford-oval/storm
- OpenDeepResearcher：https://github.com/langchain-ai/open_deep_research
- Auto-Deep-Research：https://github.com/HKUDS/Auto-Deep-Research
- OpenManus：https://github.com/mannaandpoem/OpenManus
- OWL：https://github.com/camel-ai/owl
- smolagents：https://github.com/huggingface/smolagents
- Tongyi DeepResearch：arXiv 2510.24701
- anthropics/skills 官方仓库（确认无官方 deep-research skill）：https://github.com/anthropics/skills
- Weizhena/Deep-Research-skills：https://github.com/Weizhena/Deep-Research-skills
- 199-biotechnologies 调研 skill：https://github.com/199-biotechnologies/claude-deep-research-skill
- B143KC47 调研 skill（证据账本）：https://github.com/B143KC47/deep-research-skill