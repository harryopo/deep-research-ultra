"""v6.38.0 回归：--plan-only 不许把没配置的引擎写进数据源。

报告 A18（09-28 的 A2 重犯，2026-09-29 一轮实跑）：同会话 `--probe` 已判 `tavily`
"缺少配置: TAVILY_API_KEY"，而 `--plan-only` 给出的 8 个子问题里 6 个的数据源仍写着 tavily。
当场复现：输出的两行"数据源: tavily, open-websearch, websearch"。

v6.36.0 只把 `--route` 的建议 `--sources` 按配置就绪过滤了；plan 这条路径没接同一个判据，
Lead 照计划派子 Agent，子 Agent 撞上未配置引擎就回 0 条——像搜过了，实际一条没打出去。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plan import (  # noqa: E402
    ResearchPlan, SubQuestion, prune_unconfigured_sources,
)


def _plan():
    leaf_bad = SubQuestion(id='q1', question='现状', data_sources=['tavily', 'open-websearch'])
    leaf_ok = SubQuestion(id='q2', question='路线', data_sources=['openalex', 'github-deep-search'])
    only_bad = SubQuestion(id='q3', question='反例', data_sources=['tavily'])
    root = SubQuestion(id='r', question='主题', data_sources=['tavily'],
                       children=[leaf_bad, leaf_ok, only_bad])
    return ResearchPlan(topic='t', issue_tree=[root])


def test_unconfigured_engines_are_dropped_configured_kept():
    p = _plan()

    dropped, emptied = prune_unconfigured_sources(p, {'open-websearch', 'openalex',
                                                       'github-deep-search'})

    assert dropped == ['tavily'], f"未配置的引擎没被摘干净: {dropped}"
    q1 = p.issue_tree[0].children[0]
    assert q1.data_sources == ['open-websearch'], q1.data_sources
    q2 = p.issue_tree[0].children[1]
    assert q2.data_sources == ['openalex', 'github-deep-search'], q2.data_sources


def test_leaf_left_without_a_source_is_named_not_silenced():
    """摘完就空的节点必须逐个点名：留一行空数据源，Lead 会以为这一路已经排好了。

    夹具里根节点也只配了 tavily，所以被打空的是 r 与 q3 两个——点名按节点不按层级，
    渲染时每个节点都印数据源，漏印一个就是漏一路。
    """
    p = _plan()

    dropped, emptied = prune_unconfigured_sources(p, {'open-websearch', 'openalex',
                                                      'github-deep-search'})

    assert emptied == ['r', 'q3'], f"被打空的节点没报全: {emptied}"


def test_all_configured_plan_is_untouched():
    """正向对照：全都配置就绪时一个不许动、一声不许吭。"""
    p = _plan()
    for q in [p.issue_tree[0]] + p.issue_tree[0].children:
        q.data_sources = ['openalex']

    dropped, emptied = prune_unconfigured_sources(p, {'openalex'})

    assert dropped == [] and emptied == []
    assert p.issue_tree[0].children[0].data_sources == ['openalex']
