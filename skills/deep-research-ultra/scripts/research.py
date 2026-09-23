#!/usr/bin/env python3
"""
Deep Research Ultra v5.1 — 主入口（v5 CLI）

四阶段工作流：Plan → Execute → Synthesize → Reflect
四层数据源：MCP + 学术直连/全文/引用图谱 → Skill → 内置/浏览器自动化 → 降级（含 curl_cffi TLS 伪装）
v5.0 新增：智能路由（--auto-route）+ 学术直连引擎 + 反爬虫升级
v5.1 新增：论文全文下载(arXiv/Unpaywall) + 引用图谱(S2) + Crawl4AI浏览器自动化 + 方法论落地(秘塔问题链/Kimi多信号停止)

与 v3 search.py 的关系：
- search.py 保留为 v3 兼容入口（--sources baidu,bing 等）
- research.py 是 v5 推荐入口（--depth standard --format html --auto-route 等）

用法示例：
  # 标准深度调研（HTML 报告，默认）
  python research.py "深度调研 2025 年 AI Agent 框架"

  # v5.0 智能路由（自动选择数据源）
  python research.py "最新 LLM 论文" --auto-route

  # 深度模式（多轮反思）
  python research.py "深度调研大语言模型微调" --depth deep --reflect-rounds 3

  # 查看路由分析（不执行搜索）
  python research.py "RAG 开源实现" --route

  # 仅生成 MECE 计划
  python research.py "深度调研 RAG 最佳实践" --plan-only

  # MCP 健康检查
  python research.py --mcp-check

  # 列出所有可用引擎
  python research.py --list
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

SKILL_MD = SCRIPT_DIR.parent / 'SKILL.md'


def skill_version() -> str:
    """版本号单一来源：SKILL.md frontmatter（此前 banner 硬编码 v4.0，与实际版本漂移）。"""
    import re
    try:
        for line in SKILL_MD.read_text(encoding='utf-8').splitlines()[:15]:
            m = re.match(r'\s*version:\s*(\S+)', line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return '0.0.0'


# ============================================================
# 引擎注册（导入所有引擎并注册到 Registry）
# ============================================================

def build_registry():
    """构建引擎注册表，注册所有可用引擎（v5.2 含 GitHub 深度搜索 + 国内内容源）"""
    from engines.base import EngineRegistry
    from engines import (
        TavilyMcpEngine, FirecrawlMcpEngine, OpenWebsearchMcpEngine,
        ArxivMcpEngine, PaperSearchMcpEngine,
        OpenAlexEngine, SemanticScholarEngine, PubmedEngine,
        ArxivFulltextEngine, UnpaywallEngine, CitationGraphEngine,
        AgentReachEngine, OssFinderEngine, Last30DaysEngine,
        SciverseEngine, DefuddleEngine, Context7Engine,
        GitHubDeepSearchEngine, GitHubCodeSearchEngine,
        BaiduSerpEngine, SogouWeixinEngine, SogouZhihuEngine, BaiduXueshuEngine,
        WebSearchEngine, WebFetchEngine,
        Crawl4aiEngine, LayeredCrawler,
        GiteeEngine, ModelScopeEngine,  # v6.1：国内开源平台
        DuckDuckGoEngine, BaiduHtmlEngine, BingHtmlEngine, SearXNGEngine,
    )

    registry = EngineRegistry()
    engine_classes = [
        # Layer 1: MCP 服务器
        TavilyMcpEngine, FirecrawlMcpEngine, OpenWebsearchMcpEngine,
        ArxivMcpEngine, PaperSearchMcpEngine,
        # Layer 1: 学术直连引擎（v5.0 新增，无需 MCP，直连免费 API）
        OpenAlexEngine, SemanticScholarEngine, PubmedEngine,
        # Layer 1: 学术全文+引用图谱（v5.1 新增）
        ArxivFulltextEngine, UnpaywallEngine, CitationGraphEngine,
        # Layer 2: Skill
        AgentReachEngine, OssFinderEngine, Last30DaysEngine,
        SciverseEngine, DefuddleEngine, Context7Engine,
        # Layer 2: GitHub 深度搜索（v5.2 新增：分桶+低星+依赖图+awesome，不漏项目）
        GitHubDeepSearchEngine, GitHubCodeSearchEngine,
        # Layer 2: 国内内容源（v5.2 新增：百度/搜狗微信/搜狗知乎/百度学术）
        BaiduSerpEngine, SogouWeixinEngine, SogouZhihuEngine, BaiduXueshuEngine,
        # Layer 3: 内置
        WebSearchEngine, WebFetchEngine,
        # Layer 3: 浏览器自动化（v5.1 新增）
        Crawl4aiEngine,
        # Layer 2: 国内开源平台（v6.1 新增：Gitee/ModelScope 免费 API 直连）
        GiteeEngine, ModelScopeEngine,
        # Layer 4: 降级（含 curl_cffi TLS 指纹伪装）
        DuckDuckGoEngine, BaiduHtmlEngine, BingHtmlEngine, SearXNGEngine,
    ]
    for cls in engine_classes:
        try:
            registry.register(cls())
        except Exception as e:
            print(f"⚠️ 引擎 {cls.__name__} 注册失败: {e}", file=sys.stderr)
    return registry


# ============================================================
# 命令：--mcp-check
# ============================================================

def cmd_mcp_check(registry):
    """MCP 健康检查：静态配置之外，真起进程握一次手，数得出工具才算连上。"""
    from probe import MCP_PROBE_BUDGET, engine_kind

    print("=" * 60)
    print(f"Deep Research Ultra v{skill_version()} — MCP 健康检查")
    print("=" * 60)
    print()

    mcp_engines = [e for e in registry.get_by_layer(1, only_available=False)
                   if engine_kind(e) == 'mcp']
    if not mcp_engines:
        print("⚠️ 未注册任何 MCP 引擎")
        return

    available_count = 0
    for engine in mcp_engines:
        m = engine.metadata
        if not engine.is_available():
            missing = [k for k in m.config_keys if not os.environ.get(k)]
            reason = f"缺少环境变量: {', '.join(missing)}" if missing \
                else "配置文件里没有这个 server，或 command 不可执行"
            print(f"  ❌ 未配置    {m.name:<20} {reason}")
            continue
        client = getattr(engine, '_client', None)
        tools = client.list_tools(timeout=MCP_PROBE_BUDGET) if client else []
        if tools:
            available_count += 1
            print(f"  ✅ 已连接    {m.name:<20} {len(tools)} 个工具")
        else:
            reason = str(getattr(client, 'last_error', '') or '握手无响应')
            print(f"  ❌ 连不上    {m.name:<20} {reason}")

    print()
    print(f"总计: {available_count}/{len(mcp_engines)} 个 MCP 真连得通")

    if available_count == 0:
        print()
        print("💡 建议运行一键配置脚本（免费 MCP）：")
        print("   bash scripts/setup-mcp.sh --core")
        print("   首次跑要下载包，配好后先 --mcp-check 预热再 --probe")
    elif available_count < len(mcp_engines):
        print()
        print("💡 如需解锁全部 MCP，运行：")
        print("   bash scripts/setup-mcp.sh --all")


# ============================================================
# 命令：--env-check（v6.1 环境分级门控）
# ============================================================

def cmd_env_check(args):
    """环境分级验证：按调研场景（profile）声明所需环境并逐项验证"""
    from env_check import run_env_check, format_report, PROFILES

    profile = getattr(args, 'env_profile', 'full')
    if profile not in PROFILES:
        print(f"❌ 未知 profile: {profile}（可选: {', '.join(PROFILES)}）", file=sys.stderr)
        sys.exit(2)

    include_net = not getattr(args, 'no_net', False)
    print("=" * 60)
    print(f"Deep Research Ultra — 环境验证（profile: {profile}）")
    print("=" * 60)
    report = run_env_check(profile, include_net=include_net)
    print(format_report(report, verbose=False))

    if not report.ready:
        print()
        print("💡 尚未就绪：请先完成上述缺失项配置，再重跑 --env-check 验证通过后开始调研。")
        sys.exit(1)
    sys.exit(0)


# ============================================================
# 命令：--route（v5.0 智能路由）
# ============================================================

def cmd_route(args, registry):
    """智能路由分析 — 展示查询分类和推荐引擎链"""
    from router import QueryRouter

    print("=" * 70)
    print("Deep Research Ultra v5.0 — 智能路由分析")
    print("=" * 70)
    print()

    router = QueryRouter()
    decision = router.route(args.query, {})

    # 查询类型
    type_labels = {
        'academic': '学术论文', 'opensource': '开源项目', 'community': '社区口碑',
        'docs': '技术文档', 'news': '时效新闻', 'general': '通用搜索',
        'definition': '定义解释', 'guide': '操作指南', 'comparison': '对比分析',
    }
    type_label = type_labels.get(decision.query_type, decision.query_type)
    print(f"📋 查询: {args.query}")
    print(f"🏷️  类型: {decision.query_type}（{type_label}）")
    if decision.secondary_types:
        secondary_labels = [type_labels.get(t, t) for t in decision.secondary_types]
        print(f"     次要类型: {', '.join(secondary_labels)}")
    print(f"📊 置信度: {decision.confidence:.0%}")
    print(f"⏰ 时间敏感度: {decision.time_sensitivity}")
    print(f"🏛️ 权威性需求: {decision.authority_need}")
    print()

    # 多语言变体
    if decision.query_variants:
        print("🌍 多语言查询变体:")
        for v in decision.query_variants:
            print(f"   [{v.get('lang', '?')}] {v.get('q', '')}")
        print()

    # 推荐引擎链
    print("🔗 推荐引擎链（按优先级）:")
    from probe import agent_invoked
    available_engines = registry.get_available()
    available_names = {e.get_name() for e in available_engines}
    # skill 封装与宿主内置的 is_available() 恒 True，但脚本层 search() 恒返 None：
    # 光看 is_available 会给它们打 ✅，照建议命令跑就是白跑一路（实测 oss-finder 排第一）。
    agent_only = {e.get_name() for e in registry.get_all() if agent_invoked(e)}
    for i, eng_name in enumerate(decision.engine_chain, 1):
        if eng_name in agent_only:
            status = "🤖"
        else:
            status = "✅" if eng_name in available_names else "❌"
        engine = registry.get(eng_name)
        desc = engine.metadata.description[:50] if engine else "(未注册)"
        print(f"   {i}. {status} {eng_name:<20} {desc}")
    if agent_only & set(decision.engine_chain):
        print("   🤖 ＝数据只有 Agent 亲自调用对应工具才拿得到，"
              "research.py（脚本层）跑它必返 0 条")
    print()

    # 断路器过滤后的可用引擎链
    filtered = router.filter_engines_by_breaker(decision.engine_chain)
    removed = set(decision.engine_chain) - set(filtered)
    if removed:
        print(f"⚡ 断路器过滤: {', '.join(removed)}（暂时不可用，已跳过）")
        print()

    # 路由推理
    if decision.reasoning:
        print("📝 路由推理:")
        print(f"   {decision.reasoning}")
        print()

    runnable = [n for n in filtered if n not in agent_only]
    print("💡 使用以下命令执行调研:")
    if runnable:
        print(f"   python research.py \"{args.query}\" --sources {','.join(runnable[:5])}")
    print(f"   或直接运行（自动路由）:")
    print(f"   python research.py \"{args.query}\" --auto-route")
    dropped = sorted(agent_only & set(filtered))
    if dropped:
        print(f"   🤖 {', '.join(dropped)} 不写进 --sources：脚本层取不到，"
              f"要由 Lead/子 Agent 直接调用对应 skill 或内置工具")


# ============================================================
# 命令：--list
# ============================================================

def cmd_list(registry):
    """列出所有引擎"""
    print("=" * 80)
    print(f"Deep Research Ultra v{skill_version()} — 引擎清单（四层架构）")
    print("=" * 80)
    print()

    layer_names = {
        1: "Layer 1: MCP 服务器层（首选）",
        2: "Layer 2: 全局 Skill 层（复用）",
        3: "Layer 3: Claude 内置工具层",
        4: "Layer 4: 降级引擎层（兜底）",
    }

    for layer in [1, 2, 3, 4]:
        engines = registry.get_by_layer(layer, only_available=False)
        if not engines:
            continue
        print(f"┌─ {layer_names[layer]}")
        for engine in engines:
            m = engine.metadata
            status = "✅" if engine.is_configured() else "❌"
            caps = ", ".join(m.capabilities) if m.capabilities else "-"
            config_hint = ""
            if m.requires_config:
                missing = [k for k in m.config_keys if not os.environ.get(k)]
                if missing:
                    config_hint = f" [需配置: {', '.join(missing)}]"
            print(f"│  {status} {m.name:<20} {m.description[:50]}{config_hint}")
            print(f"│     能力: {caps}  优先级: {m.priority}  国内可用: {'是' if m.is_china_friendly else '否'}")
        print("└─")
        print()

    # 降级链（配置就绪顺序；实时可达由 --probe 判）
    chain = registry.get_configured_chain()
    print("降级链（按优先级）：")
    print("  " + " → ".join(e.get_name() for e in chain))
    print()

    summary = registry.summary()
    print(f"总计: {summary['total']} 个引擎，配置就绪 {summary['configured']} 个"
          f"（{summary['needs_config']} 个需先配 key/服务）")
    layers = summary['configured_by_layer']
    print(f"  Layer 1: {layers[1]}  Layer 2: {layers[2]}  "
          f"Layer 3: {layers[3]}  Layer 4: {layers[4]}")
    print()
    print("ℹ️  ✅ ＝配置就绪（免配置，或所需 key 已给），与本机能连上吗无关；"
          "某源此刻出不出数据请用 --probe 实测")


def filter_by_relevance(results, min_relevance: float, target_count: int):
    """按 CRAAP 相关性维度过滤：返回 (保留, 实际丢弃数, 低相关条数)。

    只在高相关结果够数时才丢弃 —— 跨语言调研（中文主题命中英文源）相关性天然偏低，
    无脑过滤会把整份报告清空。低相关结果不会静默混过：够数就丢，不够数就保留并让
    调用方告警（结论不得只靠它们）。
    """
    if min_relevance <= 0:
        return list(results), 0, 0

    def _relevance(r) -> float:
        score = getattr(r, 'craap_score', None) or {}
        return float(score.get('relevance', 0) or 0)

    strong = [r for r in results if _relevance(r) >= min_relevance]
    weak = len(results) - len(strong)
    needed = max(1, min(target_count, 5))
    if len(strong) >= needed:
        return strong, weak, weak
    return list(results), 0, weak


def _cmd_theme_preflight(registry, args):
    """主题级预演：拿 Lead 派给子 Agent 的实际查询词逐条打一次。

    --probe 用的是登记死的通用词，它 ✅ 只说明引擎今天活着。实测探针 ✅ 的
    arxiv-fulltext 对每一条真实查询都 HTTP 406 —— 于是"指定引擎没结果"被读成
    "这个主题没资料"。本命令在派单前先量一次到得到数据吗，并拒绝把 0 命中当结论。
    """
    from probe import THEME_USABLE, format_theme_rows, theme_probe

    if not args.sources:
        print("❌ 主题预演必须配 --sources：它按实际查询词逐条打真请求，"
              "不限引擎范围＝全部源×全部词，白烧额度", file=sys.stderr)
        print('   用法：research.py --probe --sources arxiv-fulltext,github-code-search '
              '--theme-query "本维度要用的查询词"（可重复给多条）', file=sys.stderr)
        sys.exit(2)

    queries = [q.strip() for q in args.theme_query if q and q.strip()]
    if not queries:
        print("❌ --theme-query 给了空值：要预演的是 Lead 真正要派出去的那句查询",
              file=sys.stderr)
        sys.exit(2)

    wanted = {s.strip() for s in args.sources.split(',') if s.strip()}
    engines = [e for e in registry.get_all() if e.get_name() in wanted]
    unknown = sorted(wanted - {e.get_name() for e in engines})
    if unknown:
        print(f"❌ --sources 里有引擎不存在：{', '.join(unknown)}"
              f"（--list 看可用引擎名；少跑一个源会被读成\"本主题到不了\"）", file=sys.stderr)
        sys.exit(2)

    print("=" * 72)
    print(f"主题级预演 — {len(engines)} 个引擎 × {len(queries)} 条实际查询词")
    print("=" * 72)
    rows = theme_probe(engines, queries, max_results=max(3, min(args.limit, 5)))
    for line in format_theme_rows(rows):
        print(line)

    usable = [r for r in rows if r['verdict'] == THEME_USABLE]
    print("-" * 72)
    if usable:
        print(f"✅ 可派单：{len(usable)}/{len(rows)} 个引擎对本主题到得了数据"
              f"（{'、'.join(r['engine'] for r in usable)}）")
        return
    print("⛔ 没有任何引擎对本主题到得了数据 —— 这不等于主题没资料：")
    print("   · 先换查询词形态（整句长查询拆成 2-3 个短词组／分类式查询）重跑预演")
    print("   · 或补同层替代源（--list --caps academic,fulltext 看候选）")
    print("   · 仍要开跑时：报告里写明本主题仅由哪几个源支撑，0 命中不得写成\"无相关文献\"")
    sys.exit(4)


def cmd_probe(registry, args):
    """引擎功能自检 + 环境充分性硬门（Phase 0）。

    --list 的 ✅ 只代表配置就绪；本命令才代表"这个引擎今天真的能用"。
    环境不足时退出码非 0（3）——Lead 看到 0 就会直接进 Phase 1 开跑。
    """
    from probe import (STATUS_AGENT_ONLY, STATUS_EMPTY, STATUS_FAILED, STATUS_OK,
                       STATUS_SKIPPED, engine_kind, probe_engine, probeable_engines,
                       source_gate, summarize)

    if getattr(args, 'theme_query', None):
        _cmd_theme_preflight(registry, args)
        return

    scoped = bool(args.sources)
    if scoped:
        wanted = {s.strip() for s in args.sources.split(',') if s.strip()}
        engines = [e for e in registry.get_all() if e.get_name() in wanted]
    else:
        engines = probeable_engines(registry.get_all())

    mcp_n = sum(1 for e in engines if engine_kind(e) == 'mcp')
    scope = f"{len(engines)} 个引擎 · 含 {mcp_n} 个 MCP（真连一次）" if mcp_n \
        else f"{len(engines)} 个引擎"
    print("=" * 72)
    print(f"Deep Research Ultra v{skill_version()} — 引擎功能自检（{scope}）")
    print("=" * 72)

    marks = {STATUS_OK: '✅', STATUS_EMPTY: '⚠️', STATUS_FAILED: '❌',
             STATUS_SKIPPED: '⏭ ', STATUS_AGENT_ONLY: '🤖'}
    reports = []
    for engine in engines:
        rep = probe_engine(engine, query=args.probe_query or '',
                           max_results=max(3, min(args.limit, 5)))
        reports.append(rep)
        print(f"{marks.get(rep['status'], '?')} {rep['engine']:<20} "
              f"{rep['count']:>2} 条  {rep['note']}")

    counts = summarize(reports)
    print("-" * 72)
    print(f"功能正常 {counts.get(STATUS_OK, 0)} ｜ 0 结果 {counts.get(STATUS_EMPTY, 0)} ｜ "
          f"不可用 {counts.get(STATUS_FAILED, 0)} ｜ 跳过 {counts.get(STATUS_SKIPPED, 0)}"
          f" ｜ 🤖 需 Agent 调用 {counts.get(STATUS_AGENT_ONLY, 0)}")
    judged = [r for r in reports
              if r['status'] not in (STATUS_AGENT_ONLY, STATUS_SKIPPED)]
    if not counts.get(STATUS_OK) and not judged:
        # --sources 只点了脚本层取不到数据的引擎：这是"看不见"，不是"坏了"。
        # 判成 rc=1「不要开始调研」会把一轮正常调研拦停在假红上（实测）。
        print("🤖 这一轮点的引擎都得由 Agent 亲自调工具才有数据，脚本层探不了它们。")
        print("   别据此说引擎坏了，也别用 --probe 判它们；要探的是脚本层那批源。")
        return
    if not counts.get(STATUS_OK):
        print("❌ 没有任何引擎通过功能自检 —— 不要开始调研，先按上面的缺项修环境", file=sys.stderr)
        sys.exit(1)

    gate = source_gate(reports)
    if scoped:
        print("ℹ️  局部自检（--sources 指定了引擎范围）：只验证这几个引擎出不出数据，"
              "不判定全局环境充分性")
        for line in gate['guidance']:
            print(f"  · {line}")
        return

    print("-" * 72)
    print(f"🚦 环境闸门：真出数据 {len(gate['available'])} 个"
          f" ｜ 覆盖层 {gate['layers']}"
          f" ｜ 一手通道 {gate['primary_channels'] or '无'}")
    if gate['ok']:
        print("✅ 环境可开工")
        if gate['guidance']:
            print(f"⚠️ 有 {len(gate['guidance'])} 个源没配好。先与用户确认"
                  f"「现在配 / 就这样开跑」，不要默认降级：")
            for line in gate['guidance']:
                print(f"  · {line}")
        return

    if getattr(args, 'allow_degraded', False):
        print(f"⚠️ 环境不足 —— 已按 --allow-degraded 放行：{'；'.join(gate['blockers'])}")
        print("   报告里必须写明数据源受限，未验证的结论不得当作定论")
        return

    print("⛔ 环境不足 —— 停下，先配置再调研：")
    for b in gate['blockers']:
        print(f"   · {b}")
    if gate['guidance']:
        print("📋 怎么配（配好后重跑 --probe，直到闸门放行）：")
        for line in gate['guidance']:
            print(f"   - {line}")
    print("→ 把这些缺项转述给用户，等他配好环境再开跑（退出码 3）；"
          "确需带缺口调研时由用户显式加 --allow-degraded")
    sys.exit(3)


# ============================================================
# 命令：--plan-only
# ============================================================

def cmd_plan_only(args):
    """仅生成 MECE 计划（v6.0：含多视角 + 待确认清单）"""
    from plan import PlanGenerator, IssueTree

    gen = PlanGenerator()
    perspectives = None
    if getattr(args, 'perspectives', None) == '0':
        perspectives = []
    elif getattr(args, 'perspectives', None):
        perspectives = [p.strip() for p in args.perspectives.split(',')]

    plan = gen.generate_plan(
        topic=args.query,
        goal=args.goal or '',
        depth=args.depth,
        effort=args.effort,
        dimensions=args.dimensions.split(',') if args.dimensions else None,
        time_range=args.time_range or '',
        language=args.language or 'auto',
        region=args.region or '',
        perspectives=perspectives,
    )

    # 构建 IssueTree 对象以便验证和可视化
    tree = IssueTree()
    tree.roots = list(plan.issue_tree)

    print("=" * 60)
    print(f"Deep Research Ultra v{skill_version()} — MECE 调研计划")
    print("=" * 60)
    print()
    print(f"主题: {plan.topic}")
    print(f"目标: {plan.goal or '(未指定)'}")
    print(f"深度: {plan.depth}")
    print(f"维度: {', '.join(plan.dimensions) if plan.dimensions else '(自动)'}")
    print(f"预计耗时: {plan.estimated_duration}")
    print(f"预计来源数: {plan.estimated_sources}")
    print()

    # MECE 问题树
    print("─" * 60)
    print("MECE 问题树：")
    print("─" * 60)
    if plan.issue_tree:
        for i, q in enumerate(plan.issue_tree, 1):
            print(f"\n  Q{i}: {q.question}")
            if q.hypothesis:
                print(f"      假设: {q.hypothesis}")
            if q.data_sources:
                print(f"      数据源: {', '.join(q.data_sources)}")
            if q.keywords:
                print(f"      关键词: {', '.join(q.keywords)}")
            for j, child in enumerate(q.children, 1):
                print(f"      Q{i}.{j}: {child.question}")
                if child.hypothesis:
                    print(f"            假设: {child.hypothesis}")
                if child.data_sources:
                    print(f"            数据源: {', '.join(child.data_sources)}")
    else:
        print("  (空)")
    print()

    # MECE 验证
    validation = tree.validate_mece()
    print("─" * 60)
    print("MECE 验证：")
    print("─" * 60)
    print(f"  是否满足 MECE: {'✅ 是' if validation.get('is_mece') else '⚠️ 否'}")
    print(f"  重叠度评分: {validation.get('overlap_score', 0):.2f}")
    print(f"  覆盖度评分: {validation.get('coverage_score', 0):.2f}")
    print(f"  总问题数: {validation.get('total_questions', 0)}")
    print(f"  叶子问题: {validation.get('leaf_questions', 0)}")
    print(f"  最大深度: {validation.get('max_depth', 0)}")
    if validation.get('issues'):
        print("  问题：")
        for issue in validation['issues']:
            print(f"    - {issue}")
    if validation.get('suggestions'):
        print("  建议：")
        for sug in validation['suggestions']:
            print(f"    - {sug}")
    print()

    # Mermaid 图
    mermaid = tree.to_mermaid()
    if mermaid and mermaid != "graph TD":
        print("─" * 60)
        print("Mermaid 问题树图：")
        print("─" * 60)
        print(mermaid)
        print()

    # v6.0：待确认清单（计划确认门输入，供用户增删子问题/调整深度）
    from plan import resolve_preset_key, DEPTH_TO_EFFORT
    preset_key = resolve_preset_key(args.effort, args.depth)
    effort = DEPTH_TO_EFFORT[preset_key]
    breadth = args.breadth or {'quick': 2, 'standard': 4, 'deep': 8, 'exhaustive': 12}.get(effort, 4)
    print("─" * 60)
    print("📋 待确认清单（计划确认门）：")
    print("─" * 60)
    print(f"  建议 effort: {effort}{'（--effort 指定）' if args.effort else f'（{args.depth} 深度）'}")
    print(f"  建议 breadth（并行子主题数）: {breadth}")
    pv = [', '.join(q.perspectives) for q in plan.issue_tree if q.perspectives] or ['(默认域专家/怀疑者/实践者)']
    print(f"  专家团视角: {'; '.join(dict.fromkeys(pv))}")
    print(f"  子问题（共 {len(plan.unanswered_questions)} 个待执行主题）:")
    for i, q in enumerate(plan.unanswered_questions, 1):
        print(f"    {i}. {q}")
    if plan.dropped_dimensions:
        # 丢弃告警原先只在 stderr：Lead 只看 stdout（或 `| tail`）就会以为维度齐了
        print(f"  ⚠️ 被档位上限丢弃的维度（{len(plan.dropped_dimensions)} 个）："
              f"{'、'.join(plan.dropped_dimensions)} —— 需要它们就提高 --effort/--depth")
    print("  提示: 可增删子问题、调整 --depth/--effort/--breadth/--perspectives，批准后再执行搜索。")

    # 保存计划
    if args.output:
        plan.save(args.output)
        print(f"💾 计划已保存到: {args.output}")


# ============================================================
# 命令：默认搜索（v4 模式）
# ============================================================

def _extract_claim_texts(obj_list, attr='statement'):
    """从 Claim 对象列表或 dict 列表提取文本（兼容缓存命中与新鲜验证结果）。"""
    out = []
    for c in obj_list or []:
        v = getattr(c, attr, None) if not isinstance(c, dict) else c.get(attr, '')
        if v:
            out.append(str(v))
    return out


def _ledger_summary(written) -> str:
    n_drop = written.get('dropped', 0)
    tail = f"，{n_drop} 条命中点不回原文已丢弃" if n_drop else ''
    if not written['claims']:
        return (f"{written['evidence']} 条证据（未建 claim——读完内容用 add-claim 立论；"
                f"沿用旧行为加 --auto-claim）{tail}")
    return (f"{written['evidence']} 条证据 + {written['claims']} 条 auto-claim"
            f"（按交叉验证分流 status）{tail}")


def _write_ledger(ledger, results, verification, query, auto_claim: bool = False):
    """搜索结果落盘（v6.10：默认只登记证据，不再自动生成 claim）。

    引擎给回的标题是别人页面的标题，不是本调研的论断。实测把 `--ledger` 打开跑
    4 个 session，子 Agent 自报约 391 条 claim，merge 后变 602 条——多出来的几乎
    全是 5 星空仓库名与培训班广告，它们却进了覆盖率与引用统计。
    claim 现在必须由 Lead/子 Agent 读完内容后 add-claim 显式立论。

    auto_claim=True 保留旧行为（按交叉验证结果分流 status）：
    - 命中 verified_claims（≥2 独立来源）→ 'verified'
    - 命中 contradictions → 'conflict'
    - 命中 single_source_claims 或未命中 → 'pending'
    """
    if ledger is None:
        return {'claims': 0, 'evidence': 0, 'dropped': 0}
    ver = verification if verification is not None else None
    if isinstance(ver, dict):
        verified_texts = _extract_claim_texts(ver.get('verified_claims'))
        single_texts = _extract_claim_texts(ver.get('single_source_claims'))
        conflict_texts = []
        for con in ver.get('contradictions') or []:
            ca = con.get('claim_a', '') if isinstance(con, dict) else ''
            cb = con.get('claim_b', '') if isinstance(con, dict) else ''
            conflict_texts += [str(ca), str(cb)]
    elif ver is not None:
        verified_texts = _extract_claim_texts(getattr(ver, 'verified_claims', []))
        single_texts = _extract_claim_texts(getattr(ver, 'single_source_claims', []))
        conflict_texts = []
        for con in getattr(ver, 'contradictions', []) or []:
            conflict_texts += [str(getattr(con, 'claim_a', '')),
                               str(getattr(con, 'claim_b', ''))]
    else:
        verified_texts, single_texts, conflict_texts = [], [], []

    def _match(text, pool):
        t = str(text).strip()
        for p in pool:
            if t and (t in p or p in t):
                return True
        return False

    written = {'claims': 0, 'evidence': 0, 'dropped': 0}
    for r in results:
        try:
            title = r.title if hasattr(r, 'title') else r.get('title', '')
            url = r.url if hasattr(r, 'url') else r.get('url', '')
            craap = r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {})
            if not isinstance(craap, dict):
                craap = {}
            text = title or ''
            if not text:
                content = (r.content if hasattr(r, 'content')
                           else (r.get('content', '') if isinstance(r, dict) else ''))
                text = str(content)[:80] or '(无标题)'
            engine = (getattr(r, 'engine', '')
                      or (r.get('engine', '') if isinstance(r, dict) else '')) or ''
            ev = ledger.add_evidence(url=url, title=title, query=query, engine=engine,
                                     tier=craap.get('tier'),
                                     craap_score=craap.get('total'))
            if ev is not None:
                written['evidence'] += 1
            elif not auto_claim:
                written['dropped'] += 1     # 点不回原文的命中不入账，只记个数
            if not auto_claim:
                continue
            if _match(text, conflict_texts):
                status = 'conflict'
                conf = 0.3
            elif _match(text, verified_texts):
                status = 'verified'
                conf = 0.8
            elif _match(text, single_texts):
                status = 'pending'      # 单源：待交叉验证
                conf = 0.4
            else:
                status = 'pending'      # v6.3：未验证一律 pending
                conf = 0.4
            claim = ledger.add_claim(
                claim=str(text), topic=query, status=status,
                perspective='engine', confidence=conf,
                note='auto: from search results (status by cross-verification)')
            if url:
                ledger.add_source(
                    claim['id'], str(url), str(title),
                    tier=craap.get('tier') if craap else None,
                    craap_score=craap.get('total') if craap else None)
            written['claims'] += 1
        except Exception as e:
            print(f"⚠️ 账本写入失败: {e}", file=sys.stderr)
    return written


def cmd_search(args, registry):
    """v4 搜索模式"""
    from cache import LRUCache
    from score import CraapScorer
    from verify import CrossVerifier
    from report import ReportGenerator

    # 0. 断路器接线（惰性 router，失败容忍）
    breaker_router = None
    try:
        from router import QueryRouter
        breaker_router = QueryRouter()
    except Exception:
        breaker_router = None

    # 1. 缓存检查（v6.3：key 含 ledger/effort/breadth/perspectives/reflect 参数，
    #    防止带账本的二跑命中旧缓存导致账本为空）
    cache = LRUCache()
    cache_key = LRUCache.make_key(
        args.query, sources=args.sources,
        language=args.language, region=args.region,
        depth=args.depth,
        ledger=bool(args.ledger), effort=args.effort,
        breadth=args.breadth, perspectives=getattr(args, 'perspectives', None),
        reflect_rounds=args.reflect_rounds,
    )
    if not args.no_cache:
        cached = cache.get(cache_key)
        if cached:
            print(f"✅ 缓存命中（key: {cache_key[:8]}...）", file=sys.stderr)
            # v6.3：缓存命中也落盘（此前直接 return 导致 --ledger 二跑账本为空）
            ledger = None
            if args.ledger:
                from ledger import ResearchLedger
                ledger = ResearchLedger(args.ledger).init()
                n = _write_ledger(ledger, cached.get('results', []),
                                  cached.get('verification'), args.query,
                                  auto_claim=args.auto_claim)
                print(f"📒 落盘（缓存结果）：{_ledger_summary(n)}", file=sys.stderr)
            _output_results(cached, args)
            return

    # 2. 生成计划（除非 --no-plan；v6.3：透传 perspectives/goal/dimensions/time_range）
    plan = None
    if not args.no_plan:
        from plan import PlanGenerator
        gen = PlanGenerator()
        _persp = None
        if getattr(args, 'perspectives', None) == '0':
            _persp = []
        elif getattr(args, 'perspectives', None):
            _persp = [p.strip() for p in args.perspectives.split(',')]
        plan = gen.generate_plan(
            topic=args.query,
            goal=getattr(args, 'goal', '') or '',
            depth=args.depth,
            effort=args.effort,
            dimensions=(args.dimensions.split(',')
                        if getattr(args, 'dimensions', None) else None),
            time_range=getattr(args, 'time_range', '') or '',
            language=args.language or 'auto',
            region=getattr(args, 'region', '') or '',
            perspectives=_persp,
        )
        print(f"📋 MECE 计划已生成（{len(plan.issue_tree)} 个子问题）",
              file=sys.stderr)

    # v6.0：证据账本（可选，--ledger 指定目录）
    ledger = None
    if args.ledger:
        from ledger import ResearchLedger
        ledger = ResearchLedger(args.ledger).init()
        print(f"📒 证据账本已初始化: {args.ledger}", file=sys.stderr)

    # 3. 执行搜索（按降级链）
    chain = registry.get_fallback_chain()
    if not chain:
        print("❌ 无可用引擎！请运行 --mcp-check 检查配置", file=sys.stderr)
        sys.exit(1)

    all_results = []
    used_engines = []
    empty_engines = []      # 调通但 0 结果
    unavailable = []        # 返回 None / 抛异常
    # 用户显式 --sources 点名的引擎即使不声明 search 能力也照样调用（如 modelscope 详情查询）
    explicit_sources = {s.strip() for s in args.sources.split(',')} if args.sources else set()

    # 如果指定了 --sources，过滤引擎
    if args.sources:
        source_names = [s.strip() for s in args.sources.split(',')]
        chain = [e for e in chain if e.get_name() in source_names]
        if not chain:
            # 尝试 v3 兼容映射
            v3_to_v4 = {
                'baidu': 'baidu-html', 'bing': 'bing-html',
                'duckduckgo': 'duckduckgo',
            }
            mapped = [v3_to_v4.get(s, s) for s in source_names]
            chain = [e for e in registry.get_fallback_chain() if e.get_name() in mapped]
            if chain:
                print(f"⚠️ v3 引擎名自动映射到 v4 Layer 4（建议配置 MCP）", file=sys.stderr)
                print(f"💡 运行 setup-mcp.sh --core 配置免费 MCP", file=sys.stderr)
    elif getattr(args, 'auto_route', False):
        # v5.0 智能路由：自动根据查询意图选择引擎链
        try:
            from router import QueryRouter
            router = QueryRouter()
            decision = router.route(args.query, {})
            route_names = set(decision.engine_chain)
            # 断路器过滤
            filtered_names = set(router.filter_engines_by_breaker(decision.engine_chain))
            type_labels = {
                'academic': '学术论文', 'opensource': '开源项目', 'community': '社区口碑',
                'docs': '技术文档', 'news': '时效新闻', 'general': '通用搜索',
                'definition': '定义解释', 'guide': '操作指南', 'comparison': '对比分析',
            }
            print(f"🧭 智能路由: {decision.query_type}（{type_labels.get(decision.query_type, '')}）"
                  f" 置信度={decision.confidence:.0%}", file=sys.stderr)
            print(f"   引擎链: {', '.join(decision.engine_chain)}", file=sys.stderr)
            # 过滤出可用引擎
            routed_chain = [e for e in chain if e.get_name() in filtered_names]
            if routed_chain:
                chain = routed_chain
            else:
                # 路由推荐的引擎都不可用，降级到默认链
                print(f"⚠️ 路由推荐引擎均不可用，降级到默认降级链", file=sys.stderr)
        except ImportError:
            print(f"⚠️ 智能路由模块未找到（router.py），使用默认降级链", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ 智能路由失败: {e}，使用默认降级链", file=sys.stderr)

    # 搜索（取第一个可用引擎或聚合多个；v6.3：断路器接线——
    #     OPEN 的引擎跳过，成功/失败记账，恢复走 HALF_OPEN 试探）
    def _breaker_ok(name):
        if breaker_router is None:
            return True
        try:
            return breaker_router.get_breaker(name).can_call()
        except Exception:
            return True

    def _breaker_record(name, ok):
        if breaker_router is None:
            return
        try:
            b = breaker_router.get_breaker(name)
            b.record_success() if ok else b.record_failure()
        except Exception:
            pass

    if args.all:
        # 搜索所有可用引擎
        for engine in chain:
            name = engine.get_name()
            if not engine.has_capability('search') and name not in explicit_sources:
                continue
            if not _breaker_ok(name):
                print(f"⚡ 断路器 OPEN，跳过: {name}", file=sys.stderr)
                continue
            print(f"🔍 搜索中: {name}...", file=sys.stderr)
            try:
                results = engine.search(args.query, max_results=args.limit)
                if results is None:
                    # 基类契约：None = 引擎没取到数据（依赖/鉴权/契约变更）
                    _breaker_record(name, False)
                    unavailable.append(name)
                elif results:
                    _breaker_record(name, True)
                    all_results.extend(results)
                    used_engines.append(name)
                else:
                    _breaker_record(name, True)
                    empty_engines.append(name)
            except Exception as e:
                _breaker_record(name, False)
                unavailable.append(name)
                print(f"⚠️ {name} 搜索失败: {e}", file=sys.stderr)
    else:
        # 按降级链搜索，命中即停（或聚合前 N 个）
        for engine in chain:
            name = engine.get_name()
            if not engine.has_capability('search') and name not in explicit_sources:
                continue
            if not _breaker_ok(name):
                print(f"⚡ 断路器 OPEN，跳过: {name}", file=sys.stderr)
                continue
            print(f"🔍 搜索中: {name}...", file=sys.stderr)
            try:
                results = engine.search(args.query, max_results=args.limit)
                if results is None:
                    _breaker_record(name, False)
                    unavailable.append(name)
                    continue
                _breaker_record(name, True)
                if results:
                    all_results.extend(results)
                    used_engines.append(name)
                    if len(all_results) >= args.limit:
                        break
                else:
                    empty_engines.append(name)
            except Exception as e:
                _breaker_record(name, False)
                unavailable.append(name)
                print(f"⚠️ {name} 搜索失败: {e}", file=sys.stderr)

    if not all_results:
        # v6.5：如实区分「调通了但 0 结果」与「引擎没取到数据」，
        # 不再把两者的失败统一甩锅成"所有引擎都不可用，请运行 --mcp-check"
        print("❌ 未找到结果", file=sys.stderr)
        if empty_engines:
            print(f"⚠️ 已调通但 0 结果: {', '.join(empty_engines)}"
                  f"（查询词过窄 / 端点契约变更）", file=sys.stderr)
        if unavailable:
            print(f"❌ 未取到数据: {', '.join(unavailable)}", file=sys.stderr)
        print("💡 先跑 --probe 看哪些引擎今天真的出得来数据，再调整 --sources 或查询词",
              file=sys.stderr)
        sys.exit(1)

    print(f"📊 找到 {len(all_results)} 条结果（来自 {len(used_engines)} 个引擎）", file=sys.stderr)

    # 4. CRAAP 评分
    scorer = CraapScorer()
    for r in all_results:
        try:
            r.craap_score = scorer.score(r, query=args.query, enable_llm=args.llm_score)
        except Exception as e:
            print(f"⚠️ CRAAP 评分失败: {e}", file=sys.stderr)

    # 5. 过滤低分
    if args.min_score > 0:
        before = len(all_results)
        all_results = [r for r in all_results if r.craap_score and r.craap_score.get('total', 0) >= args.min_score]
        print(f"🎯 过滤后: {len(all_results)}/{before} 条（min_score={args.min_score}）", file=sys.stderr)

    # 5b. 相关性过滤（v6.5）：无关结果不得静默混进报告
    #     （实测：中文查询 "向量数据库 开源" 曾带回土地覆盖/图像质量论文，
    #       总分 60-68 却无一条被拦，因为总分把"权威/时效"和"相关"混加权了）
    all_results, dropped, weak = filter_by_relevance(
        all_results, args.min_relevance, args.limit)
    if dropped:
        print(f"🎯 相关性过滤：丢弃 {dropped} 条（relevance < {args.min_relevance}）",
              file=sys.stderr)
    elif weak:
        print(f"⚠️ {weak} 条与查询词几乎无重叠（relevance < {args.min_relevance}），"
              f"因高相关结果不足而保留 —— 结论不得只靠它们，建议换查询词或补 --sources",
              file=sys.stderr)

    # 6. 交叉验证
    verifier = CrossVerifier()
    verification = verifier.verify(all_results, query=args.query)
    print(f"✓ 交叉验证: {len(verification.verified_claims)} 已验证, "
          f"{len(verification.single_source_claims)} 单源, "
          f"{len(verification.contradictions)} 矛盾",
          file=sys.stderr)

    # 6.5 落盘证据账本（v6.3：前移到反思循环之前——
    #     此前落盘在反思之后导致 evidence_sufficient/marginal 恒读空账本）
    if ledger:
        written = _write_ledger(ledger, all_results, verification, args.query,
                                auto_claim=args.auto_claim)
        print(f"📒 落盘：{_ledger_summary(written)}", file=sys.stderr)

    # 7. 反思循环（如果 --reflect-rounds > 0；账本已就绪，证据充分性停止生效）
    reflections = []
    if args.reflect_rounds > 0 and plan:
        from reflect import Reflector
        reflector = Reflector(max_rounds=args.reflect_rounds)
        prev_claims = None
        for round_num in range(1, args.reflect_rounds + 1):
            reflection = reflector.reflect(plan, all_results, round_num, verification,
                                           ledger=ledger, previous_claim_count=prev_claims)
            reflections.append(reflection)
            print(f"🔄 反思轮 {round_num}: 覆盖率 {reflection.coverage_score:.0%}, "
                  f"{'需 Drill-down' if reflection.should_drill_down else '停止: ' + (reflection.stop_reason or '')}",
                  file=sys.stderr)
            if not reflection.should_drill_down:
                break
            if ledger is not None:
                prev_claims = len(ledger.claims())

    # 8. 准备输出数据（所有对象转为可 JSON 序列化的字典）
    def _to_dict_safe(obj):
        """安全转为字典（用于 JSON 序列化）"""
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        elif hasattr(obj, '__dict__'):
            return {k: _to_dict_safe(v) for k, v in obj.__dict__.items()}
        elif isinstance(obj, list):
            return [_to_dict_safe(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: _to_dict_safe(v) for k, v in obj.items()}
        else:
            return obj

    output_data = {
        'query': args.query,
        'depth': args.depth,
        'plan': _to_dict_safe(plan) if plan else None,
        'results': [r.to_dict() if hasattr(r, 'to_dict') else _to_dict_safe(r) for r in all_results],
        'verification': _to_dict_safe(verification),
        'reflections': [_to_dict_safe(r) for r in reflections],
        'used_engines': used_engines,
    }

    # 9. 缓存
    if not args.no_cache:
        cache.set(cache_key, output_data)
        print(f"💾 已缓存（key: {cache_key[:8]}...）", file=sys.stderr)

    # v6.0：组装调研元信息（报告头显示）
    options = None
    if args.effort or args.breadth or args.perspectives:
        options = {}
        if args.effort:
            options['effort'] = args.effort
        if args.breadth:
            options['breadth'] = args.breadth
        if args.depth:
            options['depth'] = args.depth
        if args.perspectives:
            options['perspectives'] = args.perspectives

    # 10. 输出
    _output_results(output_data, args, plan, all_results, verification, reflections,
                    options=options, ledger=ledger)


def _output_results(data, args, plan=None, results=None, verification=None, reflections=None,
                    options=None, ledger=None):
    """输出结果（v6.0：options/ledger 透传到报告生成）"""
    format = args.format

    def emit(text: str):
        """文本产物一律认 -o：以前只有 html 认，`--format json -o x.json` 会静默不落盘。"""
        if args.output:
            Path(args.output).write_text(text, encoding='utf-8')
            print(f'💾 {format} 输出已保存: {args.output}', file=sys.stderr)
        else:
            print(text)

    if format == 'json':
        emit(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return

    if format == 'csv':
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow(['title', 'url', 'source', 'craap_total', 'craap_grade', 'published_date'])
        for r in (results or data.get('results', [])):
            craap = r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {}) or {}
            writer.writerow([
                r.title if hasattr(r, 'title') else r.get('title', ''),
                r.url if hasattr(r, 'url') else r.get('url', ''),
                r.source if hasattr(r, 'source') else r.get('source', ''),
                craap.get('total', '') if isinstance(craap, dict) else '',
                craap.get('grade', '') if isinstance(craap, dict) else '',
                r.published_date if hasattr(r, 'published_date') else r.get('published_date', ''),
            ])
        emit(buf.getvalue())
        return

    if format == 'markdown':
        if plan and results:
            from report import ReportGenerator
            reporter = ReportGenerator()
            md = reporter.generate(plan, results, verification, reflections,
                                   format='markdown', ledger=ledger, options=options)
            emit(md)
        else:
            # 简单 markdown（无 plan 时）
            lines = [f"# {data['query']}\n"]
            for r in data.get('results', []):
                lines.append(f"## {r.get('title', '')}")
                lines.append(f"URL: {r.get('url', '')}")
                lines.append(f"来源: {r.get('source', '')}")
                craap = r.get('craap_score', {}) or {}
                if craap:
                    lines.append(f"CRAAP: {craap.get('total', 0)}/100 ({craap.get('grade', '-')})")
                lines.append(f"\n{r.get('content', '')}\n")
            emit('\n'.join(lines))
        return

    if format == 'html':
        if plan and results:
            # 完整 HTML 报告（含 Mermaid 图表、CRAAP 评分表；v6.0 含证据账本附录）
            from report import ReportGenerator
            reporter = ReportGenerator()
            html = reporter.generate(plan, results, verification, reflections,
                                     format='html', ledger=ledger, options=options)
        elif results:
            # 简单 HTML 报告（无 plan，仅展示搜索结果）
            html = _generate_simple_html(data, results, verification)
        else:
            html = "<html><body><h1>无数据</h1></body></html>"

        if args.output:
            Path(args.output).write_text(html, encoding='utf-8')
            print(f"💾 HTML 报告已保存: {args.output}", file=sys.stderr)
        else:
            print(html)
        return

    # 默认 JSON
    emit(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _generate_simple_html(data, results, verification=None):
    """生成简单 HTML 报告（无 MECE 计划时使用）"""
    import html as html_lib

    query = data.get('query', '')
    used_engines = data.get('used_engines', [])

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='zh-CN'>",
        "<head>",
        "<meta charset='UTF-8'>",
        f"<title>{html_lib.escape(query)} — 深度调研报告</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "max-width: 900px; margin: 0 auto; padding: 20px; line-height: 1.6; color: #333; }",
        "h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }",
        ".result { background: #f9f9f9; border-left: 4px solid #3498db; padding: 15px; margin: 15px 0; }",
        ".result h3 { margin-top: 0; color: #2c3e50; }",
        ".meta { color: #7f8c8d; font-size: 0.9em; margin-bottom: 10px; }",
        ".craap { display: inline-block; background: #e8f5e9; color: #2e7d32; "
        "padding: 2px 8px; border-radius: 3px; font-size: 0.85em; }",
        ".content { margin-top: 10px; }",
        ".engines { background: #fff3e0; padding: 10px; border-radius: 4px; margin: 20px 0; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>🔍 {html_lib.escape(query)}</h1>",
        f"<div class='engines'>📊 使用引擎: {', '.join(used_engines)} | 结果数: {len(results)}</div>",
    ]

    if verification:
        verified = len(getattr(verification, 'verified_claims', []) or [])
        single = len(getattr(verification, 'single_source_claims', []) or [])
        contra = len(getattr(verification, 'contradictions', []) or [])
        html_parts.append(
            f"<div class='engines'>✓ 交叉验证: {verified} 已验证, {single} 单源, {contra} 矛盾</div>"
        )

    for i, r in enumerate(results, 1):
        title = getattr(r, 'title', '') or (r.get('title', '') if isinstance(r, dict) else '')
        url = getattr(r, 'url', '') or (r.get('url', '') if isinstance(r, dict) else '')
        source = getattr(r, 'source', '') or (r.get('source', '') if isinstance(r, dict) else '')
        content = getattr(r, 'content', '') or (r.get('content', '') if isinstance(r, dict) else '')
        craap = getattr(r, 'craap_score', None) or (r.get('craap_score', {}) if isinstance(r, dict) else {})
        craap_total = craap.get('total', 0) if isinstance(craap, dict) else 0
        craap_grade = craap.get('grade', '') if isinstance(craap, dict) else ''

        html_parts.append(f"<div class='result'>")
        html_parts.append(f"<h3>{i}. {html_lib.escape(title)}</h3>")
        html_parts.append(f"<div class='meta'>")
        html_parts.append(f"🔗 <a href='{html_lib.escape(url)}' target='_blank'>{html_lib.escape(url)}</a><br>")
        html_parts.append(f"📡 来源: {html_lib.escape(source)}")
        if craap_total:
            html_parts.append(f" | <span class='craap'>CRAAP: {craap_total}/100 ({craap_grade})</span>")
        html_parts.append(f"</div>")
        if content:
            # 截取前 500 字符避免过长
            display_content = content[:500] + ('...' if len(content) > 500 else '')
            html_parts.append(f"<div class='content'>{html_lib.escape(display_content)}</div>")
        html_parts.append(f"</div>")

    html_parts.extend([
        "<hr>",
        f"<p style='color:#999;font-size:0.85em;text-align:center;'>"
        f"Generated by Deep Research Ultra v{skill_version()} — {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>",
        "</body>",
        "</html>",
    ])

    return '\n'.join(html_parts)


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Deep Research Ultra v5.0 — 深度调研工具（智能路由 + 学术直连 + 反爬虫升级）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
v5.0 四阶段工作流: Plan → Execute → Synthesize → Reflect
四层数据源: MCP + 学术直连 → Skill → 内置 → 降级（curl_cffi TLS 伪装）
v5.0 新增: 智能路由(--auto-route) | 学术直连引擎(OpenAlex/S2/PubMed) | 反爬虫升级

示例:
  %(prog)s "深度调研 2025 年 AI Agent 框架"
  %(prog)s "最新 LLM 论文" --auto-route
  %(prog)s "RAG 开源实现" --route
  %(prog)s "FastAPI vs Django" --depth standard --format html
  %(prog)s "大语言模型微调" --depth deep --reflect-rounds 3
  %(prog)s "RAG 最佳实践" --plan-only
  %(prog)s --mcp-check
  %(prog)s --list

v3 兼容（自动降级到 Layer 4）:
  %(prog)s "AI" --sources baidu,bing,duckduckgo --format markdown

详细文档: references/optimization-plan-v5.md
        """
    )

    # 位置参数
    parser.add_argument('query', nargs='?', default='',
                        help='调研主题或搜索关键词')

    # 深度与策略
    parser.add_argument('--depth', '-d', default='standard',
                        choices=['quick', 'standard', 'deep', 'extreme'],
                        help='调研深度（quick=2-3子问题, standard=4-6, deep=7-10, extreme=10+）')
    # v6.0：努力程度分级（映射 depth + breadth 上限）
    parser.add_argument('--effort', default=None,
                        choices=['quick', 'standard', 'deep', 'exhaustive'],
                        help='v6.0 努力程度（quick=1轮检索跳过专家团 ... exhaustive=red-team对抗评审）')
    parser.add_argument('--breadth', type=int, default=0,
                        help='v6.0 并行子主题数（0=随 effort 自动；供主 Agent 并行派发参考）')
    parser.add_argument('--auto-claim', action='store_true',
                        help='把每条搜索结果的标题自动写成一条 claim（默认关闭：标题是'
                             '别人页面的标题而不是本调研的论断，会灌进 5 星空仓库与广告'
                             '噪声并虚高覆盖率；只在复现 v6.9 及以前行为时用）')
    parser.add_argument('--ledger', default=None,
                        help='v6.0 证据账本目录（.research/session/ledger），搜索结果落盘并用于反思/报告')
    parser.add_argument('--perspectives', default=None,
                        help='v6.0 专家团视角，逗号分隔（如 domain_expert,skeptic,practitioner；"0" 关闭）')
    parser.add_argument('--reflect-rounds', type=int, default=1,
                        help='反思循环轮数（0=禁用, 1=默认, 3=深度模式）')
    parser.add_argument('--goal', help='调研目标（明确目标可跳过澄清）')
    parser.add_argument('--dimensions', help='调研维度，逗号分隔（如：性能,生态,案例）')
    parser.add_argument('--time-range', help='时间范围（如：2024-2025, 近1年）')
    parser.add_argument('--language', help='查询语言（auto/zh/en）')
    parser.add_argument('--region', help='查询区域（cn/global）')

    # 数据源
    parser.add_argument('--sources', '-s',
                        help='指定数据源，逗号分隔（v3 引擎名自动映射到 Layer 4）')
    parser.add_argument('--all', '-a', action='store_true',
                        help='搜索所有可用引擎（聚合模式）')
    parser.add_argument('--no-plan', action='store_true',
                        help='跳过 MECE 计划生成（快速搜索模式）')
    parser.add_argument('--auto-route', action='store_true',
                        help='v5.0 智能路由：自动根据查询意图选择数据源（学术→论文引擎，开源→GitHub，理论+联网+实际）')
    parser.add_argument('--route', action='store_true',
                        help='v5.0 仅展示路由分析结果（不执行搜索）')

    # 输出
    parser.add_argument('--format', '-f', default='html',
                        choices=['html', 'markdown', 'json', 'csv'],
                        help='输出格式（v4 默认 html，含 Mermaid 图表）')
    parser.add_argument('--output', '-o',
                        help='输出文件路径（html 格式推荐）')
    parser.add_argument('--limit', '-n', type=int, default=10,
                        help='每个引擎最大结果数')

    # 评分
    parser.add_argument('--min-score', type=float, default=0,
                        help='最低 CRAAP 总分（0-100），低于此分过滤')
    parser.add_argument('--min-relevance', type=float, default=50,
                        help='最低 CRAAP 相关性分（0-100），高相关结果够数时丢弃低相关结果；0=关闭')
    parser.add_argument('--llm-score', action='store_true',
                        help='启用 LLM 语义评分（更准确，消耗 token）')

    # 缓存
    parser.add_argument('--no-cache', action='store_true',
                        help='禁用缓存')

    # 工具命令
    parser.add_argument('--mcp-check', action='store_true',
                        help='MCP 健康检查')
    parser.add_argument('--probe', action='store_true',
                        help='引擎功能自检：真实发探针查询，验证引擎今天是否出得来数据')
    parser.add_argument('--probe-query', default=None,
                        help='覆盖探针查询词（默认按引擎定制，见 probe.py 的 PROBE_QUERIES）')
    parser.add_argument('--theme-query', action='append', default=None, metavar='查询词',
                        help='主题级预演：把 Lead 本维度真要派出去的查询词逐条打一次（可重复），'
                             '须配 --sources；区分"引擎活着"与"对本主题到得到数据"')
    parser.add_argument('--allow-degraded', action='store_true',
                        help='--probe 环境闸门不足时仍放行（默认退出码 3 停住，先配环境再调研）')
    # v6.1: 环境分级门控
    parser.add_argument('--env-check', action='store_true',
                        help='环境分级验证（minimal/opensource/academic/full）')
    parser.add_argument('--env-profile', default='full',
                        choices=['minimal', 'opensource', 'academic', 'full'],
                        help='环境验证 profile（v6.1，默认 full）')
    parser.add_argument('--no-net', action='store_true',
                        help='跳过网络连通性探测（--env-check 用）')
    parser.add_argument('--list', '-l', action='store_true',
                        help='列出所有引擎（四层架构）')
    parser.add_argument('--plan-only', action='store_true',
                        help='仅生成 MECE 计划，不执行搜索')
    parser.add_argument('--proxy', help='HTTP 代理地址')

    args = parser.parse_args()

    # 设置代理
    if args.proxy:
        os.environ['HTTP_PROXY'] = args.proxy
        os.environ['HTTPS_PROXY'] = args.proxy
        print(f"🌐 使用代理: {args.proxy}", file=sys.stderr)

    # 构建引擎注册表
    registry = build_registry()

    # 命令分发
    if args.mcp_check:
        cmd_mcp_check(registry)
        return

    if args.env_check:
        cmd_env_check(args)
        return

    if args.probe or args.theme_query:
        cmd_probe(registry, args)
        return

    if args.list:
        cmd_list(registry)
        return

    if args.route:
        if not args.query:
            print("❌ --route 需要指定查询", file=sys.stderr)
            sys.exit(1)
        cmd_route(args, registry)
        return

    if args.plan_only:
        if not args.query:
            print("❌ --plan-only 需要指定调研主题", file=sys.stderr)
            sys.exit(1)
        cmd_plan_only(args)
        return

    if not args.query:
        parser.print_help()
        return

    # 默认：执行搜索
    cmd_search(args, registry)


if __name__ == '__main__':
    from console import force_utf8
    force_utf8()
    main()
