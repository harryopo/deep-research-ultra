"""v6.16 回归：克隆地址不是来源；结论段必须带账本引用。

两个缺口都来自 2026-10-02 的端到端实跑（AI Agent 方向，6 维度 82 条 claim）。

缺口一：`.git` 克隆地址被放行
------------------------------------------------
`_is_traceable()` 的判据是 `^https?://[^\s/]+`，于是
`https://github.com/ShanglinWu/LLM-MAS_Memory_Survey.git` 过了闸门。
但那是 `git clone` 用的地址，浏览器打开不返回仓库页、更不返回正文——
它点不回原文，却照样拿到一个 `primary_index` 进报告的引用登记表。
这与 test_v6155_source_traceable.py 立下的规矩同源：假溯源不得占引用编号。
区别在于那一轮拦的是站内相对链接与口头指代，这一轮拦的是"协议对、用途错"。

缺口二：结论与建议段可以整段零引用
------------------------------------------------
`cited_claim_ids()` 按行归因：某行的编号只代表"这条 claim 被引用"。
Lead 手写的「结论与建议」「执行摘要」「调研方法」三段没有 claim 行归属，
于是即便一个字引用都不写，也没有任何校验项会拦——实测一轮 1791 字的结论段
0 个 `[N]`，照样盖戳。这违反 SKILL.md 十六自己写的「禁止结论无账本引用」：
铁律只落在 claim 行上，Lead 自己写的判断反而是盲区。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger, _is_traceable  # noqa: E402


# ============================================================
# 缺口一：克隆地址 / 非网页地址不得当来源
# ============================================================

CLONE = 'https://github.com/ShanglinWu/LLM-MAS_Memory_Survey.git'
SSH_CLONE = 'git@github.com:x/y.git'
BLOB = 'https://github.com/x/y/blob/main/README.md'


@pytest.mark.parametrize('url', [
    CLONE,
    'https://gitlab.com/g/p.git',
    'https://github.com/x/y.git/',
    'https://github.com/x/y.GIT',
])
def test_clone_urls_are_not_traceable(url):
    """git 克隆地址点不开网页正文，不是来源。"""
    assert _is_traceable(url) is False


def test_ordinary_urls_still_traceable():
    """正向对照：真网页地址不能被一起挡掉。"""
    for url in [
        'https://github.com/x/y',                       # 仓库页
        BLOB,                                            # 文件页
        'https://github.com/x/y/tree/main',              # 分支目录
        'https://arxiv.org/abs/2401.12345',              # 论文页
        'https://doi.org/10.1007/s44336-024-00009-2',    # DOI 解析
        'https://link.springer.com/article/10.1007/x',   # 出版方页
    ]:
        assert _is_traceable(url) is True, url


def test_ssh_clone_still_refused():
    """SSH 形式本来就被 `^https?://` 挡住，别在改版里漏掉。"""
    assert _is_traceable(SSH_CLONE) is False


def test_add_source_refuses_clone_url(tmp_path):
    """封口在写入侧：不能让克隆地址占掉一个引用编号。"""
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    cid = L.add_claim('某仓库的现状是 X', topic='格局')['id']
    with pytest.raises(ValueError) as e:
        L.add_source(cid, CLONE)
    assert '.git' in str(e.value)
    assert [x['url'] for x in L._all() if x.get('type') == 'source'] == []


def test_add_source_still_accepts_repo_page(tmp_path):
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    cid = L.add_claim('某仓库的现状是 X', topic='格局')['id']
    entry = L.add_source(cid, 'https://github.com/x/y', title='仓库页')
    assert entry['url'] == 'https://github.com/x/y'


# ============================================================
# 缺口二：结论段必须带账本引用
# ============================================================

MIN_CONCLUSION_CHARS = 120  # 短结论不算"无引用"；低于此长度不值得逼引用


def _report(conclusion: str) -> str:
    return (
        '# T\n\n## 执行摘要\n\n摘要 [1]。\n\n'
        '## 调研方法\n\n方法说明。\n\n'
        f'## 结论与建议\n\n{conclusion}\n\n'
        '## 来源\n\n| 编号 | Tier | 标题 | URL |\n'
        '|---|---|---|---|\n| [1] | 1 | 论文 | https://arxiv.org/abs/2401.12345 |\n'
    )


def test_conclusion_without_citations_is_flagged():
    """1791 字零引用的结论段，v6.15 会盖戳放行——那是漏网。"""
    from validate_report import audit_conclusion_citations
    body = ('这是一段很长的结论，' * 40) + '没有任何引用编号。'
    issues, stats = audit_conclusion_citations(_report(body))
    assert issues, '零引用的长结论段必须被拦'
    assert stats['conclusion_chars'] >= MIN_CONCLUSION_CHARS
    assert stats['conclusion_citations'] == 0


def test_conclusion_with_citations_passes():
    from validate_report import audit_conclusion_citations
    body = ('结论一，需要依据 [1]。' * 30) + '另一条依据 [2]。'
    issues, stats = audit_conclusion_citations(_report(body))
    assert not issues, issues
    assert stats['conclusion_citations'] >= 2


def test_short_conclusion_is_exempt():
    """一句话结论不该被逼着挂引用。"""
    from validate_report import audit_conclusion_citations
    issues, _ = audit_conclusion_citations(_report('用 MCP 接工具，用 A2A 接 agent。'))
    assert not issues


def test_only_counts_body_not_the_heading():
    """章节标题里的"结论"二字不该被算进结论段。"""
    from validate_report import audit_conclusion_citations
    md = '# T\n\n## 调研方法\n\n这里写「结论与建议」四个字但不是章节。\n\n## 来源\n\n| 编号 | Tier | 标题 | URL |\n|---|---|---|---|\n'
    issues, stats = audit_conclusion_citations(md)
    assert stats.get('conclusion_chars', 0) == 0
    assert not issues


def test_summary_section_also_audited():
    """执行摘要同样要求带引用——它是最常被直接抄进对外材料的一段。"""
    from validate_report import audit_conclusion_citations
    md = (
        '# T\n\n## 执行摘要\n\n' + ('摘要断言需要出处 [1]。' * 40) + '\n\n'
        '## 调研方法\n\n方法。\n\n## 结论与建议\n\n短结论。\n\n'
        '## 来源\n\n| 编号 | Tier | 标题 | URL |\n|---|---|---|---|\n| [1] | 1 | P | https://arxiv.org/abs/1 |\n'
    )
    issues, stats = audit_conclusion_citations(md)
    assert stats.get('summary_chars', 0) >= MIN_CONCLUSION_CHARS
    assert stats.get('summary_citations', 0) >= 1


def test_subsection_headings_do_not_truncate_measurement():
    """结论段里常有「### 一句话结论」这类子标题。

    遇到子标题就清空 current 会只量到子标题之前那几行——实测把 1791 字的
    结论段量成 136 字，恰好掉到阈值以下，门就漏过去了。子标题必须继承父节。
    """
    from validate_report import audit_conclusion_citations
    filler = '结论依据账本推导，' * 30          # ~240 字，在子标题之前
    after = '子标题之后的判断也要算进去，' * 30  # ~270 字，在子标题之后
    md = (
        '# T\n\n## 执行摘要\n\n摘要 [1]。\n\n'
        f'## 结论与建议\n\n{filler}\n\n### 一句话结论\n\n{after}\n\n'
        '## 来源\n\n| 编号 | Tier | 标题 | URL |\n|---|---|---|---|\n| [1] | 1 | P | https://arxiv.org/abs/1 |\n'
    )
    issues, stats = audit_conclusion_citations(md)
    assert stats['conclusion_chars'] >= len(filler) + len(after) - 20, stats
    assert issues, '零引用就该被拦——不能被子标题吃掉长度后逃过阈值'
