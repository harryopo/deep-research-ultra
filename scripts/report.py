#!/usr/bin/env python3
"""
Deep Research Ultra v4.0 — Phase 3: Synthesize（报告生成）

生成结构化调研报告，支持多种格式：
- HTML（默认，含 Mermaid 图表，可视化丰富）
- Markdown（轻量，适合文档系统）
- JSON（结构化，适合程序处理）
- CSV（来源列表，适合表格分析）

HTML 报告结构：
1. 执行摘要（Executive Summary）
2. MECE 问题树（Mermaid 图表）
3. 子问题分析（CER 结构：Claim-Evidence-Reasoning）
4. 矛盾点标注（Disagreements）
5. 时间线/趋势图（Mermaid timeline）
6. 引用列表（带 CRAAP 评分）
7. 可信度热图（来源 × 子问题）
8. 调研质量自评（覆盖率/验证率/矛盾处理率）

修复 v3.2.0 的问题：
- v3 只有 markdown/json/report/csv → v4 默认 HTML（含 Mermaid）
- v3 报告只是结果罗列 → v4 结构化（CER + 矛盾 + 时间线）
- v3 没有可视化 → v4 Mermaid 图表
- v3 没有质量自评 → v4 内置质量自评

使用方式：
    reporter = ReportGenerator()
    reporter.generate(
        plan=plan,
        results=results,
        verification=verification_result,
        reflections=reflection_history,
        format='html',
        output_path='report.html',
    )
"""

import csv
import html
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# v5.2 推荐度评分系统（可选导入，测试环境可能不存在）
try:
    from recommend import (
        GitHubRecommender,
        PaperRecommender,
        detect_intent,
        RecommendationScore,
    )
    _RECOMMEND_AVAILABLE = True
except ImportError:
    _RECOMMEND_AVAILABLE = False
    GitHubRecommender = None
    PaperRecommender = None
    detect_intent = None
    RecommendationScore = None


def as_reflection_history(reflections: Any) -> Optional[Any]:
    """把 List[Reflection] 归一为 ReflectionHistory（幂等）。

    research.py 的反思循环累积的是 list，而本模块按 ReflectionHistory 读取
    .final_coverage / .total_rounds / .to_dict()；这个边界从未被定义，
    于是 --format html 在 --reflect-rounds ≥ 1 时必然 AttributeError 崩溃。
    """
    if reflections is None:
        return None
    from reflect import ReflectionHistory
    if isinstance(reflections, ReflectionHistory):
        return reflections
    hist = ReflectionHistory()
    for r in reflections:
        hist.add(r)
    return hist


# ============================================================
# Mermaid 图表生成
# ============================================================

class MermaidGenerator:
    """Mermaid 图表生成器"""

    @staticmethod
    def issue_tree(plan: Any) -> str:
        """生成 MECE 问题树 Mermaid 图"""
        lines = ["graph TD"]
        issue_tree = getattr(plan, 'issue_tree', []) if plan else []

        def _add_node(q):
            # 节点文本（截断）
            text = q.question[:30].replace('"', "'")
            # 根据状态选择样式
            status = getattr(q, 'status', 'pending')
            if status == 'completed':
                lines.append(f'    {q.id}["✅ {text}"]:::completed')
            elif status == 'searching':
                lines.append(f'    {q.id}["🔍 {text}"]:::searching')
            else:
                lines.append(f'    {q.id}["{text}"]')
            for child in getattr(q, 'children', []):
                _add_node(child)
                lines.append(f'    {q.id} --> {child.id}')

        for root in issue_tree:
            _add_node(root)

        # 样式定义
        lines.append("")
        lines.append("    classDef completed fill:#d4edda,stroke:#28a745,stroke-width:2px")
        lines.append("    classDef searching fill:#fff3cd,stroke:#ffc107,stroke-width:2px")
        return '\n'.join(lines)

    @staticmethod
    def timeline(events: List[Dict[str, str]]) -> str:
        """
        生成时间线 Mermaid 图

        Args:
            events: [{"date": "2025-01", "event": "...", "source": "..."}]
        """
        if not events:
            return ""

        lines = ["timeline"]
        lines.append("    title 调研主题时间线")
        # 按日期排序
        sorted_events = sorted(events, key=lambda x: x.get('date', ''))
        # 按年分组
        current_year = ""
        for event in sorted_events:
            date = event.get('date', '')
            event_text = event.get('event', '')[:40]
            if date:
                year = date[:4] if len(date) >= 4 else ""
                if year != current_year:
                    current_year = year
                    lines.append(f"    section {year}")
                lines.append(f"    {date} : {event_text}")
        return '\n'.join(lines)

    @staticmethod
    def credibility_heatmap(sources: List[str], questions: List[str],
                            scores: Dict[str, Dict[str, float]]) -> str:
        """
        生成可信度热图（来源 × 子问题）

        使用 Mermaid quadrantChart
        """
        if not sources or not questions:
            return ""

        lines = ["quadrantChart"]
        lines.append("    title 来源可信度分布")
        lines.append("    x-axis 低权威性 --> 高权威性")
        lines.append("    y-axis 低相关性 --> 高相关性")
        lines.append("    quadrant-1 推荐")
        lines.append("    quadrant-2 谨慎使用")
        lines.append("    quadrant-3 补充参考")
        lines.append("    quadrant-4 高质量但偏离主题")

        for source in sources[:15]:  # 最多 15 个
            for question in questions[:5]:  # 最多 5 个问题
                score = scores.get(source, {}).get(question, {})
                authority = score.get('authority', 50) / 100
                relevance = score.get('relevance', 50) / 100
                label = f"{source}-{question[:10]}"
                lines.append(f'    "{label}": [{authority:.2f}, {relevance:.2f}]')

        return '\n'.join(lines)

    @staticmethod
    def source_distribution(results: List[Any]) -> str:
        """生成数据源分布饼图"""
        from collections import Counter
        sources = []
        for r in results:
            source = r.source if hasattr(r, 'source') else r.get('source', '')
            if source:
                sources.append(source)

        if not sources:
            return ""

        counter = Counter(sources)
        lines = ["pie title 数据源分布"]
        for source, count in counter.most_common():
            lines.append(f'    "{source}" : {count}')
        return '\n'.join(lines)


# ============================================================
# SVG 雷达图生成器（v5.2 新增）
# ============================================================

