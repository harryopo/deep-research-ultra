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
    """MCP 健康检查"""
    print("=" * 60)
    print("Deep Research Ultra v4.0 — MCP 健康检查")
    print("=" * 60)
    print()

    mcp_engines = registry.get_by_layer(1, only_available=False)
    if not mcp_engines:
        print("⚠️ 未注册任何 MCP 引擎")
        return

    available_count = 0
    for engine in mcp_engines:
        m = engine.metadata
        status = "✅ 可用" if engine.is_available() else "❌ 不可用"
        reason = ""
        if not engine.is_available():
            if m.requires_config:
                missing = [k for k in m.config_keys if not os.environ.get(k)]
                if missing:
                    reason = f"（缺少环境变量: {', '.join(missing)}）"
                else:
                    reason = "（命令不可执行）"
            else:
                reason = "（未配置）"
        print(f"  {status}  {m.name:<20} {m.description}")
        if reason:
            print(f"           {reason}")
        if engine.is_available():
            available_count += 1

    print()
    print(f"总计: {available_count}/{len(mcp_engines)} 个 MCP 可用")

    if available_count == 0:
        print()
        print("💡 建议运行一键配置脚本（免费 MCP）：")
        print("   bash scripts/setup-mcp.sh --core")
    elif available_count < len(mcp_engines):
        print()
        print("💡 如需解锁全部 MCP，运行：")
        print("   bash scripts/setup-mcp.sh --all")


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
    available_engines = registry.get_available()
    available_names = {e.get_name() for e in available_engines}
    for i, eng_name in enumerate(decision.engine_chain, 1):
        status = "✅" if eng_name in available_names else "❌"
        engine = registry.get(eng_name)
        desc = engine.metadata.description[:50] if engine else "(未注册)"
        print(f"   {i}. {status} {eng_name:<20} {desc}")
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

    print("💡 使用以下命令执行调研:")
    print(f"   python research.py \"{args.query}\" --sources {','.join(filtered[:5])}")
    print(f"   或直接运行（自动路由）:")
    print(f"   python research.py \"{args.query}\" --auto-route")


# ============================================================
# 命令：--list
# ============================================================

def cmd_list(registry):
    """列出所有引擎"""
    print("=" * 80)
    print("Deep Research Ultra v4.0 — 引擎清单（四层架构）")
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
            status = "✅" if engine.is_available() else "❌"
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

    # 降级链
    chain = registry.get_fallback_chain()
    print("降级链（按优先级）：")
    print("  " + " → ".join(e.get_name() for e in chain))
    print()

    summary = registry.summary()
    print(f"总计: {summary['total']} 个引擎，{summary['available']} 个可用")
    print(f"  Layer 1: {summary['by_layer'][1]}  Layer 2: {summary['by_layer'][2]}  "
          f"Layer 3: {summary['by_layer'][3]}  Layer 4: {summary['by_layer'][4]}")


# ============================================================
# 命令：--plan-only
# ============================================================

def cmd_plan_only(args):
    """仅生成 MECE 计划"""
    from plan import PlanGenerator, IssueTree

    gen = PlanGenerator()
    plan = gen.generate_plan(
        topic=args.query,
        goal=args.goal or '',
        depth=args.depth,
        dimensions=args.dimensions.split(',') if args.dimensions else None,
        time_range=args.time_range or '',
        language=args.language or 'auto',
        region=args.region or '',
    )

    # 构建 IssueTree 对象以便验证和可视化
    tree = IssueTree()
    tree.roots = list(plan.issue_tree)

    print("=" * 60)
    print("Deep Research Ultra v4.0 — MECE 调研计划")
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

    # 保存计划
    if args.output:
        plan.save(args.output)
        print(f"💾 计划已保存到: {args.output}")


# ============================================================
# 命令：默认搜索（v4 模式）
# ============================================================

