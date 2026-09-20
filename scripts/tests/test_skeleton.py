"""X-D14 回归：deep 档正文写不完时，脚手架由脚本给，占位内容不许出门。

起因（使用者点破的那堵墙）：deep 档定义 6000-15000 字、一次跑 2-3 轮，Lead 一轮
写不完又要过校验门，于是就有人落一份带占位内容的 report.md 声称"passed"。
修两头：
① skeleton.py 把纯机械的部分（引用编号、来源登记表、按主题分组的 claim 清单）
   从账本直接生成，Lead 只剩"取舍 + 连接 + 判断"；
② 骨架里的占位标记【待写】是校验门的硬失败项——骨架永远不可能被当成报告交付。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ledger import ResearchLedger
from skeleton import PLACEHOLDER, _main as skeleton_main, build_skeleton
from validate_report import registry_number_conflicts, validate_report

SKILL_MD = Path(__file__).resolve().parents[2] / 'SKILL.md'


@pytest.fixture()
def led(tmp_path):
    """两个主题、三条 claim（两条 verified、一条 pending），共五条来源。"""
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    c1 = L.add_claim('微服务拆分要看团队规模', '架构', 'verified', 'domain_expert', 0.9)
    L.add_source(c1['id'], 'https://arxiv.org/abs/2401.00001', title='拆分实证', tier=1)
    L.add_source(c1['id'], 'https://www.gov.cn/arch-guide', title='架构指南', tier=1)
    c2 = L.add_claim('拆分过细会推高运维成本', '架构', 'pending', 'skeptic', 0.5)
    L.add_source(c2['id'], 'https://blog.example.com/cost', title='一篇博客', tier=4)
    c3 = L.add_claim('平台团队先行更适合 20 人以下', '成本', 'verified', 'practitioner', 0.85)
    L.add_source(c3['id'], 'https://arxiv.org/abs/2401.00002', title='组织研究', tier=1)
    L.add_source(c3['id'], 'https://gitee.com/oschina/x', title='实践案例', tier=2)
    return L


def _heading_lines(md: str) -> str:
    return '\n'.join(l for l in md.splitlines() if l.startswith('#'))


def test_skeleton_carries_every_required_section(led):
    md = build_skeleton(str(led.root))
    heads = _heading_lines(md)
    for kw in ('执行摘要', '方法', '结论', '来源'):
        assert kw in heads, f'骨架缺章节：{kw}'


def test_citation_numbers_are_the_ledger_primary_indexes(led):
    md = build_skeleton(str(led.root))
    line = next(l for l in md.splitlines() if '微服务拆分要看团队规模' in l)
    assert '[1]' in line and '[2]' in line, f'引用编号没按账本编号落：{line}'


def test_registry_rows_resolve_to_one_url_each(led):
    md = build_skeleton(str(led.root))
    for url in ('https://arxiv.org/abs/2401.00001', 'https://www.gov.cn/arch-guide',
                'https://blog.example.com/cost', 'https://arxiv.org/abs/2401.00002',
                'https://gitee.com/oschina/x'):
        assert url in md, f'来源登记表漏了 {url}'
    assert registry_number_conflicts(md) == {}, '骨架自己把编号串了号'


def test_every_claim_lands_in_the_skeleton(led):
    md = build_skeleton(str(led.root))
    for c in led.claims():
        assert c['text'] in md, f'claim 没进骨架：{c["text"]}'


def test_unverified_claim_is_flagged_instead_of_settled(led):
    md = build_skeleton(str(led.root))
    line = next(l for l in md.splitlines() if '拆分过细会推高运维成本' in l)
    assert '⚠️' in line, f'pending claim 没标待核，读起来像已定论：{line}'


def test_skeleton_is_marked_as_unfinished(led):
    md = build_skeleton(str(led.root))
    assert PLACEHOLDER in md


def test_placeholder_fails_the_gate_and_blocks_the_stamp(led):
    """骨架被原样当成报告交出去，必须过不了门——这是 X-D14 的机器闸门。"""
    md = build_skeleton(str(led.root))
    result = validate_report(md, ledger_dir=str(led.root))
    assert result.passed is False
    assert any('占位' in i or '骨架' in i for i in result.issues), result.issues


def test_written_report_without_placeholder_is_not_flagged(led):
    md = '''# 报告
## 执行摘要
微服务拆分要看团队规模 [1][2]。
## 调研方法
两主题五源。
## 结论
结论稳定。
## 来源
| [1] | https://arxiv.org/abs/2401.00001 | 拆分实证 |
| [2] | https://www.gov.cn/arch-guide | 架构指南 |
| [3] | https://blog.example.com/cost | 一篇博客 |
| [4] | https://arxiv.org/abs/2401.00002 | 组织研究 |
| [5] | https://gitee.com/oschina/x | 实践案例 |
'''
    result = validate_report(md, ledger_dir=str(led.root))
    assert not any('占位' in i or '骨架' in i for i in result.issues), result.issues


def test_cli_writes_the_skeleton_to_a_file(tmp_path, led):
    out = tmp_path / 'report_skeleton.md'
    assert skeleton_main([str(led.root), '-o', str(out)]) == 0
    assert out.read_text(encoding='utf-8') == build_skeleton(str(led.root))


def test_cli_refuses_when_the_ledger_is_missing(tmp_path):
    out = tmp_path / 'report_skeleton.md'
    rc = skeleton_main([str(tmp_path / 'nope'), '-o', str(out)])
    assert rc != 0, '--session 指错层时必须硬停'
    assert not out.exists()


def test_skill_md_pins_the_one_round_per_session_rule():
    md = SKILL_MD.read_text(encoding='utf-8')
    assert 'skeleton.py' in md, 'SKILL.md 要写出骨架生成器，Lead 才不会手搓占位正文'
    assert '一个 session 一轮' in md, 'deep 档单轮产能红线得写进 SKILL.md'