class RadarChartGenerator:
    """
    SVG 雷达图生成器 — 多维度推荐度可视化

    用于在报告中展示 GitHub 项目/论文的多维度评分对比。
    纯 SVG 生成，不依赖外部库，支持暗色模式。
    """

    # 配色方案（每组一个颜色，最多 8 个项目对比）
    COLORS = [
        '#3b82f6',  # blue
        '#10b981',  # emerald
        '#f59e0b',  # amber
        '#ef4444',  # red
        '#8b5cf6',  # violet
        '#ec4899',  # pink
        '#06b6d4',  # cyan
        '#84cc16',  # lime
    ]

    @staticmethod
    def generate(
        items: List[Dict[str, Any]],
        dimensions: List[str],
        dimension_labels: Optional[Dict[str, str]] = None,
        max_items: int = 5,
        size: int = 400,
    ) -> str:
        """
        生成雷达图 SVG

        Args:
            items: [{"label": "项目A", "scores": {"popularity": 80, "activity": 70, ...}}, ...]
            dimensions: ["popularity", "activity", "maintenance", ...]
            dimension_labels: {"popularity": "人气", "activity": "活跃度", ...}
            max_items: 最多对比项目数
            size: SVG 尺寸（正方形）

        Returns:
            SVG 字符串
        """
        if not items or not dimensions:
            return '<p style="color:var(--muted);">无推荐度数据，无法生成雷达图。</p>'

        items = items[:max_items]
        n_dims = len(dimensions)
        if n_dims < 3:
            return '<p style="color:var(--muted);">维度不足 3 个，无法生成雷达图。</p>'

        labels = dimension_labels or {}
        center = size / 2
        radius = size * 0.35
        angle_step = 2 * math.pi / n_dims

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}" style="max-width:100%;height:auto;">',
        ]

        # 1. 背景网格（5 层同心多边形）
        for level in range(1, 6):
            r = radius * level / 5
            points = []
            for i in range(n_dims):
                angle = -math.pi / 2 + i * angle_step
                x = center + r * math.cos(angle)
                y = center + r * math.sin(angle)
                points.append(f'{x:.1f},{y:.1f}')
            opacity = 0.15 + level * 0.05
            svg_parts.append(
                f'<polygon points="{" ".join(points)}" '
                f'fill="none" stroke="var(--border)" stroke-width="1" opacity="{opacity:.2f}"/>'
            )

        # 2. 轴线 + 维度标签
        for i, dim in enumerate(dimensions):
            angle = -math.pi / 2 + i * angle_step
            x_end = center + radius * math.cos(angle)
            y_end = center + radius * math.sin(angle)
            svg_parts.append(
                f'<line x1="{center}" y1="{center}" x2="{x_end:.1f}" y2="{y_end:.1f}" '
                f'stroke="var(--border)" stroke-width="1"/>'
            )
            # 标签
            label_x = center + (radius + 20) * math.cos(angle)
            label_y = center + (radius + 20) * math.sin(angle)
            label_text = labels.get(dim, dim)
            svg_parts.append(
                f'<text x="{label_x:.1f}" y="{label_y:.1f}" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'fill="var(--muted)" font-size="11">{html.escape(label_text)}</text>'
            )

        # 3. 每个项目的数据多边形
        for idx, item in enumerate(items):
            color = RadarChartGenerator.COLORS[idx % len(RadarChartGenerator.COLORS)]
            scores = item.get('scores', {})
            points = []
            for i, dim in enumerate(dimensions):
                value = scores.get(dim, 0)
                # 归一化到 0-1
                normalized = max(0, min(100, value)) / 100
                r = radius * normalized
                angle = -math.pi / 2 + i * angle_step
                x = center + r * math.cos(angle)
                y = center + r * math.sin(angle)
                points.append(f'{x:.1f},{y:.1f}')

            svg_parts.append(
                f'<polygon points="{" ".join(points)}" '
                f'fill="{color}" fill-opacity="0.12" '
                f'stroke="{color}" stroke-width="2"/>'
            )
            # 数据点
            for pt in points:
                px, py = pt.split(',')
                svg_parts.append(
                    f'<circle cx="{px}" cy="{py}" r="3" fill="{color}"/>'
                )

        # 4. 图例
        legend_y = size - 10
        legend_x = 10
        for idx, item in enumerate(items):
            color = RadarChartGenerator.COLORS[idx % len(RadarChartGenerator.COLORS)]
            label = item.get('label', f'项目{idx+1}')[:20]
            svg_parts.append(
                f'<rect x="{legend_x}" y="{legend_y - idx * 18}" width="12" height="12" '
                f'fill="{color}" fill-opacity="0.3" stroke="{color}" stroke-width="1.5"/>'
            )
            svg_parts.append(
                f'<text x="{legend_x + 16}" y="{legend_y - idx * 18 + 10}" '
                f'fill="var(--fg)" font-size="11">{html.escape(label)}</text>'
            )

        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)