def cmd_search(args, registry):
    """v4 搜索模式"""
    from cache import LRUCache
    from score import CraapScorer
    from verify import CrossVerifier
    from report import ReportGenerator

    # 1. 缓存检查
    cache = LRUCache()
    cache_key = LRUCache.make_key(
        args.query, sources=args.sources,
        language=args.language, region=args.region,
        depth=args.depth,
    )
    if not args.no_cache:
        cached = cache.get(cache_key)
        if cached:
            print(f"✅ 缓存命中（key: {cache_key[:8]}...）", file=sys.stderr)
            _output_results(cached, args)
            return

    # 2. 生成计划（除非 --no-plan）
    plan = None
    if not args.no_plan:
        from plan import PlanGenerator
        gen = PlanGenerator()
        plan = gen.generate_plan(
            topic=args.query,
            depth=args.depth,
            language=args.language or 'auto',
        )
        print(f"📋 MECE 计划已生成（{len(plan.issue_tree)} 个子问题）",
              file=sys.stderr)

    # 3. 执行搜索（按降级链）
    chain = registry.get_fallback_chain()
    if not chain:
        print("❌ 无可用引擎！请运行 --mcp-check 检查配置", file=sys.stderr)
        sys.exit(1)

    all_results = []
    used_engines = []

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

    # 搜索（取第一个可用引擎或聚合多个）
    if args.all:
        # 搜索所有可用引擎
        for engine in chain:
            if not engine.has_capability('search'):
                continue
            print(f"🔍 搜索中: {engine.get_name()}...", file=sys.stderr)
            try:
                results = engine.search(args.query, max_results=args.limit)
                if results:
                    all_results.extend(results)
                    used_engines.append(engine.get_name())
            except Exception as e:
                print(f"⚠️ {engine.get_name()} 搜索失败: {e}", file=sys.stderr)
    else:
        # 按降级链搜索，命中即停（或聚合前 N 个）
        for engine in chain:
            if not engine.has_capability('search'):
                continue
            print(f"🔍 搜索中: {engine.get_name()}...", file=sys.stderr)
            try:
                results = engine.search(args.query, max_results=args.limit)
                if results:
                    all_results.extend(results)
                    used_engines.append(engine.get_name())
                    if len(all_results) >= args.limit:
                        break
            except Exception as e:
                print(f"⚠️ {engine.get_name()} 搜索失败: {e}", file=sys.stderr)

    if not all_results:
        print("❌ 未找到结果", file=sys.stderr)
        if not used_engines:
            print("💡 可能原因：所有引擎都不可用，请运行 --mcp-check", file=sys.stderr)
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

    # 6. 交叉验证
    verifier = CrossVerifier()
    verification = verifier.verify(all_results, query=args.query)
    print(f"✓ 交叉验证: {len(verification.verified_claims)} 已验证, "
          f"{len(verification.single_source_claims)} 单源, "
          f"{len(verification.contradictions)} 矛盾",
          file=sys.stderr)

    # 7. 反思循环（如果 --reflect-rounds > 0）
    reflections = []
    if args.reflect_rounds > 0 and plan:
        from reflect import Reflector
        reflector = Reflector(max_rounds=args.reflect_rounds)
        for round_num in range(1, args.reflect_rounds + 1):
            reflection = reflector.reflect(plan, all_results, round_num, verification)
            reflections.append(reflection)
            print(f"🔄 反思轮 {round_num}: 覆盖率 {reflection.coverage_score:.0%}, "
                  f"{'需 Drill-down' if reflection.should_drill_down else '停止: ' + (reflection.stop_reason or '')}",
                  file=sys.stderr)
            if not reflection.should_drill_down:
                break

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

    # 10. 输出
    _output_results(output_data, args, plan, all_results, verification, reflections)


def _output_results(data, args, plan=None, results=None, verification=None, reflections=None):
    """输出结果"""
    format = args.format

    if format == 'json':
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return

    if format == 'csv':
        import csv
        writer = csv.writer(sys.stdout)
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
        return

    if format == 'markdown':
        if plan and results:
            from report import ReportGenerator
            reporter = ReportGenerator()
            md = reporter.generate(plan, results, verification, reflections, format='markdown')
            print(md)
        else:
            # 简单 markdown（无 plan 时）
            print(f"# {data['query']}\n")
            for r in data.get('results', []):
                print(f"## {r.get('title', '')}")
                print(f"URL: {r.get('url', '')}")
                print(f"来源: {r.get('source', '')}")
                craap = r.get('craap_score', {}) or {}
                if craap:
                    print(f"CRAAP: {craap.get('total', 0)}/100 ({craap.get('grade', '-')})")
                print(f"\n{r.get('content', '')}\n")
        return

    if format == 'html':
        if plan and results:
            # 完整 HTML 报告（含 Mermaid 图表、CRAAP 评分表）
            from report import ReportGenerator
            reporter = ReportGenerator()
            html = reporter.generate(plan, results, verification, reflections, format='html')
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
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


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
        f"Generated by Deep Research Ultra v4.0 — {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>",
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
    parser.add_argument('--llm-score', action='store_true',
                        help='启用 LLM 语义评分（更准确，消耗 token）')

    # 缓存
    parser.add_argument('--no-cache', action='store_true',
                        help='禁用缓存')

    # 工具命令
    parser.add_argument('--mcp-check', action='store_true',
                        help='MCP 健康检查')
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
    main()
