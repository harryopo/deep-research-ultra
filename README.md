# Deep Research Ultra — 超级深度调研工具 v6.88.0

可溯源的深度调研工具。插件壳 7.4.0。

**Plan → Execute → Synthesize → Reflect** 四阶段范式。Lead 内联编排，子 Agent 并行检索，
深度调研专家团对抗，证据账本逐条回源，发布前校验门硬绑账本。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-orange.svg)](https://claude.ai/code)
[![Version](https://img.shields.io/badge/version-6.88.0-brightgreen.svg)]()

在线教程：<https://harryopo.github.io/deep-research-ultra/>

## 这个工具解决什么问题

调研的产出质量取决于两件事：**找到的东西对不对**，以及**写出来的每句话有没有出处**。
这两件事通常都靠人自觉，于是同一个错误会在报告里反复出现：把搜索引擎的标题当成结论、
把三年前的仓库说成"仍在维护"、把互相矛盾的两篇论文只引用其中一篇。

本工具的立场是：**判断留给 Lead，纪律交给机器。**

- 纪律（机器管）：来源逐条可回源、引用编号与账本一致、未验证的断言不许当定论、
  未裁决的矛盾必须标注、抓回来的网页里的"指令"不得改变裁决动作、报告与账本不一致就盖不了戳。
- 判断（人管）：哪些资料相关、结论是什么、取舍怎么定。工具不做这两件事，也假装自己做。

## 数据源口径（先看这个）

34 个数据源分四层：MCP 服务器、全局 Skill、内置工具、降级引擎。

**34 是注册表里的口径，不是"今天能用 34 个"。** 它等于 `--list` 报的总数。可用性分三层看，
层层收紧：

| 命令 | 回答的问题 |
|---|---|
| `--list` | 配置就绪了吗（不需要额外 key / 服务地址） |
| `--probe` | 这个引擎今天真出不出得来数据 |
| `--probe --sources a,b --theme-query "<本维度真要用的词>"` | 这个引擎对你这个主题到不到数据 |

**别拿 34 当可用数**，也别把某次 probe 的数字写进文档当定数：它取决于网络、凭据与上游状态，
每次都不一样。静态文档只承诺可复算的东西（注册表口径），动态的交给 `--probe`。

## 安装

一个目录，两种用法。硬性校验（发布门、防伪戳、证据账本）在两种用法下都生效——
它们由本仓库自带的 Python 脚本执行，不依赖宿主是否加载了插件。

### 前置条件

- Python 3.10+，且 `python` 在 PATH 上（插件模式下宿主会直接 spawn 它）
- 第三方依赖只有一个：`ddgs`；插件模式额外需要 `mcp>=2.1,<3`
- 任一 Agent 宿主（Qoder / Claude Code / TRAE / Codex CLI 等）

### 方式一：解包即用（默认，零注册、零重启）

拿到 `deep-research-ultra-v7.4.0.zip` 时，解压后进入解压出的 `deep-research-ultra/` 目录，
执行下面三条命令（不需要 git、不需要联网克隆）：

```bash
pip install -r skills/deep-research-ultra/requirements.txt

# 把 skill 目录放进宿主的 skills 路径即可被触发（Qoder 为例）
# 先删旧目录再拷：cp -r 是合并，旧版里已删除的文件会留在安装位（实测能留下旧 scripts/*.py），
# 装完就成了「版本号相同、内容不同」的漂移副本
rm -rf ~/.qoder/skills/deep-research-ultra
cp -r skills/deep-research-ultra ~/.qoder/skills/

python skills/deep-research-ultra/scripts/research.py --probe   # 自检：引擎今天真出不出数据
```

Windows 下换成：

```bash
robocopy skills\deep-research-ultra %USERPROFILE%\.qoder\skills\deep-research-ultra /MIR
```

`/MIR` 会先删掉目标里多出来的旧文件。robocopy 的返回码是位掩码不是「0 才算成功」，
本机实测：`0`＝没有变化、`1`＝复制了文件、`3`＝复制了文件并删掉了多余文件
（**从旧版升级成功就是 3，别当成失败**），`8` 及以上才是真失败。

有网络时也可以直接克隆，之后步骤相同：

```bash
git clone https://github.com/harryopo/deep-research-ultra.git
cd deep-research-ultra
```

调用调研时对宿主**没有任何额外要求**：所有强制校验都是 `scripts/` 下的 Python 在跑。

**换别的宿主就换一条命令**（把 skill 目录放到正确位置，顺带把 MCP 配好）：

```bash
python skills/deep-research-ultra/scripts/install.py --host trae --dry-run   # 先看要动哪些文件
python skills/deep-research-ultra/scripts/install.py --host trae             # 实际执行
```

已实测的落点（Windows，2026-09-21）：Qoder `~/.qoder/skills/`、TRAE CN `~/.trae-cn/skills/`。
两家的 `SKILL.md` 都必须在目录**顶层**，放深一层宿主就扫不到。TRAE 的 MCP 写在
`%APPDATA%\Trae CN\User\mcp.json`，安装器按**绝对路径**追加一条、幂等，
并保留你已有的其它 MCP 条目。安装器遇到「目标像个 git 仓库」会硬停不覆盖，让你先看。

### 方式二：再注册为宿主插件（可选加分项）

注册后多得到两样东西：Agent 能直接看见并调用 `drux_*` 工具；`Stop` hook 在收尾时兜一道
「没过校验门就想交报告」的拦截。

```bash
# 让宿主从本地插件缓存目录加载（Qoder 为例）
mkdir -p ~/.qoder/plugins/cache/local/deep-research-ultra/7.4.0
git archive HEAD | tar -x -C ~/.qoder/plugins/cache/local/deep-research-ultra/7.4.0
```

然后在 `~/.qoder/plugins/installed_plugins_v2.json` 里登记一条 `installPath` 指向上面这个目录，
并把插件名写进 `~/.qoder/settings.json` 的 `enabledPlugins`，**开一个新会话**生效。

三条实测过的注意事：

1. 注册只是**指针**，宿主从 `installPath` 读代码。改完仓库代码必须重新执行上面的
   `git archive` 那两行，否则宿主跑的还是旧副本。
2. 会话的工具表是**启动时的快照**：注册插件后旧会话里看不到 `drux_*`，要开新会话。
   hook 不需要重启（按事件实时读取）。
3. macOS / Linux 的插件登记路径**未实测**，本仓库所有实测数据来自 Windows。

### 依赖

| 依赖 | 用途 | 必需 |
|---|---|---|
| `ddgs` | DuckDuckGo 搜索（Layer 4 降级引擎） | 是 |
| Python 标准库 | urllib / json / subprocess（核心模块） | 内置 |
| `mcp` | 仅注册为插件时才需要（承载 `server.py`） | 方式二必需 |
| `jieba` | 中文分词（提升评分准确性） | 可选 |

核心模块仅依赖 Python 标准库 + ddgs，依赖体积做到最小。

## 配置

### 四层数据源架构

```
Layer 1: MCP 服务器层（首选，结构化、稳定）
  Tavily MCP        AI 搜索 + extract + map + crawl
  Firecrawl MCP     搜索 + scrape + crawl + browser 自动化
  open-websearch    免费、无 Key、Bing / 百度 / CSDN / 掘金等
  arxiv MCP         arXiv 论文
  paper-search MCP  14 个学术平台聚合

Layer 2: 全局 Skill 层（已存在，直接复用）
  agent-reach       13 个平台社交（X / Reddit / HN / B站 / 知乎 等）
  oss-finder        GitHub / GitLab / Gitee / npm / PyPI
  last30days        近 30 天全网
  sciverse          学术论文深度检索
  defuddle          网页转 Markdown（替代 Jina Reader）
  context7          库文档拉取

Layer 3: 宿主内置工具层
  WebSearch         实时网络搜索
  WebFetch          简单网页抓取
  Task (subagent)   并行子 Agent

Layer 4: 自建 / 降级层（仅当上面都不可用时）
  DuckDuckGo        ddgs Python 库（免费、无需 Key）
  百度 / Bing HTML  HTML 解析（最后手段，易失效）
  SearXNG           自建元搜索（Docker 部署）
```

### 配置场景

| 场景 | 推荐操作 |
|---|---|
| 零配置快速开始 | `bash setup-mcp.sh --core`（免费 MCP） |
| 国内无 VPN | `--core` + Tavily（可选） |
| 有 VPN | `--core` + Tavily + Firecrawl + Brave Search MCP |
| 学术调研 | `--core` + Semantic Scholar MCP + Scientific-Papers-MCP |

详见 [references/mcp-config.md](skills/deep-research-ultra/references/mcp-config.md)

### 环境变量

```bash
# Layer 1: MCP 增强层（可选）

# Tavily AI 搜索（推荐，1000 次/月免费；注册前确认免绑卡——要绑银行卡就放弃这个源）
# 获取地址：https://app.tavily.com
export TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxx

# Firecrawl 搜索 + 抓取（500 credits/月；注册前确认免绑卡——要绑银行卡就放弃这个源）
# 获取地址：https://firecrawl.dev
export FIRECRAWL_API_KEY=fc-xxxxxxxxxxxxxxxxxxxxx

# Layer 4: 降级层（可选）

# SearXNG 自建实例地址
export SEARXNG_URL=http://localhost:8080

# 代理配置（可选，用于访问国际服务）
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

## 使用

### 作为 Skill 使用（推荐）

```text
/deep-research-ultra 深度调研 2025 年最值得学习的 Python Web 框架
```

或直接用自然语言触发：

```text
帮我深度研究一下 Kubernetes 生产环境最佳实践
全面分析 FastAPI vs Django REST Framework 的性能对比
```

### 命令行

下面这类命令都在 skill 目录内执行（`cd skills/deep-research-ultra`）。

**脚本直接落盘的是「证据集」**（检索结果页：标题 / URL / 摘要 / CRAAP / Tier），
**不是调研报告，不能直接交付**。报告由主 Agent 组稿：`skeleton.py` 直出引用编号与来源登记表，
补写摘要 / 方法 / 结论，再过校验门。下面这些命令跑完，把产物当证据集用。

```bash
# 自动选择数据源（推荐，默认 HTML 报告）
python scripts/research.py "Python Web 框架"

# 指定深度与反思轮数
python scripts/research.py "AI agent" --depth deep --reflect-rounds 3

# 指定数据源（引擎名）
python scripts/research.py "AI agent" --sources tavily,arxiv

# 搜索所有可用数据源（聚合模式）
python scripts/research.py "AI 趋势" --all

# 仅生成 MECE 计划（不执行搜索）
python scripts/research.py "RAG 最佳实践" --plan-only

# 输出到文件
python scripts/research.py "FastAPI vs Django" --format html -o report.html
```

### 引擎选择

| 场景 | 推荐数据源 | 理由 |
|---|---|---|
| 中文技术问题 | `open-websearch,tavily,agent-reach` | 中文内容 + 结构化 + 社区口碑 |
| 英文学术问题 | `arxiv,paper-search,sciverse` | 三个学术数据源全覆盖 |
| 开源项目搜索 | `oss-finder,tavily,open-websearch` | 项目搜索 + 评测文章 |
| 近期热点 | `last30days,agent-reach,tavily` | 时效性 + 社区讨论 |

### 输出格式

| 格式 | 命令 | 用途 |
|---|---|---|
| HTML（默认） | `--format html -o report.html` | 含 Mermaid 问题树、时间线、CRAAP 评分表、来源分布、矛盾点标注 |
| Markdown | `--format markdown` | 适合归档 |
| JSON | `--format json` | 适合 API 集成 |
| CSV | `--format csv` | 适合 Excel 分析 |

## 四阶段工作流

### Phase 1: Plan

把模糊主题拆成互斥穷尽（MECE）的子问题树，每个子问题附可验证假设。

```bash
python scripts/research.py "RAG 最佳实践" --plan-only --depth standard
```

输出 MECE 问题树（含假设与数据源匹配）、MECE 验证（重叠度 / 覆盖度评分）、Mermaid 可视化图。

### Phase 2: Execute

按 breadth 派发子 Agent 并行检索，每轮搜索后评估是否需要 Drill-down。

宿主没有 Agent 工具时降级为 Lead 串行自跑，但**账本分片与 merge 归并不能省**——
降级的是编排方式，不是纪律。详见 SKILL.md Phase 2.5 与 `references/subagent-lessons.md`。

### Phase 3: Synthesize

基于证据池生成 CER 结构报告：

- **Claim**：结论
- **Evidence**：证据（带来源 URL + CRAAP 评分）
- **Reasoning**：推理链

### Phase 4: Reflect

调研质量自评 + 用户反馈 + 记忆归档。

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| 覆盖率 | 已有证据的子问题数 / 总子问题数 | ≥ 90% |
| 交叉验证率 | 有 ≥2 独立来源的结论数 / 总结论数 | ≥ 70% |
| 矛盾处理率 | 已处理矛盾数 / 发现矛盾数 | 100% |
| 平均 CRAAP 分 | 所有来源 CRAAP 均分 | ≥ 70 |

## 深度与评分

### 深度策略

| 深度（`--depth`） | 对应 effort | 子问题数（硬上限） | 每问数据源数 | 报告字数（多轮累计目标） | 预计耗时 |
|---|---|---|---|---|---|
| quick | `quick` | ≤3 | 2 | 1500-3000 | 1-2 分钟 |
| standard | `standard` | ≤5 | 3 | 3000-6000 | 3-5 分钟 |
| deep | `deep` | ≤8 | 5 | 6000-15000 | 10-20 分钟 |
| extreme | `exhaustive` | ≤12 | 8 | 15000+ | 20-40 分钟 |

表里没有「反思轮次」这一列：反思轮数由 `--reflect-rounds N` 单独决定（默认 1，`0` 关闭），
不随深度档变；专家团视角由 `--perspectives` 决定（不传给默认三视角：域专家 / 怀疑者 / 实践者）。
维度给超过当晚上限会在 stderr 点名丢弃，要多几个子问题就同时升档。

### CRAAP 五维评分

| 维度 | 含义 | 分值 |
|---|---|---|
| Currency | 时效性 | 0-20 |
| Relevance | 相关性 | 0-20 |
| Authority | 权威性 | 0-20 |
| Accuracy | 准确性 | 0-20 |
| Purpose | 目的性 | 0-20 |

```bash
# 启用 LLM 语义评分（更准确，但消耗 token）
python scripts/research.py "关键词" --llm-score
```

账本同时存 `relevance` 与 `relevance_capped`。`craap_score`(total) 把权威性 / 时效性
掺了进来，**不是 relevance 的代理**（实测同一批结果两张名次只有 1/29 重合），
读证据按 `relevance` 排；`relevance_capped=True` 表示判定器没听懂这个语料，
**不是「评出来不相关」**。

### 缓存

- 缓存目录：`~/.cache/deep-research/`
- TTL：1 小时
- LRU 淘汰：maxsize 100
- 线程安全 + 磁盘持久化

```bash
# 禁用缓存
python scripts/research.py "query" --no-cache
```

## 核心机制

下面每条都是实测踩出来的，不是设计意图。括号里是引入它的版本。

| 机制 | 说明 |
|---|---|
| 四阶段工作流 | Plan → Execute → Synthesize → Reflect（v6.0） |
| 子 Agent 并行编排 | Lead 规划 → 并行 spawn 子 Agent（独立上下文）→ 结果落盘 → 归并（v6.0） |
| 深度调研专家团 | 多视角提问（域专家 / 怀疑者 / 实践者 / 记者 / 成本）+ 红蓝对抗 + 审稿人闭环（v6.0） |
| 证据账本 | claim → source 可溯源，多子 Agent 并发写，`ledger.py` 审计导出（v6.0） |
| 来源 Tier 分级 | Tier 1-4 域名判定，CRAAP 集成加权，报告附录 D 展示（v6.0） |
| 发布前校验门 | 主指标＝引用-证据对齐（被报告引用立论的 claim 必须已 verified / conflict）/ 独立来源强度 / 必需章节 / 低质源占比 / 摘要长度（v6.7） |
| effort 分级 + breadth 旋钮 | quick / standard / deep / exhaustive + 并行子主题数（v6.0） |
| 引擎功能自检 `--probe` | 探针查询实测每个引擎今天出不出得来数据，区分「0 结果 / 401 缺配置 / 406 限流」（v6.5） |
| Phase 0 环境闸门 | 出数据引擎 <3、覆盖 <2 层、或没有一手制品通道 → 退出码 3 并逐条打印「去哪申请 + 解锁什么 + 怎么设」（v6.8） |
| 证据与结论分离 | `--ledger` 只登记证据到 evidence.jsonl，claim 必须显式 add-claim；merge 拒收不可溯源来源，缺 status 一律 pending（v6.10） |
| 报告防伪戳 | `--stamp` 只在过门后盖 `drux:validated`（含正文与账本指纹）；`--verify-stamp` 复核。**没有账本就不算过门**：不给 `--ledger` 判未通过，`ledger=none` 的旧戳一律验不过（v6.11 / v6.62 加固） |
| 仓库扫描五态 | `repo_health.py` 分清 ok / not_found / rate_limited / forbidden / unreachable：429、403、断网一律 `unknown`，不再把限流写成「该仓库高风险」（v6.12） |
| 下载制品校验 | arXiv PDF / LaTeX 落盘前验魔数、篇幅、`%%EOF` 完整性与论文 ID 一致性（v6.13） |
| 报告骨架 + 单轮产能红线 | `skeleton.py` 从账本直出引用编号与来源登记表；未达 verified 的断言带「待核」出场，残留「待写」是校验门**硬失败**（v6.14） |
| 主题级预演 | `--probe --theme-query` 把「引擎今天活着」与「引擎对这个主题到不到数据」分开报；退出码 4 = 没有任何引擎对本主题到得了数据（v6.15） |
| 检索词按语料语言给 | `--source-query 引擎=查询词`：英文学术库给英文词、国内平台给中文词。相关性按**该引擎实际收到的词**打分并记进 `evidence.jsonl`（v6.15） |
| 未知不等于 0 | 引擎返回 `None`＝通道失败、`[]`＝通到了但 0 条；没取到的 star / 引用数印「未取到」，真的是 0 才印 0（v6.24 / 6.26 / 6.29） |
| 同一制品的三条判同通道 | 同族 URL 入口、跨标识符字段（DOI / arXiv id）、跨主机逐字内容片段（v6.19–6.32） |
| 抓回内容里的指令不进裁决 | 网页 / PDF 中「忽略以上指令」式文字由机械门隔离；删除文件、上传密钥、植入程序这类动作即使当前有权限也一律不做（v6.20） |
| 每维度 claim 上限 | 单分片超过 12 条在 merge 归并时点名文件并告警——claim 产量超过验证产能时，多出来的只会是过不了门的 pending（v6.31） |
| 国内源解析按真页面重做 | 百度 / 搜狗微信 / 搜狗知乎的标题、摘要、日期重新解析；被风控的空壳页判为通道失败（v6.24.4–6.28） |
| MCP 真连接 | 5 个 MCP 源纳入闸门：一个会话一个进程真握手、25 秒整场预算；连不上就报「连不上 + 原因」（v6.9） |
| 文件化交付契约 | 报告一律落盘 `.research/<session>/report.md`，返回值只给 ≤25 行短摘要（v6.5） |
| Windows 控制台自适应 | CLI 强制 UTF-8 输出，GBK 代码页不再 UnicodeEncodeError（v6.5） |
| 两档 verified 判据 | 跨域三角验证（档 A）与「一手来源 + Lead 反查」（档 B）分开，归属型 claim 不再被卡在 pending（v6.6 / 6.7） |
| 相关性过滤与分布 | 无关结果不再靠「权威 / 时效」加权混进报告；每次检索后报相关性分布，明说「留下的里还有多少低于阈值」（v6.5 / v6.81） |
| MECE 问题树 | 麦肯锡 MECE 原则拆解主题，互斥穷尽不遗漏 + 多视角注入 |
| 交叉验证与反思循环 | 同一结论需 ≥2 个独立来源支持，矛盾点自动标注；反思用 Drill-down 决策 + 证据充分性停止 |
| 结构化报告与进度跟踪 | CER 结构 + Mermaid + 雷达图；实时 ETA 估算与质量自评 |

## 项目结构

```
deep-research-ultra/                  # 仓库根＝插件壳；skill 本体在 skills/ 子目录
├── README.md  CHANGELOG.md  LICENSE  .gitignore
├── index.html                        # GitHub Pages 宣传页
├── .qoder-plugin/plugin.json         # 宿主插件清单（注册为插件时才用到，可选）
├── mcp.json                          # MCP 服务器声明 → server.py
├── server.py                         # 5 个 drux_* 工具（stdio 握手与中文入参往返均实测）
├── hooks/
│   ├── hooks.json                    # Stop 钩子声明
│   ├── gate_hook.py                  # 报告没盖过校验戳就拦停
│   └── probe_log.py
├── tests/                            # 插件壳侧测试 4 个文件 / 50 个用例
├── docs/{specs,plans,dev}/           # 设计文档、实现计划、体检与决策记录
└── skills/deep-research-ultra/       # ← 解包即用的 skill 本体
    ├── SKILL.md                      # 接口文档：命令照抄即可，签名表见 §14.3
    ├── requirements.txt              # 唯一第三方依赖 ddgs
    ├── evals/evals.json              # 评测集（40 个场景）
    ├── references/                   # 5 份操作手册与配置指南
    └── scripts/
        ├── research.py               # 主入口（--probe / --env-check / --plan-only / --source-query…）
        ├── router.py                 # 三级级联路由 Rule → Semantic → LLM
        ├── plan.py  reflect.py  progress.py   # 问题树 / 反思停止 / 进度
        ├── probe.py  env_check.py    # 引擎功能自检 + Phase 0 环境闸门
        ├── ledger.py                 # 证据账本：merge / set-status / verify-primary / 判同三通道
        ├── guard.py                  # 越权文件与注入指令机械门
        ├── skeleton.py               # 账本直出报告骨架（引用编号 + 来源登记表）
        ├── validate_report.py        # 发布前校验门 + 防伪戳 --stamp / --verify-stamp
        ├── repo_health.py            # 仓库健康五态（限流 / 封禁 / 断网判 unknown）
        ├── claim_support.py          # 交付前忠实度自查（数字 + 定性高危形态）
        ├── check_serp_patterns.py    # SERP 改版预警：把「0 结果」的四种成因分开
        ├── recommend.py  score.py  tier.py  similarity.py   # 推荐度 / CRAAP / Tier / 判同
        ├── panel.py  report.py  verify.py  cache.py  console.py
        ├── install.py  mcp_config_writer.py  setup-mcp.sh   # 跨宿主安装与 MCP 配置
        ├── engines/                  # 13 个引擎模块，撑起四层共 34 个数据源
        │   ├── base.py               # SearchEngine 抽象基类 + EngineRegistry
        │   ├── mcp_client.py  mcp_engines.py               # MCP 层（5 个）
        │   ├── academic_engines.py  academic_fulltext.py
        │   ├── skill_engines.py  github_deep_search.py  platform_engines.py
        │   ├── cn_sources.py  builtin.py  crawl4ai_engine.py
        │   └── fallback.py           # 降级引擎 + curl_cffi TLS 指纹伪装
        └── tests/                    # 126 个测试文件 / 1278 个用例
```

## 测试

```bash
# 全仓一次跑完（内核 + 插件壳，汇总真实通过数）——在仓库根
python run_all_tests.py

# 单跑内核测试——在 skill 目录内
cd skills/deep-research-ultra/scripts && python -m pytest tests/ -v

# 单跑插件壳侧测试（握手 / MCP 工具 / Stop 钩子 / 安装器，50 个用例）——在仓库根
python -m pytest tests/ -v
```

当前 **1328 项**（内核 1278 + 壳 50）。Windows 上有 2 项因缺 `bash` 跳过
（跑 `setup-mcp.sh` 的那两条，是环境依赖不是回归）。

## 与竞品对比

| 特性 | Deep Research Ultra | Perplexity | OpenAI Deep Research | LangChain open_deep_research |
|---|---|---|---|---|
| 架构 | 四层 34 数据源 + 四阶段 + Lead 编排 | 单引擎 | 闭源 | 单框架 |
| 子 Agent 并行 | 支持：并行派发 + 证据账本 | 不支持 | 支持 | 不支持 |
| 专家团评审 | 支持：多视角 + 对抗闭环 | 不支持 | 不支持 | 不支持 |
| 证据账本 | 支持：claim → source 可溯源 | 不支持 | 不支持 | 不支持 |
| MECE 问题树 | 支持 | 不支持 | 不支持 | 不支持 |
| CRAAP 评分 + Tier | 支持：五维 + 来源分级 | 不支持 | 不支持 | 不支持 |
| 交叉验证 | 支持：≥2 独立源 | 不支持 | 不支持 | 不支持 |
| 反思循环 | 支持：多信号 + 证据充分性停止 | 不支持 | 支持 | 支持 |
| MCP 集成 | 支持：5 个 MCP | 不支持 | 不支持 | 不支持 |
| Skill 复用 | 支持：6 个 skill | 不支持 | 不支持 | 不支持 |
| 中文优化 | 支持：多引擎 | 有限 | 有限 | 不支持 |
| 费用 | 完全免费 | 付费 | 付费 | 开源 |
| 报告格式 | HTML / Markdown / JSON / CSV | 文本 | 文本 | 文本 |
| Mermaid 可视化 | 支持 | 不支持 | 不支持 | 不支持 |

## 贡献

欢迎提交 Issue 和 Pull Request。

添加新引擎：在 `scripts/engines/` 下创建新引擎类，然后在 `research.py` 的 `build_registry()` 中注册。

```python
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
        return [SearchResult(title=..., url=..., content=..., source="new-engine")]
```

## 许可证

本项目采用 [MIT 许可证](LICENSE)。

### 整合的开源工具

| 工具 | 许可证 | 来源 |
|---|---|---|
| DuckDuckGo (ddgs) | MIT | https://github.com/deedy5/ddgs |
| SearXNG | AGPL-3.0 | https://github.com/searxng/searxng |
| Tavily MCP | MIT | https://github.com/tavily-ai/tavily-mcp |
| Firecrawl MCP | MIT | https://github.com/mendableai/firecrawl-mcp |
| open-websearch MCP | MIT | https://github.com/nicholishen/open-websearch |

### 商业服务（有免费额度）

- Tavily：https://app.tavily.com （1000 次/月免费；注册前确认免绑卡——要绑银行卡就放弃这个源）
- Firecrawl：https://www.firecrawl.dev （500 credits/月；注册前确认免绑卡——要绑银行卡就放弃这个源）

## 参考资料

内部：

- [references/mcp-config.md](skills/deep-research-ultra/references/mcp-config.md) — MCP 配置指南
- [references/playbooks.md](skills/deep-research-ultra/references/playbooks.md) — 操作手册
- [CHANGELOG.md](CHANGELOG.md) — 完整更新历史
- `docs/dev/` — 开发期调研、体检与决策记录

外部：

- [OpenAI Deep Research 官方指导](https://github.com/openai/openai-cookbook) — Plan → Execute → Synthesize 三步范式
- [LangChain open_deep_research](https://github.com/langchain-ai/open_deep_research)
- [字节跳动 DeerFlow 2.0](https://github.com/bytedance/deer-flow)
- 麦肯锡方法 — MECE 原则、假设驱动、逻辑树、金字塔原理
- CRAAP Test — 信息可信度评估标准
- CER（Claim-Evidence-Reasoning）— 科学论证结构

## 相关项目

- [oss-finder](https://github.com/harryopo/oss-finder) — 开源项目搜索工具
- [agent-reach](https://github.com/harryopo/agent-reach) — 社交媒体搜索工具
- [skill-workspace](https://github.com/harryopo/skill-workspace) — Skill 开发工作台

## 支持

- 提交 Bug：https://github.com/harryopo/deep-research-ultra/issues
- 功能建议：https://github.com/harryopo/deep-research-ultra/issues
- 文档：https://github.com/harryopo/deep-research-ultra/wiki

## 致谢

- [DuckDuckGo (ddgs)](https://github.com/deedy5/ddgs) — 免费搜索 API
- [SearXNG](https://github.com/searxng/searxng) — 元搜索引擎
- [Tavily](https://tavily.com) — AI 搜索引擎
- [Firecrawl](https://firecrawl.dev) — 网页抓取与浏览器自动化
- 麦肯锡 MECE 原则 — 问题拆解方法论
- CRAAP Test — 信息可信度评估标准
- CER Framework — 科学论证结构

---

内核 6.88.0 · 插件壳 7.4.0 · 更新历史见 [CHANGELOG.md](CHANGELOG.md)
