"""v6.19.1 回归：一条 claim 的引用不许牵连到共享同一来源的别的 claim。

实测（2026-09-24 端到端实跑，报告 93 条 claim / 172 条来源，过门时）：
校验门报"2 条 claim 被报告引用但没有验证：c-d2-03、c-d3-02"，而这两条在正文里
根本没被当作结论引用过——它们只是与已验证的 claim **共用同一条来源 URL**：
  c-d2-01(verified) 与 c-d2-03(pending) 都挂 tex.stackexchange 那两条；
  c-d3-03(verified) 与 c-d3-02(pending) 都挂 ALCE 那篇 doi.org/10.18653/v1/2023.emnlp-main.398。
骨架把每条 claim 渲染成独立一行、行尾带该行自己的编号，Lead 读到的是"这一行在说这条 claim"。
而 cited_claim_ids 只按编号→claim 的全局映射归因（且同号后写者覆盖先写者），
于是已验证那一行的编号会替未验证的那条 claim"立论"，报告里根本没有对应的句子。

这个方向的误拦比误放更坏：Lead 拿什么改动正文都消不掉它（除非把已验证 claim 的引用
也删掉，或给 verified 的行错加 ⚠️），最后只能靠删证据或绕开门来过——正是本工具要防的。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validate_report import cited_claim_ids  # noqa: E402

# 同一 URL 被两条 claim 各登记一次，于是两个编号指向同一个 URL
SOURCES = [
    {'primary_index': 1, 'claim_id': 'cA', 'url': 'https://tex.example/8332'},
    {'primary_index': 2, 'claim_id': 'cA', 'url': 'https://tex.example/43276'},
    {'primary_index': 3, 'claim_id': 'cB', 'url': 'https://tex.example/8332'},   # 与 cA 同号源
]
CLAIMS = [
    {'id': 'cA', 'text': '对齐校验的最小正确形态是两个方向的集合差，不是查编号有没有重复'},
    {'id': 'cB', 'text': '校验时机和报错定位是这套门能不能落地的关键，必须排在渲染收敛之后'},
]


def test_verified_claims_line_does_not_put_a_sibling_on_trial():
    """cA 那行引用 [1][2]，不应当成"cB 也被正文引用且未标 ⚠️"。"""
    report = (
        "## 引用对齐与一致性校验\n\n"
        "- 对齐校验的最小正确形态是两个方向的集合差，不是查编号有没有重复 [1][2]\n"
        "- ⚠️ 仅作线索：校验时机和报错定位是这套门能不能落地的关键，必须排在渲染收敛之后 [3]"
        "（状态 pending，未达 verified 判据）\n"
    )
    unmarked, marked = cited_claim_ids(report, SOURCES, CLAIMS)
    assert 'cA' in unmarked, '已验证 claim 自己的行应当照常归因给它'
    assert 'cB' not in unmarked, 'cA 那行的编号把未验证的 cB 也算成了"正文引用"'
    assert 'cB' in marked, 'cB 自己那行带了 ⚠️，应记为已明示降级'


def test_prose_outside_claim_lines_still_attributes_by_number():
    """段落里（不属于任何 claim 行）引用编号，仍按编号→claim 归因。

    那才是真正"拿未验证证据下结论"的形态：Lead 在摘要或结论里直接引一个编号，
    该编号背后的 claim 若还是 pending 就必须报出来——行级归因只豁免"别人的那一行"，
    不豁免自己的正文句子。
    """
    report = "## 执行摘要\n\n集合差与时机两条判据共同支撑本结论 [1][3]。\n"
    unmarked, _ = cited_claim_ids(report, SOURCES, CLAIMS)
    assert {'cA', 'cB'} <= unmarked, '段落级引用的归因被误删'


def test_old_two_arg_call_still_works():
    """兼容既有调用形状（未传 claims 时退回全局归因），不破坏别的入口。"""
    report = "- 随便一句结论 [3]\n"
    unmarked, _ = cited_claim_ids(report, SOURCES)
    assert 'cB' in unmarked