# ============================================================
# HTML 报告模板
# ============================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — 深度调研报告</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        :root {{
            --bg: #ffffff;
            --fg: #1a1a1a;
            --muted: #6b7280;
            --border: #e5e7eb;
            --accent: #3b82f6;
            --accent-light: #eff6ff;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --code-bg: #f9fafb;
            --card-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg: #1a1a1a;
                --fg: #e5e7eb;
                --muted: #9ca3af;
                --border: #374151;
                --accent: #60a5fa;
                --accent-light: #1e3a5f;
                --code-bg: #2d2d2d;
            }}
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: var(--fg);
            background: var(--bg);
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }}
        h1, h2, h3, h4 {{ margin-top: 2rem; margin-bottom: 1rem; font-weight: 600; }}
        h1 {{ font-size: 2rem; border-bottom: 2px solid var(--accent); padding-bottom: 0.5rem; }}
        h2 {{ font-size: 1.5rem; color: var(--accent); }}
        h3 {{ font-size: 1.25rem; }}
        p {{ margin-bottom: 1rem; }}
        a {{ color: var(--accent); text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        blockquote {{
            border-left: 4px solid var(--accent);
            padding: 0.5rem 1rem;
            margin: 1rem 0;
            background: var(--accent-light);
            border-radius: 0 4px 4px 0;
        }}
        code {{
            background: var(--code-bg);
            padding: 0.2rem 0.4rem;
            border-radius: 3px;
            font-family: "SFMono-Regular", Consolas, monospace;
            font-size: 0.9em;
        }}
        pre {{
            background: var(--code-bg);
            padding: 1rem;
            border-radius: 6px;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
            box-shadow: var(--card-shadow);
        }}
        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{ background: var(--accent-light); font-weight: 600; }}
        tr:hover {{ background: var(--accent-light); }}
        .card {{
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.5rem;
            margin: 1rem 0;
            box-shadow: var(--card-shadow);
        }}
        .grade-high {{ color: var(--success); font-weight: 600; }}
        .grade-medium {{ color: var(--warning); font-weight: 600; }}
        .grade-low {{ color: var(--danger); font-weight: 600; }}
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: 500;
        }}
        .badge-high {{ background: #d1fae5; color: #065f46; }}
        .badge-medium {{ background: #fef3c7; color: #92400e; }}
        .badge-low {{ background: #fee2e2; color: #991b1b; }}
        .toc {{
            background: var(--code-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.5rem;
            margin: 2rem 0;
        }}
        .toc ul {{ list-style: none; }}
        .toc li {{ padding: 0.25rem 0; }}
        .toc a {{ color: var(--fg); }}
        .metadata {{
            color: var(--muted);
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }}
        .mermaid {{
            text-align: center;
            margin: 2rem 0;
            background: var(--code-bg);
            padding: 1rem;
            border-radius: 8px;
        }}
        .contradiction {{
            border-left: 4px solid var(--danger);
            background: #fef2f2;
            padding: 1rem;
            margin: 1rem 0;
            border-radius: 0 4px 4px 0;
        }}
        .verified {{
            border-left: 4px solid var(--success);
            background: #f0fdf4;
            padding: 1rem;
            margin: 1rem 0;
            border-radius: 0 4px 4px 0;
        }}
        .single-source {{
            border-left: 4px solid var(--warning);
            background: #fffbeb;
            padding: 1rem;
            margin: 1rem 0;
            border-radius: 0 4px 4px 0;
        }}
        .footer {{
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid var(--border);
            color: var(--muted);
            font-size: 0.85rem;
            text-align: center;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin: 1rem 0;
        }}
        .stat-card {{
            background: var(--accent-light);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            text-align: center;
        }}
        .stat-value {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent);
        }}
        .stat-label {{
            font-size: 0.85rem;
            color: var(--muted);
            margin-top: 0.25rem;
        }}
        /* v5.2 推荐度评分样式 */
        .recommendation-section {{
            margin: 2rem 0;
        }}
        .group-header {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin: 1.5rem 0 0.75rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid var(--border);
        }}
        .group-header h3 {{
            margin: 0;
            font-size: 1.1rem;
        }}
        .group-badge {{
            display: inline-block;
            padding: 0.15rem 0.6rem;
            border-radius: 10px;
            font-size: 0.8rem;
            font-weight: 600;
        }}
        .group-flagship {{ background: #dbeafe; color: #1e40af; }}
        .group-mainstream {{ background: #d1fae5; color: #065f46; }}
        .group-niche {{ background: #fef3c7; color: #92400e; }}
        .group-paper {{ background: #ede9fe; color: #5b21b6; }}
        .grade-badge {{
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            color: #fff;
        }}
        .grade-Adopt {{ background: #059669; }}
        .grade-Trial {{ background: #2563eb; }}
        .grade-Assess {{ background: #d97706; }}
        .grade-Hold {{ background: #6b7280; }}
        .grade-MustRead {{ background: #dc2626; }}
        .grade-Recommended {{ background: #059669; }}
        .grade-Optional {{ background: #d97706; }}
        .grade-Skip {{ background: #6b7280; }}
        .recommendation-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 0.5rem 0 1rem;
            font-size: 0.9rem;
        }}
        .recommendation-table th {{
            background: var(--accent-light);
            padding: 0.6rem;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid var(--accent);
            white-space: nowrap;
        }}
        .recommendation-table td {{
            padding: 0.6rem;
            border-bottom: 1px solid var(--border);
            vertical-align: top;
        }}
        .recommendation-table tr:hover {{
            background: var(--accent-light);
        }}
        .score-bar {{
            display: inline-block;
            width: 60px;
            height: 8px;
            background: var(--border);
            border-radius: 4px;
            overflow: hidden;
            vertical-align: middle;
            margin-right: 0.3rem;
        }}
        .score-bar-fill {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s;
        }}
        .radar-container {{
            display: flex;
            justify-content: center;
            margin: 1.5rem 0;
            background: var(--code-bg);
            padding: 1rem;
            border-radius: 8px;
        }}
        .recommendation-reason {{
            color: var(--muted);
            font-size: 0.85rem;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <h1>📊 {title}</h1>
    <div class="metadata">
        <p>📅 生成时间：{generated_at}</p>
        <p>🎯 调研目标：{goal}</p>
        <p>🔍 调研深度：{depth}</p>
        <p>⏱️ 预估时长：{duration}</p>
        <p>📚 数据源数：{source_count}</p>
    </div>

    {toc}

    {content}

    <div class="footer">
        <p>由 Deep Research Ultra v4.0 生成 | {generated_at}</p>
    </div>

    <script>
        mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
    </script>
</body>
</html>"""


# ============================================================
# 报告生成器
# ============================================================

class ReportGenerator:
    """
    调研报告生成器

    支持格式：
    - html: HTML 报告（默认，含 Mermaid 图表）
    - markdown: Markdown 报告
    - json: JSON 结构化数据
    - csv: CSV 来源列表
    """

    def generate(
        self,
        plan: Any,
        results: List[Any],
        verification: Optional[Any] = None,
        reflections: Optional[Any] = None,
        format: str = 'html',
        output_path: Optional[str] = None,
        ledger: Optional[Any] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        生成报告

        Args:
            plan: ResearchPlan 对象
            results: 搜索结果列表（已评分）
            verification: VerificationResult 对象
            reflections: ReflectionHistory 对象
            format: 输出格式（html/markdown/json/csv）
            output_path: 输出文件路径（如不提供则返回字符串）
            ledger: v6.0 证据账本（ResearchLedger），追加账本摘要/来源 Tier 分布
            options: v6.0 调研元信息 {'depth','breadth','perspectives','effort','validation'}

        Returns:
            报告内容字符串
        """
        if format == 'html':
            content = self._generate_html(plan, results, verification, reflections,
                                          ledger=ledger, options=options)
        elif format == 'markdown':
            content = self._generate_markdown(plan, results, verification, reflections,
                                              ledger=ledger, options=options)
        elif format == 'json':
            content = self._generate_json(plan, results, verification, reflections,
                                          ledger=ledger, options=options)
        elif format == 'csv':
            content = self._generate_csv(results)
        else:
            raise ValueError(f"不支持的格式: {format}")

        if output_path:
            Path(output_path).write_text(content, encoding='utf-8')

        return content

    # ------------------------------------------------------------
    # HTML 报告
    # ------------------------------------------------------------

    def _generate_html(
        self,
        plan: Any,
        results: List[Any],
        verification: Optional[Any],
        reflections: Optional[Any],
        ledger: Optional[Any] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成 HTML 报告"""
        topic = getattr(plan, 'topic', '调研报告') if plan else '调研报告'
        goal = getattr(plan, 'goal', '') if plan else ''
        depth = getattr(plan, 'depth', 'standard') if plan else 'standard'
        duration = getattr(plan, 'estimated_duration', '') if plan else ''
        source_count = len(set(
            r.source if hasattr(r, 'source') else r.get('source', '')
            for r in results
        ))

        # 生成各部分内容
        toc = self._html_toc()
        executive_summary = self._html_executive_summary(plan, results, verification)
        v6_meta = self._html_v6_meta(options, ledger)           # v6.0
        issue_tree_section = self._html_issue_tree(plan)
        analysis_section = self._html_analysis(results, verification)
        contradictions_section = self._html_contradictions(verification)
        timeline_section = self._html_timeline(results)
        sources_section = self._html_sources(results)
        recommendations_section = self._html_recommendations(results, plan)
        quality_section = self._html_quality(plan, results, verification, reflections)
        v6_appendix = self._html_v6_appendix(ledger)            # v6.0

        content = '\n'.join([
            executive_summary,
            v6_meta,
            issue_tree_section,
            analysis_section,
            contradictions_section,
            timeline_section,
            sources_section,
            recommendations_section,
            quality_section,
            v6_appendix,
        ])

        return HTML_TEMPLATE.format(
            title=html.escape(topic),
            generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            goal=html.escape(goal) or '未指定',
            depth=depth,
            duration=duration or '未指定',
            source_count=source_count,
            toc=toc,
            content=content,
        )

    def _html_toc(self) -> str:
        """生成目录"""
        return """<div class="toc">
        <h3>📑 目录</h3>
        <ul>
            <li><a href="#summary">1. 执行摘要</a></li>
            <li><a href="#issue-tree">2. MECE 问题树</a></li>
            <li><a href="#analysis">3. 子问题分析（CER）</a></li>
            <li><a href="#contradictions">4. 矛盾点标注</a></li>
            <li><a href="#timeline">5. 时间线</a></li>
            <li><a href="#sources">6. 引用列表（CRAAP 评分）</a></li>
            <li><a href="#recommendations">7. 推荐度评分与排序（v5.2）</a></li>
            <li><a href="#quality">8. 调研质量自评</a></li>
            <li><a href="#v6-ledger">9. 证据账本与来源分级（v6.0）</a></li>
        </ul>
    </div>"""

    # ------------------------------------------------------------
    # v6.0：调研元信息 + 证据账本摘要 + 来源 Tier 分布
    # ------------------------------------------------------------
    def _html_v6_meta(self, options: Optional[Dict[str, Any]],
                      ledger: Optional[Any]) -> str:
        """调研元信息卡（effort/breadth/专家团/校验）+ 账本概览。无输入时返回空。"""
        if not options and ledger is None:
            return ''
        parts = [f'<div class="card" id="v6-ledger"><h4>⚙️ 调研配置（v6.0）</h4><table>']
        if options:
            fields = [
                ('effort', '努力程度'), ('breadth', '并行子主题数'),
                ('depth', '深度'), ('perspectives', '专家团视角'),
                ('validation', '发布校验'),
            ]
            for key, label in fields:
                if options.get(key) is not None:
                    parts.append(f'<tr><th>{label}</th><td>{html.escape(str(options[key]))}</td></tr>')
        if ledger is not None:
            stats = self._ledger_stats(ledger)
            if stats:
                parts.append(f'<tr><th>账本 claims</th><td>{stats["claims"]}</td></tr>')
                parts.append(f'<tr><th>账本 sources</th><td>{stats["sources"]}</td></tr>')
                parts.append(
                    f'<tr><th>证据充分子主题</th><td>{stats["sufficient_topics"]}/{stats["topic_count"]}</td></tr>')
        parts.append('</table></div>')
        return '\n'.join(parts) if len(parts) > 1 else ''

    def _html_v6_appendix(self, ledger: Optional[Any]) -> str:
        """证据账本摘要（按子主题）+ 来源 Tier 分布附录。"""
        if ledger is None:
            return ''
        stats = self._ledger_stats(ledger)
        if not stats or not stats['topic_stats']:
            return ''
        out = ['<div class="card" id="v6-ledger-detail"><h4>📒 证据账本摘要</h4>',
               '<table><tr><th>子主题</th><th>claims</th><th>verified</th>'
               '<th>conflict</th><th>独立来源</th><th>覆盖</th><th>充分</th></tr>']
        for t, s in sorted(stats['topic_stats'].items()):
            mark = '✅' if s.get('sufficient') else '⚠️'
            out.append(f'<tr><td>{html.escape(t)}</td><td>{s["claims"]}</td>'
                       f'<td>{s["verified"]}</td><td>{s["conflict"]}</td>'
                       f'<td>{s["independent_sources"]}</td><td>{s["coverage"]:.0%}</td>'
                       f'<td>{mark}</td></tr>')
        out.append('</table>')
        if stats['tier_dist']:
            out += ['<h4>📍 来源 Tier 分布（附录 D）</h4>',
                    '<table><tr><th>Tier</th><th>含义</th><th>数量</th></tr>']
            for tier in sorted(stats['tier_dist']):
                label = {1: '官方/学术', 2: '权威/官方文档', 3: '一般', 4: '社区/低质'}.get(tier, str(tier))
                out.append(f'<tr><td>{tier}</td><td>{label}</td><td>{stats["tier_dist"][tier]}</td></tr>')
            out.append('</table>')
        out.append('</div>')
        return '\n'.join(out)

    @staticmethod
    def _ledger_stats(ledger: Optional[Any]) -> Optional[Dict[str, Any]]:
        """从账本提取统计（任一步出错返回 None，绝不中断报告生成）。"""
        if ledger is None:
            return None
        try:
            stats = ledger.status()
            sources = ledger.export_json().get('sources', [])
            tier_dist: Dict[int, int] = {}
            for s in sources:
                t = s.get('tier')
                if t is not None:
                    tier_dist[t] = tier_dist.get(t, 0) + 1
            return {
                'topic_stats': stats,
                'tier_dist': tier_dist,
                'claims': len(ledger.claims()),
                'sources': len(sources),
                'sufficient_topics': sum(1 for s in stats.values() if s.get('sufficient')),
                'topic_count': len(stats),
            }
        except Exception:
            return None

    def _html_executive_summary(
        self, plan: Any, results: List[Any], verification: Optional[Any]
    ) -> str:
        """执行摘要"""
        verified_count = len(verification.verified_claims) if verification else 0
        single_count = len(verification.single_source_claims) if verification else 0
        contradiction_count = len(verification.contradictions) if verification else 0
        verification_rate = verification.verification_rate if verification else 0

        # 计算 CRAAP 平均分
        total_scores = []
        for r in results:
            craap = r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {})
            if craap:
                total_scores.append(craap.get('total', 0))
        avg_score = sum(total_scores) / len(total_scores) if total_scores else 0

        return f"""<h2 id="summary">1. 执行摘要</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{len(results)}</div>
                <div class="stat-label">总结果数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{verified_count}</div>
                <div class="stat-label">已验证结论</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{verification_rate:.0%}</div>
                <div class="stat-label">验证率</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{avg_score:.1f}</div>
                <div class="stat-label">平均 CRAAP 分</div>
            </div>
        </div>
        <p>本次调研共收集 <strong>{len(results)}</strong> 条结果，
        其中 <strong>{verified_count}</strong> 条结论经过交叉验证（≥2 独立来源），
        验证率 <strong>{verification_rate:.0%}</strong>。
        发现 <strong>{contradiction_count}</strong> 个矛盾点，
        <strong>{single_count}</strong> 条单源结论待进一步验证。</p>"""

    def _html_issue_tree(self, plan: Any) -> str:
        """MECE 问题树"""
        if not plan or not getattr(plan, 'issue_tree', []):
            return '<h2 id="issue-tree">2. MECE 问题树</h2><p>未生成问题树。</p>'

        mermaid_code = MermaidGenerator.issue_tree(plan)
        return f"""<h2 id="issue-tree">2. MECE 问题树</h2>
        <div class="mermaid">
{mermaid_code}
        </div>"""

    def _html_analysis(self, results: List[Any], verification: Optional[Any]) -> str:
        """CER 结构分析"""
        if not verification:
            return '<h2 id="analysis">3. 子问题分析（CER）</h2><p>未进行交叉验证。</p>'

        sections = ['<h2 id="analysis">3. 子问题分析（CER）</h2>']

        # 已验证结论
        if verification.verified_claims:
            sections.append('<h3>✅ 已验证结论</h3>')
            for claim in verification.verified_claims[:10]:
                sources_html = ', '.join(
                    f'<a href="{ev.source_url}" target="_blank">{ev.source_domain}</a>'
                    for ev in claim.evidence[:3]
                )
                confidence_class = 'grade-high' if claim.confidence > 0.7 else 'grade-medium'
                sections.append(f"""<div class="verified">
                    <p><strong>结论：</strong>{html.escape(claim.statement)}</p>
                    <p><strong>置信度：</strong><span class="{confidence_class}">{claim.confidence:.0%}</span>
                    | <strong>独立来源：</strong>{claim.get_independent_source_count()} 个</p>
                    <p><strong>来源：</strong>{sources_html}</p>
                </div>""")

        # 单源结论
        if verification.single_source_claims:
            sections.append('<h3>⚠️ 单源结论（待确认）</h3>')
            for claim in verification.single_source_claims[:5]:
                sources_html = ', '.join(
                    f'<a href="{ev.source_url}" target="_blank">{ev.source_domain}</a>'
                    for ev in claim.evidence[:2]
                )
                sections.append(f"""<div class="single-source">
                    <p><strong>结论：</strong>{html.escape(claim.statement)}</p>
                    <p><strong>来源：</strong>{sources_html}（仅 1 个来源）</p>
                </div>""")

        return '\n'.join(sections)

    def _html_contradictions(self, verification: Optional[Any]) -> str:
        """矛盾点标注"""
        if not verification or not verification.contradictions:
            return '<h2 id="contradictions">4. 矛盾点标注</h2><p>✅ 未发现明显矛盾。</p>'

        sections = ['<h2 id="contradictions">4. 矛盾点标注</h2>']
        for con in verification.contradictions:
            sections.append(f"""<div class="contradiction">
                <p><strong>矛盾 A：</strong>{html.escape(con.claim_a)}</p>
                <p><strong>矛盾 B：</strong>{html.escape(con.claim_b)}</p>
                <p><strong>可能原因：</strong>{html.escape(con.possible_reason)}</p>
            </div>""")
        return '\n'.join(sections)

    def _html_timeline(self, results: List[Any]) -> str:
        """时间线"""
        events = []
        for r in results:
            title = r.title if hasattr(r, 'title') else r.get('title', '')
            date = r.published_date if hasattr(r, 'published_date') else r.get('published_date', '')
            if date:
                events.append({'date': date, 'event': title, 'source': ''})

        if not events:
            return '<h2 id="timeline">5. 时间线</h2><p>无时间线数据。</p>'

        mermaid_code = MermaidGenerator.timeline(events)
        return f"""<h2 id="timeline">5. 时间线</h2>
        <div class="mermaid">
{mermaid_code}
        </div>"""

    def _html_sources(self, results: List[Any]) -> str:
        """引用列表"""
        if not results:
            return '<h2 id="sources">6. 引用列表</h2><p>无引用。</p>'

        rows = []
        for i, r in enumerate(results, 1):
            title = r.title if hasattr(r, 'title') else r.get('title', '')
            url = r.url if hasattr(r, 'url') else r.get('url', '')
            source = r.source if hasattr(r, 'source') else r.get('source', '')
            craap = r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {})
            total = craap.get('total', 0) if craap else 0
            grade = craap.get('grade', '') if craap else ''
            grade_class = f'grade-{grade}' if grade else ''
            badge_class = f'badge-{grade}' if grade else ''
            rows.append(f"""<tr>
                <td>{i}</td>
                <td><a href="{html.escape(url)}" target="_blank">{html.escape(title[:60])}</a></td>
                <td>{html.escape(source)}</td>
                <td class="{grade_class}">{total:.1f}</td>
                <td><span class="badge {badge_class}">{grade}</span></td>
            </tr>""")

        # 数据源分布图
        mermaid_pie = MermaidGenerator.source_distribution(results)

        return f"""<h2 id="sources">6. 引用列表（CRAAP 评分）</h2>
        <div class="mermaid">
{mermaid_pie}
        </div>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>标题</th>
                    <th>来源</th>
                    <th>CRAAP 分</th>
                    <th>等级</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>"""

    def _html_recommendations(self, results: List[Any], plan: Any) -> str:
        """
        v5.2 推荐度评分与排序章节

        包含：
        1. GitHub 项目推荐度（分组：旗舰/主流/小众，组内按推荐度排序）
        2. 推荐度对比表（含 8 维评分 + 推荐等级 + 推荐理由）
        3. 雷达图（前 5 个项目多维度对比，SVG）
        4. 学术论文推荐度（如有论文结果）
        """
        if not _RECOMMEND_AVAILABLE:
            return (
                '<h2 id="recommendations">7. 推荐度评分与排序</h2>'
                '<p style="color:var(--muted);">推荐度评分模块未加载（recommend.py 不可用）。</p>'
            )

        if not results:
            return (
                '<h2 id="recommendations">7. 推荐度评分与排序</h2>'
                '<p style="color:var(--muted);">无搜索结果，无法生成推荐度评分。</p>'
            )

        # 获取查询关键词（用于意图识别和相关性评分）
        query = getattr(plan, 'topic', '') if plan else ''
        intent = detect_intent(query) if detect_intent else 'default'

        sections = [
            '<h2 id="recommendations">7. 推荐度评分与排序（v5.2）</h2>',
            f'<blockquote><p>🎯 查询意图：<strong>{html.escape(intent)}</strong>'
            f' | 推荐度评分基于多维度加权（人气/活跃/维护/社区/文档/依赖/相关/生态）</p></blockquote>',
        ]

        # ---- GitHub 项目推荐度 ----
        github_recommender = GitHubRecommender()
        ranked_github = github_recommender.rank_results(results, query, intent)

        if ranked_github:
            sections.append(self._render_github_recommendations(ranked_github, intent))
        else:
            sections.append(
                '<p style="color:var(--muted);">本次调研未包含 GitHub 项目结果。</p>'
            )

        # ---- 学术论文推荐度 ----
        paper_recommender = PaperRecommender()
        ranked_papers = paper_recommender.rank_results(results, query)

        if ranked_papers:
            sections.append(self._render_paper_recommendations(ranked_papers))

        return '\n'.join(sections)

    def _render_github_recommendations(
        self, ranked: List[Dict[str, Any]], intent: str
    ) -> str:
        """渲染 GitHub 项目推荐度（分组 + 对比表 + 雷达图）"""
        # 统计各组数量
        group_counts = {'flagship': 0, 'mainstream': 0, 'niche': 0}
        for item in ranked:
            group = item['recommendation'].group
            if group in group_counts:
                group_counts[group] += 1

        group_labels = {
            'flagship': ('旗舰项目', '⭐ ≥ 1000', 'group-flagship'),
            'mainstream': ('主流项目', '⭐ 100-1000', 'group-mainstream'),
            'niche': ('小众项目', '⭐ < 100（可借鉴）', 'group-niche'),
        }

        parts = [
            '<h3>📦 GitHub 项目推荐度</h3>',
            f'<div class="stats-grid">',
            f'<div class="stat-card"><div class="stat-value">{group_counts["flagship"]}</div>'
            f'<div class="stat-label">旗舰项目</div></div>',
            f'<div class="stat-card"><div class="stat-value">{group_counts["mainstream"]}</div>'
            f'<div class="stat-label">主流项目</div></div>',
            f'<div class="stat-card"><div class="stat-value">{group_counts["niche"]}</div>'
            f'<div class="stat-label">小众项目</div></div>',
            f'<div class="stat-card"><div class="stat-value">{len(ranked)}</div>'
            f'<div class="stat-label">总计</div></div>',
            f'</div>',
        ]

        # 按组渲染对比表
        current_group = ''
        for item in ranked:
            rec = item['recommendation']
            result = item['result']

            # 组分隔符
            if rec.group != current_group:
                current_group = rec.group
                label, desc, css_class = group_labels.get(
                    rec.group, (rec.group, '', 'group-mainstream')
                )
                parts.append(
                    f'<div class="group-header">'
                    f'<span class="group-badge {css_class}">{html.escape(label)}</span>'
                    f'<h3>{html.escape(label)}</h3>'
                    f'<span style="color:var(--muted);font-size:0.85rem;">{html.escape(desc)}</span>'
                    f'</div>'
                )
                # 表头
                parts.append(
                    '<table class="recommendation-table">'
                    '<thead><tr>'
                    '<th>#</th><th>项目</th><th>⭐ Stars</th>'
                    '<th>推荐度</th><th>等级</th>'
                    '<th>人气</th><th>活跃</th><th>维护</th><th>社区</th>'
                    '<th>文档</th><th>依赖</th><th>相关</th><th>生态</th>'
                    '<th>推荐理由</th>'
                    '</tr></thead><tbody>'
                )

            # 表行
            repo_data = result.raw if hasattr(result, 'raw') else result.get('raw', {})
            stars = repo_data.get('stars', 0)
            name = repo_data.get('full_name', repo_data.get('name', result.title if hasattr(result, 'title') else ''))
            url = result.url if hasattr(result, 'url') else result.get('url', '')

            dims = rec.dimensions
            # 评分条颜色（根据分数）
            def _score_bar(score: float) -> str:
                if score >= 70:
                    color = '#10b981'
                elif score >= 40:
                    color = '#f59e0b'
                else:
                    color = '#ef4444'
                return (
                    f'<span class="score-bar">'
                    f'<span class="score-bar-fill" style="width:{score:.0f}%;background:{color};"></span>'
                    f'</span>{score:.0f}'
                )

            parts.append(
                f'<tr>'
                f'<td>{rec.rank_in_group}</td>'
                f'<td><a href="{html.escape(url)}" target="_blank">{html.escape(str(name)[:40])}</a></td>'
                f'<td>{"⭐" if stars >= 1000 else ""}{stars}</td>'
                f'<td><strong>{rec.total_score:.1f}</strong></td>'
                f'<td><span class="grade-badge grade-{rec.grade}">{rec.grade}</span></td>'
                f'<td>{_score_bar(dims.get("popularity", 0))}</td>'
                f'<td>{_score_bar(dims.get("activity", 0))}</td>'
                f'<td>{_score_bar(dims.get("maintenance", 0))}</td>'
                f'<td>{_score_bar(dims.get("community", 0))}</td>'
                f'<td>{_score_bar(dims.get("docs", 0))}</td>'
                f'<td>{_score_bar(dims.get("dependency", 0))}</td>'
                f'<td>{_score_bar(dims.get("relevance", 0))}</td>'
                f'<td>{_score_bar(dims.get("ecosystem", 0))}</td>'
                f'<td class="recommendation-reason">{html.escape(rec.recommendation_reason[:80])}</td>'
                f'</tr>'
            )

        # 关闭最后一个表格
        if current_group:
            parts.append('</tbody></table>')

        # 雷达图（前 5 个项目）
        if len(ranked) >= 1:
            radar_items = []
            for item in ranked[:5]:
                rec = item['recommendation']
                result = item['result']
                repo_data = result.raw if hasattr(result, 'raw') else result.get('raw', {})
                name = repo_data.get('name', '项目')
                radar_items.append({
                    'label': name,
                    'scores': rec.dimensions,
                })

            dim_labels = {
                'popularity': '人气', 'activity': '活跃', 'maintenance': '维护',
                'community': '社区', 'docs': '文档', 'dependency': '依赖',
                'relevance': '相关', 'ecosystem': '生态',
            }
            radar_svg = RadarChartGenerator.generate(
                items=radar_items,
                dimensions=['popularity', 'activity', 'maintenance', 'community',
                           'docs', 'dependency', 'relevance', 'ecosystem'],
                dimension_labels=dim_labels,
                max_items=5,
                size=450,
            )
            parts.append('<h4>📊 推荐度雷达图（前 5 项目对比）</h4>')
            parts.append(f'<div class="radar-container">{radar_svg}</div>')

        return '\n'.join(parts)

    def _render_paper_recommendations(self, ranked: List[Dict[str, Any]]) -> str:
        """渲染学术论文推荐度"""
        parts = [
            '<div class="group-header">'
            '<span class="group-badge group-paper">学术论文</span>'
            '<h3>学术论文推荐度</h3>'
            '</div>',
            '<table class="recommendation-table">'
            '<thead><tr>'
            '<th>#</th><th>标题</th><th>引用</th>'
            '<th>推荐度</th><th>等级</th>'
            '<th>引用影响</th><th>时效</th><th>权威</th><th>h-index</th><th>相关</th>'
            '<th>推荐理由</th>'
            '</tr></thead><tbody>',
        ]

        for item in ranked[:15]:
            rec = item['recommendation']
            result = item['result']
            paper_data = result.raw if hasattr(result, 'raw') else result.get('raw', {})
            title = paper_data.get('title', result.title if hasattr(result, 'title') else '')
            url = result.url if hasattr(result, 'url') else result.get('url', '')
            citations = paper_data.get('citation_count', 0) or paper_data.get('citations', 0)

            dims = rec.dimensions

            def _score_bar(score: float) -> str:
                if score >= 70:
                    color = '#10b981'
                elif score >= 40:
                    color = '#f59e0b'
                else:
                    color = '#ef4444'
                return (
                    f'<span class="score-bar">'
                    f'<span class="score-bar-fill" style="width:{score:.0f}%;background:{color};"></span>'
                    f'</span>{score:.0f}'
                )

            parts.append(
                f'<tr>'
                f'<td>{rec.rank_in_group}</td>'
                f'<td><a href="{html.escape(url)}" target="_blank">{html.escape(str(title)[:50])}</a></td>'
                f'<td>{citations}</td>'
                f'<td><strong>{rec.total_score:.1f}</strong></td>'
                f'<td><span class="grade-badge grade-{rec.grade.replace(" ", "")}">{rec.grade}</span></td>'
                f'<td>{_score_bar(dims.get("citation_impact", 0))}</td>'
                f'<td>{_score_bar(dims.get("recency", 0))}</td>'
                f'<td>{_score_bar(dims.get("authority", 0))}</td>'
                f'<td>{_score_bar(dims.get("author_h_index", 0))}</td>'
                f'<td>{_score_bar(dims.get("relevance", 0))}</td>'
                f'<td class="recommendation-reason">{html.escape(rec.recommendation_reason[:80])}</td>'
                f'</tr>'
            )

        parts.append('</tbody></table>')

        # 论文雷达图（前 5 篇）
        if len(ranked) >= 1:
            radar_items = []
            for item in ranked[:5]:
                rec = item['recommendation']
                result = item['result']
                paper_data = result.raw if hasattr(result, 'raw') else result.get('raw', {})
                title = paper_data.get('title', '论文')
                radar_items.append({
                    'label': title[:30],
                    'scores': rec.dimensions,
                })

            dim_labels = {
                'citation_impact': '引用影响', 'recency': '时效',
                'authority': '权威', 'author_h_index': 'h-index',
                'relevance': '相关',
            }
            radar_svg = RadarChartGenerator.generate(
                items=radar_items,
                dimensions=['citation_impact', 'recency', 'authority', 'author_h_index', 'relevance'],
                dimension_labels=dim_labels,
                max_items=5,
                size=400,
            )
            parts.append('<h4>📊 论文推荐度雷达图（前 5 篇对比）</h4>')
            parts.append(f'<div class="radar-container">{radar_svg}</div>')

        return '\n'.join(parts)

    def _html_quality(
        self, plan: Any, results: List[Any],
        verification: Optional[Any], reflections: Optional[Any]
    ) -> str:
        """调研质量自评"""
        # 覆盖率
        hist = as_reflection_history(reflections)
        coverage = hist.final_coverage if hist else 0
        rounds = hist.total_rounds if hist else 0

        # 验证率
        verification_rate = verification.verification_rate if verification else 0

        # 矛盾处理率
        contradiction_rate = 0
        if verification and verification.contradictions:
            # 简化：假设所有矛盾都已被处理（实际由 Claude 标注）
            contradiction_rate = 1.0

        # 综合质量分
        quality_score = (coverage * 0.4 + verification_rate * 0.4 + contradiction_rate * 0.2) * 100

        return f"""<h2 id="quality">7. 调研质量自评</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{coverage:.0%}</div>
                <div class="stat-label">覆盖率</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{verification_rate:.0%}</div>
                <div class="stat-label">验证率</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{rounds}</div>
                <div class="stat-label">反思轮次</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{quality_score:.0f}</div>
                <div class="stat-label">综合质量分</div>
            </div>
        </div>
        <blockquote>
            <p>📊 <strong>质量评估说明</strong></p>
            <p>覆盖率：调研维度被结果覆盖的比例</p>
            <p>验证率：已验证结论（≥2 独立来源）占总结论的比例</p>
            <p>反思轮次：深度调研中执行的 Plan-Execute-Reflect 循环次数</p>
        </blockquote>"""

    # ------------------------------------------------------------
    # Markdown 报告
    # ------------------------------------------------------------

    def _generate_markdown(
        self, plan: Any, results: List[Any],
        verification: Optional[Any], reflections: Optional[Any],
        ledger: Optional[Any] = None, options: Optional[Dict[str, Any]] = None
    ) -> str:
        """生成 Markdown 报告"""
        topic = getattr(plan, 'topic', '调研报告') if plan else '调研报告'
        lines = [
            f"# {topic}",
            "",
            f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**数据源数**：{len(set(r.source if hasattr(r, 'source') else r.get('source', '') for r in results))}",
            "",
        ]

        # v6.0：调研元信息
        if options:
            lines.append('**调研配置（v6.0）**：')
            for key, label in [('effort', '努力程度'), ('breadth', '并行子主题数'),
                               ('depth', '深度'), ('perspectives', '专家团视角'),
                               ('validation', '发布校验')]:
                if options.get(key) is not None:
                    lines.append(f'- {label}：{options[key]}')
            lines.append('')

        lines += [
            "## 1. 执行摘要",
            "",
            f"本次调研共收集 {len(results)} 条结果。",
        ]

        if verification:
            lines.append(f"- 已验证结论：{len(verification.verified_claims)} 条")
            lines.append(f"- 单源结论：{len(verification.single_source_claims)} 条")
            lines.append(f"- 矛盾点：{len(verification.contradictions)} 个")
            lines.append(f"- 验证率：{verification.verification_rate:.0%}")

        # 引用列表
        lines.extend(["", "## 2. 引用列表", "",
                       "| # | 标题 | 来源 | CRAAP 分 | 等级 |",
                       "|---|------|------|----------|------|"])
        for i, r in enumerate(results, 1):
            title = r.title if hasattr(r, 'title') else r.get('title', '')
            source = r.source if hasattr(r, 'source') else r.get('source', '')
            craap = r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {})
            total = craap.get('total', 0) if craap else 0
            grade = craap.get('grade', '') if craap else ''
            lines.append(f"| {i} | {title[:40]} | {source} | {total:.1f} | {grade} |")

        # 已验证结论
        if verification and verification.verified_claims:
            lines.extend(["", "## 3. 已验证结论", ""])
            for claim in verification.verified_claims:
                lines.append(f"### ✅ {claim.statement}")
                lines.append(f"- 置信度：{claim.confidence:.0%}")
                lines.append(f"- 独立来源：{claim.get_independent_source_count()} 个")
                lines.append("")

        # 矛盾点
        if verification and verification.contradictions:
            lines.extend(["", "## 4. 矛盾点", ""])
            for con in verification.contradictions:
                lines.append(f"- **A**: {con.claim_a}")
                lines.append(f"- **B**: {con.claim_b}")
                lines.append(f"- **原因**: {con.possible_reason}")
                lines.append("")

        # v6.0：证据账本摘要 + 来源 Tier 分布（附录 D）
        stats = self._ledger_stats(ledger)
        if stats and stats['topic_stats']:
            lines.extend(["", "## 附录 D：证据账本与来源 Tier 分布（v6.0）", ""])
            lines.extend([
                "| 子主题 | claims | verified | conflict | 独立来源 | 覆盖 | 充分 |",
                "|--------|--------|----------|----------|----------|------|------|",
            ])
            for t, s in sorted(stats['topic_stats'].items()):
                mark = '✅' if s.get('sufficient') else '⚠️'
                lines.append(f"| {t} | {s['claims']} | {s['verified']} | {s['conflict']} "
                             f"| {s['independent_sources']} | {s['coverage']:.0%} | {mark} |")
            if stats['tier_dist']:
                lines.extend(["", "**来源 Tier 分布**：", ""])
                for tier in sorted(stats['tier_dist']):
                    label = {1: '官方/学术', 2: '权威/官方文档', 3: '一般', 4: '社区/低质'}.get(tier, str(tier))
                    lines.append(f"- Tier {tier}（{label}）：{stats['tier_dist'][tier]} 条")

        return '\n'.join(lines)

    # ------------------------------------------------------------
    # JSON 报告
    # ------------------------------------------------------------

    def _generate_json(
        self, plan: Any, results: List[Any],
        verification: Optional[Any], reflections: Optional[Any],
        ledger: Optional[Any] = None, options: Optional[Dict[str, Any]] = None
    ) -> str:
        """生成 JSON 报告"""
        report = {
            'metadata': {
                'topic': getattr(plan, 'topic', '') if plan else '',
                'goal': getattr(plan, 'goal', '') if plan else '',
                'depth': getattr(plan, 'depth', '') if plan else '',
                'generated_at': datetime.now().isoformat(),
                'total_results': len(results),
            },
            'results': [
                {
                    'title': r.title if hasattr(r, 'title') else r.get('title', ''),
                    'url': r.url if hasattr(r, 'url') else r.get('url', ''),
                    'source': r.source if hasattr(r, 'source') else r.get('source', ''),
                    'craap_score': r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {}),
                }
                for r in results
            ],
        }

        # v6.0：元信息 + 证据账本
        if options:
            report['metadata']['v6_options'] = options
        ledger_stats = self._ledger_stats(ledger)
        if ledger_stats:
            report['v6_ledger'] = {
                'claims': ledger_stats['claims'],
                'sources': ledger_stats['sources'],
                'sufficient_topics': ledger_stats['sufficient_topics'],
                'topic_stats': {t: s for t, s in ledger_stats['topic_stats'].items()},
                'tier_distribution': ledger_stats['tier_dist'],
            }

        if verification:
            report['verification'] = {
                'verified_claims': [c.to_dict() for c in verification.verified_claims],
                'single_source_claims': [c.to_dict() for c in verification.single_source_claims],
                'contradictions': [c.to_dict() for c in verification.contradictions],
                'verification_rate': verification.verification_rate,
            }

        hist = as_reflection_history(reflections)
        if hist:
            report['reflections'] = hist.to_dict()

        return json.dumps(report, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------
    # CSV 导出
    # ------------------------------------------------------------

    def _generate_csv(self, results: List[Any]) -> str:
        """生成 CSV 来源列表"""
        from io import StringIO
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['#', 'Title', 'URL', 'Source', 'CRAAP Total', 'Grade',
                         'Currency', 'Relevance', 'Authority', 'Accuracy', 'Purpose',
                         'Published Date', 'Author'])

        for i, r in enumerate(results, 1):
            title = r.title if hasattr(r, 'title') else r.get('title', '')
            url = r.url if hasattr(r, 'url') else r.get('url', '')
            source = r.source if hasattr(r, 'source') else r.get('source', '')
            craap = r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {})
            published = r.published_date if hasattr(r, 'published_date') else r.get('published_date', '')
            author = r.author if hasattr(r, 'author') else r.get('author', '')

            writer.writerow([
                i, title, url, source,
                craap.get('total', 0) if craap else 0,
                craap.get('grade', '') if craap else '',
                craap.get('currency', 0) if craap else 0,
                craap.get('relevance', 0) if craap else 0,
                craap.get('authority', 0) if craap else 0,
                craap.get('accuracy', 0) if craap else 0,
                craap.get('purpose', 0) if craap else 0,
                published, author,
            ])

        return output.getvalue()


# ============================================================
# 便捷函数
# ============================================================

def generate_report(
    plan: Any,
    results: List[Any],
    verification: Optional[Any] = None,
    reflections: Optional[Any] = None,
    format: str = 'html',
    output_path: Optional[str] = None,
    ledger: Optional[Any] = None,
    options: Optional[Dict[str, Any]] = None,
) -> str:
    """便捷函数：生成报告（v6.0 支持 ledger/options）"""
    reporter = ReportGenerator()
    return reporter.generate(plan, results, verification, reflections, format,
                             output_path, ledger=ledger, options=options)


# ============================================================
# CLI 入口
# ============================================================

def _main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description='生成调研报告')
    parser.add_argument('--format', default='html', choices=['html', 'markdown', 'json', 'csv'])
    parser.add_argument('--output', default='report.html')
    parser.add_argument('--results', help='结果 JSON 文件')
    args = parser.parse_args()

    # 简单测试
    class MockPlan:
        topic = "测试调研"
        goal = "测试"
        depth = "standard"
        estimated_duration = "3-5 分钟"
        dimensions = ['维度1', '维度2']
        issue_tree = []

    mock_results = [
        type('R', (), {
            'title': '测试结果 1',
            'url': 'https://example.com/1',
            'content': '测试内容',
            'source': 'tavily',
            'published_date': '2025-01-01',
            'author': '',
            'craap_score': {'total': 85, 'grade': 'high', 'currency': 90, 'relevance': 85, 'authority': 80, 'accuracy': 85, 'purpose': 80},
        })(),
    ]

    reporter = ReportGenerator()
    content = reporter.generate(MockPlan(), mock_results, format=args.format, output_path=args.output)
    print(f"报告已生成: {args.output}")


if __name__ == "__main__":
    _main()
