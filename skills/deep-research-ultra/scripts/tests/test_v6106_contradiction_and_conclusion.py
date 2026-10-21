# -*- coding: utf-8 -*-
"""v6.106：两个「该报警却没报警」的缺陷 —— 矛盾检测被合组吞掉、结论章读不懂 claim 形状。

## 缺陷 1：对立结论被合组吞掉

`verify()` 先按相似度把结论合并，再在**合并后的**列表上找对立词。
同一个工具的两条方向相反的结论（"LangChain 生态好" vs "LangChain 性能差"）
被判成「同一条结论」→ 合并 → 对立词检测只剩一条陈述 → **矛盾检测不到**。

实测：4 对用工具词表里的词写的对立结论，旧路径报 **0** 条，新路径报 **3** 条
（第 4 对检不出是另一回事：那两条共享的核心 token 不足 2 个，工具认不出是同一主体）。

**合并还有第二个坏处**：它把**相反的证据**挂到其中一条的陈述上 ——
报告里就会出现「引了一个说反了的来源」。所以对立的两条**不合并**。

v6.4 已经为**数值**矛盾修过同款缺陷（加第二个检测器 `_detect_numeric_contradictions`），
对立词这一支一直没跟上 —— 这一版补上。

## 缺陷 2：报告结论章读不懂 claim 的形状

报告的结论章只认账本 claim（dict：`text` + `sources`），
而 research.py 传进去的是 `verify.Claim`（对象：`statement` + `evidence`）
→ 正文读成空、来源数读成 0 → **每条结论都被标成「单源待确认」**，
v6.95 加的「已交叉验证 / 单源待确认」分档等于没生效。

## 这份测试盯住什么

1. 同组内的对立结论必须被检出（且**不合并**，相反的证据不许挂到同一条陈述上）；
2. 同立场、子串陷阱（两条都说「不安全」）**不许**报矛盾；
3. 报告结论章对**两种 claim 形状**都要读对：来源数分档正确、正文非空。
"""
from __future__ import annotations

import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

from verify import Claim, CrossVerifier, Evidence, VerificationResult  # noqa: E402


def _claim(cid, statement, n_sources=1, domain='a.example'):
    c = Claim(id=cid, statement=statement)
    for i in range(n_sources):
        c.add_evidence(Evidence(source_url=f'https://{domain}{i}.example/p',
                                source_domain=f'{domain}{i}.example'))
    return c


# ============================================================ 缺陷 1：矛盾检测


def test_opposite_claims_in_one_group_are_detected():
    """同主体、方向相反的结论 → 必须报矛盾（旧路径报 0 条）。"""
    v = CrossVerifier()
    r = v.verify([], claims=[
        _claim('ca', 'vLLM 速度快，吞吐高', 2),
        _claim('cb', 'vLLM 速度慢，显存占用高', 2, 'b.example'),
    ])
    assert len(r.contradictions) == 1, (
        "同组内的对立结论没被检出：%d 条" % len(r.contradictions))
    assert '快' in r.contradictions[0].possible_reason


def test_opposite_claims_are_not_merged_into_one():
    """对立的两条**不许合并** —— 合并会把相反的证据挂到同一条陈述上。"""
    v = CrossVerifier()
    r = v.verify([], claims=[
        _claim('ca', 'Milvus 稳定，扩展性强', 2),
        _claim('cb', 'Milvus 不稳定，运维成本高', 2, 'b.example'),
    ])
    assert len(r.contradictions) == 1
    assert len(r.verified_claims) == 0, \
        "对立的两条被合并成一条 verified 了 —— 相反的证据会挂在同一条陈述上"
    assert len(r.single_source_claims) == 0
    # 被标成矛盾的结论要从 verified/single 里移走（v6.3 的口径：total_claims 不少计）
    assert r.total_claims == 2


def test_same_stance_is_not_reported_as_contradiction():
    """同立场 → 不许报矛盾。"""
    v = CrossVerifier()
    r = v.verify([], claims=[
        _claim('ca', 'LangChain 生态好，工具丰富', 2),
        _claim('cb', 'LangChain 生态好，文档齐全', 2, 'b.example'),
    ])
    assert r.contradictions == []


def test_substring_trap_is_not_reported_as_contradiction():
    """'不安全' 含 '安全'：两条都说「不安全」不是矛盾。"""
    v = CrossVerifier()
    r = v.verify([], claims=[
        _claim('ca', '系统不安全，防护弱', 2),
        _claim('cb', '系统不安全，风险高', 2, 'b.example'),
    ])
    assert r.contradictions == [], "子串关系被当成了立场差异"


def test_stable_vs_unstable_is_detected():
    """'稳定' vs '不稳定'：子串关系不能把真矛盾挡掉。"""
    v = CrossVerifier()
    r = v.verify([], claims=[
        _claim('ca', 'Milvus 稳定，扩展性强', 2),
        _claim('cb', 'Milvus 不稳定，运维成本高', 2, 'b.example'),
    ])
    assert len(r.contradictions) == 1
    assert '稳定' in r.contradictions[0].possible_reason


# ============================================================ 缺陷 2：报告结论章


def _html_with_verification(claim):
    import report as rp
    from plan import ResearchPlan
    from engines.base import SearchResult
    plan = ResearchPlan(topic='t')
    res = [SearchResult(title='T', url='https://a.example/p', content='c',
                        source='web', score=0.5)]
    v = VerificationResult(query='q', verified_claims=[claim],
                           single_source_claims=[], contradictions=[],
                           total_results=1, total_claims=1,
                           verification_rate=1.0)
    return rp.generate_report(plan, res, verification=v, format='html')


def test_two_source_claim_is_marked_verified_with_its_text():
    """2 个来源的 verify.Claim → 「已交叉验证」+ 结论正文（不是空着）。"""
    html = _html_with_verification(_claim('c1', '有两条独立来源支持的说法', 2))
    assert '已交叉验证' in html
    assert '有两条独立来源支持的说法' in html, \
        "结论正文空着 —— 报告读的是 claim 的 text，而 verify.Claim 的字段叫 statement"


def test_one_source_claim_is_marked_single_source_with_its_text():
    html = _html_with_verification(_claim('c2', '只有单一来源支持的说法', 1))
    assert '单源待确认' in html
    assert '只有单一来源支持的说法' in html


def test_ledger_style_claim_still_works_in_the_conclusion_section():
    """账本形状（dict：text + sources）在**结论章**里也要读对。

    ⚠️ 只测结论章：HTML 报告的「子问题分析」章要求的是 verify.Claim 形状
    （`evidence` / `statement` / `confidence`）—— research.py 传进报告的
    正是它。结论章原先只认账本形状、现在两种都认；分析章的形状要求没动。
    """
    import report as rp

    class _V:
        verified_claims = [{'text': '账本形状的结论', 'sources': ['a', 'b']}]
        single_source_claims = []
        contradictions = []

    html = rp.ReportGenerator()._html_conclusion([], _V())
    assert '已交叉验证' in html
    assert '账本形状的结论' in html


# ============================================================ 复算入口


def test_contradictions_analysis_check_passes():
    """v6.106 的数字要能被复算（过程门会调它）。"""
    import subprocess
    r = subprocess.run(
        [sys.executable, str(S / 'analysis' / 'contradictions.py'), '--check'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=900)
    assert r.returncode == 0, "contradictions --check 没过：\n%s\n%s" % (
        r.stdout[-600:], r.stderr[-400:])
    assert '与 CHANGELOG v6.106 一致' in (r.stdout or '')
