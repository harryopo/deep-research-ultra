"""arXiv 406 的处置指引：上游拒答 ≠ 没配好 MCP，也 ≠ 这个主题没资料。

实测（2026-09-24，逐发隔离、间隔 90s）：
- search_query=cat:cs.CL（带不带 sortBy 都一样）→ HTTP 200，正常出条目；
- search_query=all:electron（裸关键词）→ **HTTP 406**，与间隔无关；
- 连发 4 发以上（间隔 ≤6s）→ 全部 406，包括本来能通的分类查询。

所以 406 有两个来源：查询形态、请求频率。两者都不该把 MCP server 说成"没连上"，
更不该让人以为"这个主题查不到东西"。修之前实测的提示正是这么写的：
"需在当前会话连上对应 MCP server…没连上就等于没有这个源"——server 明明连上了，
是 arXiv 把它的行为查询拒了。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import probe  # noqa: E402


def _advice(note: str, kind: str = 'mcp', engine: str = 'arxiv') -> str:
    rep = {'engine': engine, 'status': probe.STATUS_FAILED, 'note': note,
           'kind': kind, 'requires_config': False, 'config_keys': []}
    return ' | '.join(probe._advice_for(rep))


def test_406_advice_does_not_claim_the_server_is_unconnected():
    text = _advice('arxiv: arXiv API HTTP error (HTTP 406)')
    assert '没连上就等于没有这个源' not in text, \
        f'上游拒答被说成了 server 没连上：{text}'


def test_406_advice_names_both_real_causes_and_the_retry_action():
    text = _advice('arxiv: arXiv API HTTP error (HTTP 406)')
    assert '406' in text
    for kw in ('分类', '间隔'):        # 查询形态 + 频率，两条都得给
        assert kw in text, f'提示缺 {kw} 这一条处置动作：{text}'
    assert '无资料' in text, f'要拦住「这个主题没资料」的错误结论：{text}'


def test_406_advice_applies_to_direct_engines_too():
    """直连引擎（arxiv-fulltext）撞的是同一个上游，指引不能只给 MCP。"""
    text = _advice('HTTP 406', kind='direct')
    assert '分类' in text and '间隔' in text, text


def test_arxiv_specific_step_stays_off_other_sources():
    """实测 openalex 也会 429，但"把查询换成分类型（cat:cs.CL）"只对 arXiv 有意义。

    提示里塞进无关源的动作，Lead 会照着去改一个根本不适用的参数。
    """
    other = _advice('openalex: HTTP 429 rate limited', kind='direct', engine='openalex')
    assert 'cat:cs.CL' not in other, f'arXiv 专属步骤串给了 openalex：{other}'
    assert '间隔' in other, other
    arxiv = _advice('arxiv: arXiv API HTTP error (HTTP 406)', engine='arxiv')
    assert 'cat:cs.CL' in arxiv, arxiv



def test_generic_timeout_advice_still_unaffected():
    """不许因为加了 406 分支就把别的失败原因一起改掉。"""
    text = _advice('arxiv: 超时：整场会话 25s 预算内没等到响应')
    assert '预热' in text, text


def test_mcp_probe_query_for_arxiv_is_a_category_query():
    """探针词若是裸关键词，arXiv 恒 406，这个源就永远被误判成坏。"""
    q = probe.PROBE_QUERIES['arxiv']
    assert q.startswith('cat:'), f'arxiv MCP 探针词该用分类式查询，当前是 {q!r}'
