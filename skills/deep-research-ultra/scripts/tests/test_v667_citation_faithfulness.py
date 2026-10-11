"""v6.67.0：引用忠实度（citation faithfulness）的边界——测出来、写清楚、给自查工具。

## 这次实验打到了什么

v6.62 堵住了"没有账本"（不给 `--ledger` 判未通过、拒绝盖章）——那是浅水区。
深水区的攻击是：

    账本里有一条 verified claim：「RAG 评测框架 A 的召回率 85%，高于框架 B」
    报告写  ：「框架 B 的召回率仅 62%，且单次查询成本高出 40% [1]」
    [1] 指向那条 claim 的真实来源；编号合法、URL 出现在报告里、无串号、章节齐全

→ `validate_report` **passed=True、0 issues、盖上了防伪戳**。

**结论要说清楚**：校验门证明的是"编号有对应来源"，**不是"这句话被那个来源支撑"**。
这正是 ACL 2026 测的 citation faithfulness / claim groundedness 两项指标，
也是这个 skill 宣称"可溯源"时最容易被读成"逐句可信"的那一层。

## 为什么这次不做成门禁

语义忠实要 NLI/LLM 判定，而本项目刻意把质量判断做成纯确定性规则
（`report.py` 的设计约束就是"纯规则、不依赖 LLM"）。硬做只有两条烂路：
放宽到抓不住（等于没有），或收紧到误报满天飞（门永远红，红到没人跑）。

所以本版的处置是**诚实标注边界 + 给自查工具**：
`claim_support.py` 只查作者手写段里"带引用 + 带数字"的句子，输出"这些数字在你
引用的 claim 里找不到，去核一下"。它不进校验门，退出码 1 也只是提醒。

## 本测试钉住的东西

1. **攻击样本必须真的穿过校验门**——防的是有人把实验结论写反；
2. **自查工具必须抓到那个攻击**——否则工具是装饰；
3. **正样本不许误报**——同一份 claim 被正确引用时必须干净；
4. **边界写进文档**——SKILL.md 与体检报告都要说明"校验门不保证语义忠实"。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from claim_support import check, _load_ledger, _registry_map  # noqa: E402
from ledger import ResearchLedger  # noqa: E402
from validate_report import validate_report, write_stamp  # noqa: E402

CLAIM_TEXT = 'RAG 评测框架 A 的召回率 85%，高于框架 B'

# 结论与 claim 相反，且数字（62% / 40%）在 claim 里根本不存在
ATTACK = '''# RAG 评测框架选型

## 一页拍板
选框架 A：其召回率 85% 领先 [1]，迁移成本可控。

## 执行摘要
框架 B 的召回率仅 62%，且单次查询成本高出 40% [1]。

## 调研范围与方法
检索 arXiv 与 PubMed，纳入近三年评测框架文献。

## 结论与建议
1. 排除框架 B：召回率仅 62% [1]。
2. 框架 B 的成本高出 40% [1]。

## 来源
[1] 框架评测对比 https://arxiv.org/abs/2401.15391
[2] 评测方法综述 https://arxiv.org/abs/2402.07483
'''

# 正样本：报告里的数字都来自 claim
HONEST = '''# RAG 评测框架选型

## 一页拍板
选框架 A：其召回率 85% 领先 [1]，迁移成本可控。

## 执行摘要
框架 A 的召回率为 85% [1]，高于其他候选。

## 调研范围与方法
检索 arXiv 与 PubMed，纳入近三年评测框架文献。

## 结论与建议
1. 采用框架 A：召回率 85% [1]。

## 来源
[1] 框架评测对比 https://arxiv.org/abs/2401.15391
[2] 评测方法综述 https://arxiv.org/abs/2402.07483
'''


@pytest.fixture()
def env(tmp_path):
    d = str(tmp_path / 'ledger')
    led = ResearchLedger(d).init()
    c = led.add_claim(CLAIM_TEXT, 'RAG 评测', 'verified', 'general', 0.9)
    led.add_source(c['id'], 'https://arxiv.org/abs/2401.15391', tier=1)
    led.add_source(c['id'], 'https://arxiv.org/abs/2402.07483', tier=1)
    return d


# ---------------------------------------------------------------------------
# 1. 攻击样本真的穿过了校验门（别把结论写反）
# ---------------------------------------------------------------------------

def test_the_attack_really_passes_the_quality_gate(env, tmp_path):
    """这是本次实验的核心事实：语义相反的报告能过门、能盖章。

    如果哪天这条红了，说明校验门加严了——那好事，但本测试的
    前提描述需要同步更新（不要默默让它变绿）。
    """
    r = validate_report(ATTACK, ledger_dir=env)
    assert r.passed, (
        f'攻击样本现在被拦住了（好事）：{r.issues}——'
        '本文件的 docstring 与体检报告需要同步更新')
    assert not r.issues, r.issues
    # 而且它拿得到防伪戳
    report = tmp_path / 'report.md'
    report.write_text(ATTACK, encoding='utf-8')
    line = write_stamp(str(report), env, r.stats)
    assert 'drux:validated' in line
    assert line in report.read_text(encoding='utf-8')


def test_honest_report_also_passes(env):
    """对照组：正样本同样过门——说明校验门对两者无差别，即它看不见语义。"""
    assert validate_report(HONEST, ledger_dir=env).passed


# ---------------------------------------------------------------------------
# 2. 自查工具：抓攻击、不误报
# ---------------------------------------------------------------------------

def test_self_check_catches_the_unsupported_numbers(env):
    claims, url_to_claims = _load_ledger(env)
    reg = _registry_map(ATTACK, url_to_claims)
    checked, unsup = check(ATTACK, claims, reg)
    assert checked > 0, '攻击样本里一个"带引用+带数字"的句子都没有，检查没生效'
    found = {u['number'] for u in unsup}
    assert any('62' in n for n in found), f'没抓到 62%：{unsup}'
    assert any('40' in n for n in found), f'没抓到 40%：{unsup}'


def test_self_check_does_not_fire_on_the_honest_report(env):
    claims, url_to_claims = _load_ledger(env)
    reg = _registry_map(HONEST, url_to_claims)
    checked, unsup = check(HONEST, claims, reg)
    assert checked > 0, '正样本里也没有可查的句子，测试会空转'
    assert not unsup, f'正样本被误报了：{unsup}'


def test_self_check_ignores_lines_without_citations(env):
    """没挂引用的句子不归它管——那是校验门结论引用检查的职责。

    两条检查分工明确：门禁管"有没有引用"，自查管"引用的内容撑不撑得住"。
    """
    claims, url_to_claims = _load_ledger(env)
    no_cite = HONEST.replace('[1]', '')
    reg = _registry_map(no_cite, url_to_claims)
    checked, unsup = check(no_cite, claims, reg)
    assert checked == 0 and not unsup, (checked, unsup)


def test_self_check_says_nothing_when_there_is_nothing_to_check(env, capsys):
    """真实交付物常见形态（作者手写段零引用）不许报错，要如实说"无事可查"。"""
    from claim_support import main
    report = Path(env).parent / 'report.md'
    plain = '## 执行摘要\n\n本轮结论：框架 A 更适合本场景，召回率 85%。\n'
    report.write_text(plain, encoding='utf-8')
    assert main(['--report', str(report), '--ledger', env]) == 0
    assert '无事可查' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 3. 边界必须写在文档里
# ---------------------------------------------------------------------------

def test_skill_md_states_the_faithfulness_boundary():
    """防的是"文档只说可溯源、不说它不保证什么"。

    一句"每条结论挂 [N] 能回源"很容易被读成"逐句可信"，而校验门给不了这个保证。
    """
    md = (SCRIPTS.parent / 'SKILL.md').read_text(encoding='utf-8')
    assert 'claim_support.py' in md, '自查工具没进 SKILL.md'
    assert '引用忠实' in md or '语义' in md, \
        'SKILL.md 没说明"校验门不保证语义忠实"这件事'


def test_changelog_records_the_experiment():
    ch = (SCRIPTS.parents[2] / 'CHANGELOG.md').read_text(encoding='utf-8')
    assert 'faithfulness' in ch or '引用忠实' in ch, \
        '这次实验的结论没进 CHANGELOG——下一个人会重复做一遍'
