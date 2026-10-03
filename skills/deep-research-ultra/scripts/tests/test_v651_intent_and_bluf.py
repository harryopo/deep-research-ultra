"""v6.51 回归：意图澄清三段式 + 结论前置的「一页拍板」。

这版改的是两件用户能直接感觉到的事：

一、澄清从"列参数"变成"问意图"
------------------------------------------------
改之前 Phase 1 第 1 步只有一句"主题澄清（AskUserQuestion）：调研目标 /
深度 / 维度 / 时间范围"——问的是**参数**，不是**意图**。所以用户说
"调研开源考研软件"，会直接跳到 MECE 拆解和搜库。

而这句话里没有任何决策信息：可能是要选型报志愿、可能是要做毕设、
可能要集成进产品。三种目的要的维度几乎没有交集（选型看维护度与许可证，
毕设看文档与难度，集成看 API 稳定性与部署成本）。不问清楚，搜回来的
材料再详实也答不上他真正想问的那件事。

v6.51 改成三段式：分流（决策类/知识类）→ 强制澄清（用途/受众/期望结论）
→ Lead 推断+确认。配套 `references/intent-types.md` 给五类信息需求各自
的"该问维度 / 不相关维度 / 该问的第一个问题"。

二、报告结构：结论前置
------------------------------------------------
改之前的结构按子问题排列（1. 子问题1 / 2. 子问题2 / … / 时间线 / 结论与建议），
那是**研究过程的结构**，不是**读者需要的结构**：读者想知道结论，得先读完
所有章节才到"结论与建议"。

现在开头是「一页拍板」，直接给推荐 + 风险 + 下一步。这节光有标题不够——
写"各有优劣、看你需求"等于没拍，所以加了机械门。

本文件测的是这两件事的**机械部分**（章节校验、一页拍板质量门、
骨架是否生成该节）。意图澄清本身是 prompt 里的判断，测不了机械判据；
这里能钉住的是"规则落到文档与代码里没有走样"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SKILL_MD = Path(__file__).resolve().parents[2] / 'SKILL.md'
INTENT_MD = Path(__file__).resolve().parents[2] / 'references' / 'intent-types.md'


# ============================================================
# 一页拍板：章节校验
# ============================================================

BLUF_OK = (
    '## 一页拍板\n\n'
    '直接结论：选 crewAI。它维护最活跃、MIT 许可、无企业版限制 [1][2]。\n'
    '主要风险：生态里第三方集成质量参差，官方文档未覆盖全部场景 [3]。\n'
    '下一步：先在内部工具上跑两周试点。\n'
)

FULL_REPORT = (
    '# T\n\n' + BLUF_OK +
    '\n## 执行摘要\n\n摘要给出核心结论与置信度 [1]。\n\n'
    '## 调研方法\n\n方法说明 [1]。\n\n'
    '## 结论与建议\n\n结论与落地步骤 [1]。\n\n'
    '## 来源\n\n| 编号 | Tier | 标题 | URL |\n|---|---|---|---|\n'
    '| [1] | 1 | P | https://arxiv.org/abs/1 |\n'
    '| [2] | 1 | P2 | https://arxiv.org/abs/2 |\n'
    '| [3] | 2 | P3 | https://github.com/a/b |\n'
)


def test_bluf_section_is_required():
    """没有「一页拍板」的报告过不了门。"""
    from validate_report import REQUIRED_SECTIONS, _section_missing
    assert '一页拍板' in REQUIRED_SECTIONS, '必需章节表里没有一页拍板'
    without = FULL_REPORT.replace('## 一页拍板', '## 开头的碎念')
    # 直接问章节判定，别让别的 issue 抢先——full 报告本该是干净的
    assert _section_missing(without, '一页拍板',
                            REQUIRED_SECTIONS['一页拍板']) is True
    assert _section_missing(FULL_REPORT, '一页拍板',
                            REQUIRED_SECTIONS['一页拍板']) is False


def test_report_with_bluf_passes():
    from validate_report import validate_report
    r = validate_report(FULL_REPORT)
    assert not any('一页拍板' in i for i in r.issues), r.issues


def test_skeleton_generates_bluf_section():
    """骨架必须先把这一节立出来，否则 Lead 不会想到要写。"""
    from ledger import ResearchLedger
    from skeleton import build_skeleton
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        L = ResearchLedger(f'{d}/ledger').init()
        cid = L.add_claim('某框架维护活跃', topic='格局', status='pending')['id']
        L.add_source(cid, 'https://arxiv.org/abs/1', title='P')
        md = build_skeleton(f'{d}/ledger', title='T')
    assert '## 一页拍板' in md
    # 位置必须在执行摘要之前
    assert md.index('## 一页拍板') < md.index('## 执行摘要')


# ============================================================
# 一页拍板：质量门（不许两头下注）
# ============================================================

def test_hedged_bluf_without_citations_is_rejected():
    from validate_report import audit_conclusion_citations
    hedged = (
        '## 一页拍板\n\n'
        + ('这些框架各有优劣、看你需求，需要进一步调研才能决定，'
           '这里只能给出初步判断，具体还要视情况而定，因人而异。' * 3)
        + '\n\n## 执行摘要\n\n摘要 [1]。\n\n'
        + '## 调研方法\n\n方法 [1]\n\n## 结论与建议\n\n结论 [1]\n\n'
        + '## 来源\n\n| 编号 | 标题 | URL |\n|---|---|---|\n'
        '| [1] | P | https://arxiv.org/abs/1 |\n'
    )
    issues, stats = audit_conclusion_citations(hedged)
    assert any('下注' in i or '拍板' in i for i in issues), issues


def test_hedged_bluf_with_citations_is_allowed():
    """给了编号、说明为什么无法给推荐——那是诚实，不是两头下注。"""
    from validate_report import audit_conclusion_citations
    md = (
        '## 一页拍板\n\n'
        '本次不给推荐：A 方案与 B 方案的差异只在 2026 年后的新增特性上，'
        '而两边现有用户量都没查到可交叉的数据，任何推荐都是猜 [1][2][3]。\n'
        '下一步：补齐两边的用户量数据再定。\n\n'
        '## 执行摘要\n\n摘要 [1]。\n\n## 调研方法\n\n方法 [1]\n\n'
        '## 结论与建议\n\n结论 [1]\n\n'
        '## 来源\n\n| 编号 | 标题 | URL |\n|---|---|---|\n'
        '| [1] | P | https://arxiv.org/abs/1 |\n'
        '| [2] | P2 | https://arxiv.org/abs/2 |\n'
        '| [3] | P3 | https://github.com/a/b |\n'
    )
    issues, stats = audit_conclusion_citations(md)
    assert not any('下注' in i for i in issues), issues


def test_decisive_bluf_is_fine():
    from validate_report import audit_conclusion_citations
    issues, stats = audit_conclusion_citations(FULL_REPORT)
    assert not issues, issues
    assert stats['bluf_citations'] >= 1


# ============================================================
# 意图澄清：文档层（判据表在不在、规则有没有走样）
# ============================================================

def test_intent_types_file_exists_and_covers_five_types():
    assert INTENT_MD.exists(), '缺 references/intent-types.md'
    s = INTENT_MD.read_text(encoding='utf-8')
    for t in ['决策选型', '认知理解', '落地实施', '产品规划', '风险审查']:
        assert t in s, f'信息需求类型表缺「{t}」'


def test_intent_types_table_has_all_four_columns():
    """每类都要给：识别信号 / 该问维度 / 不相关维度 / 第一个问题。"""
    s = INTENT_MD.read_text(encoding='utf-8')
    for col in ['识别信号', '该问维度', '不相关', '第一个问题']:
        assert s.count(col) >= 5, f'「{col}」列没在 5 类里都出现'


def test_skill_md_has_three_stage_clarification():
    s = SKILL_MD.read_text(encoding='utf-8')
    assert '三段式澄清' in s
    assert '分流' in s and '强制澄清' in s and '推断' in s


def test_goal_no_longer_advertises_skipping_clarification():
    """`--goal` 旧说明是"明确目标可跳过澄清"——那是在鼓励跳过。

    argparse 建在 _main 内部，这里直接查源码里那行 help 文本。
    """
    src = (SKILL_MD.parent / 'scripts' / 'research.py').read_text(encoding='utf-8')
    goal_line = [l for l in src.split('\n') if "'--goal'" in l]
    assert goal_line, '找不到 --goal 定义'
    assert '跳过澄清' not in goal_line[0], \
        f'--goal 说明还在鼓励跳过澄清：{goal_line[0].strip()[:80]}'


def test_intent_is_recorded_in_plan():
    """类型判定要进计划，否则子 Agent 不知道每条证据为谁服务。"""
    s = SKILL_MD.read_text(encoding='utf-8')
    assert '记录进账本' in INTENT_MD.read_text(encoding='utf-8')
    assert '--goal' in s
