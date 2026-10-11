"""v6.73：定性高危形态（citation faithfulness 的选定方案 C）。

## 为什么做这个

决策材料（`docs/dev/v6.73-引用忠实度决策材料.md`）实测确认：校验门对 citation
faithfulness **零判别力**——账本说 A、报告说 B 的三种场景，issues 一字不差，
拒的都是「单源」。`claim_support.py` 覆盖了数字那一半，剩下的是定性断言。

方案 C 的依据是实测：纯规则能覆盖「极性反转」与「范围扩大」两类，7 用例
该抓 3/3、不该抓 4/4。**不接 NLI/LLM，不推翻「质量判断保持纯规则」。**

## 实现过程中改掉的两个自己的错

1. **词表把「场景下」当限定词** → 闸 3（"报告自己又打了折扣"）把真正的范围扩大
   自己消掉了，实测漏报。词表拆成 RESTRICTIVE（真限定）与 CONTEXT（上下文）：
   「所有**场景下**」里的"场景下"是"所有"的补语，不是限定。
2. **`if not checked` 把定性告警整个吞了** —— `checked` 只数数字，而"所有场景都
   优于基线"这类断言恰恰**没有数字**。新能力最常单独出现的地方，告警却发不出来。

## 本组测试的取舍

**误报比漏报贵**：这是提示不是门，报错了 Lead 会先怀疑工具而不是先怀疑报告。
所以放过类的用例（7 条）和抓取类的用例（3 条）一样多，且每条都写了为什么该放过。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
S = Path(__file__).resolve().parents[1]
SUPPORT = S / 'claim_support.py'
sys.path.insert(0, str(S))

import claim_support as cs  # noqa: E402

CLAIMS = [
    ('c1', '框架 A 的召回率高于框架 B', 'p1'),
    ('c2', '该方法在低延迟场景下优于基线', 'p2'),
    ('c3', '开源框架 A 效果最好', 'p3'),
    ('c4', '该方法可行且有效', 'p4'),
    ('c5', 'A 的延迟高于 B，且成本低于 C', 'p5'),
]
SRC = {cid: f'https://example.org/{slug}' for cid, _, slug in CLAIMS}
TABLE = '## 来源\n\n' + '\n'.join(
    f'[{i}] {SRC[c]}' for i, c in enumerate(['c1', 'c2', 'c3', 'c4', 'c5'], 1))


def _md(bluf, summary, concl):
    return (f'# T\n\n## 一页拍板\n\n{bluf}\n\n## 执行摘要\n\n{summary}\n\n'
            f'## 调研方法\n\n单次检索 [1]。\n\n## 结论与建议\n\n{concl}\n\n{TABLE}\n')


def _build(tmp: Path):
    L = tmp / 'ledger'
    # 同一次测试里会连着跑 5 个用例，都用同一个账本目录——重复建目录会 FileExistsError
    L.mkdir(exist_ok=True)
    for cid, text, slug in CLAIMS:
        for args in (
                ('add-claim', '--text', text, '--id', cid, '--topic', '效果'),
                ('add-source', '--claim-id', cid, '--url', SRC[cid],
                 '--title', slug, '--tier', '1', '--craap', '80'),
                ('set-status', '--claim-id', cid, '--status', 'verified', '--note', '核对')):
            r = subprocess.run([sys.executable, str(S / 'ledger.py'), args[0],
                                '--ledger', str(L), *args[1:]],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace')
            assert r.returncode == 0, f'建账本失败：{(r.stdout + r.stderr)[:200]}'
    return L


def _run(tmp: Path, text: str, tag: str):
    L = _build(tmp)
    p = tmp / f'{tag}.md'
    p.write_text(text, encoding='utf-8')
    r = subprocess.run([sys.executable, str(SUPPORT), '--report', str(p),
                        '--ledger', str(L)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------------------
# 该抓的：纯函数层（快、定位准）
# ---------------------------------------------------------------------------

def test_polarity_flip_is_detected():
    risks = cs.qualitative_risks('框架 A 的召回率低于框架 B [1]。',
                                  '框架 A 的召回率高于框架 B')
    assert any(r['kind'] == 'polarity_flip' for r in risks), risks


def test_extreme_word_flip_is_detected():
    risks = cs.qualitative_risks('开源框架 A 效果最差 [3]。', '开源框架 A 效果最好')
    assert any(r['kind'] == 'polarity_flip' for r in risks), risks


def test_scope_widening_is_detected():
    risks = cs.qualitative_risks('该方法在所有场景下都优于基线 [2]。',
                                  '该方法在低延迟场景下优于基线')
    assert any(r['kind'] == 'scope_widened' for r in risks), risks


# ---------------------------------------------------------------------------
# 不该抓的：误报比漏报贵，这一组和上面一样重要
# ---------------------------------------------------------------------------

def test_identical_text_is_silent():
    assert cs.qualitative_risks('框架 A 的召回率高于框架 B [1]。',
                                 '框架 A 的召回率高于框架 B') == []


def test_different_metric_is_not_a_flip():
    """「优于基线」→「部署成本高于基线」换了维度，不是极性反转。

    靠的是词组归属：优于 与 高于 不同组，所以对不上。
    """
    assert cs.qualitative_risks('该方法优于基线 [2]。', '该方法优于基线') == []


def test_contrast_in_one_sentence_is_silent():
    """「A 高于 B，而 B 的延迟高于 A」是同一组两向都在句里 → 对比讨论，放过。"""
    assert cs.qualitative_risks('A 的召回率高于 B，而 B 的延迟高于 A [1]。',
                                 'A 的召回率高于 B') == []


def test_claim_itself_is_two_directional_is_silent():
    """claim「延迟高于 B 且成本低于 C」本身两向 → 报告说其中一边对不上号，放过。"""
    assert cs.qualitative_risks('A 的延迟低于 B [5]。',
                                 'A 的延迟高于 B，且成本低于 C') == []


def test_sentence_self_qualifies_is_silent():
    """「在所有场景中，该方法部分优于基线」自己打了折扣 → 不是全称断言。"""
    assert cs.qualitative_risks('在所有场景中，该方法部分优于基线 [2]。',
                                 '该方法在低延迟场景下优于基线') == []


def test_substring_trap_is_silent():
    """「延迟最低」里"最低"不是极性反转——是"延迟"这个指标的正常说法。

    这条钉的是词表刻意不收「最高/最低/最多/最少」。子串匹配下它们会撞上
    「最低延迟」「最高收益」；宁可漏也不误报。
    """
    assert cs.qualitative_risks('该方案的延迟最低 [2]。', '该方案延迟最低') == []


def test_restrictive_and_context_words_do_not_overlap():
    """限定词与上下文词必须分开——混在一起会让闸 3 把真正的范围扩大消掉。

    这是 v6.73 实现时踩的坑：第一版把「场景下」放进限定词，于是
    「在所有场景下都优于基线」被当成"自己又打了折扣"而放过，实测漏报。
    """
    assert not (set(cs.RESTRICTIVE) & set(cs.CONTEXT)), (
        f'限定词与上下文词有交集：{set(cs.RESTRICTIVE) & set(cs.CONTEXT)}')


def test_context_words_are_not_treated_as_restrictive():
    assert cs._has_qualifier('在所有场景下都优于基线') == [], \
        '「场景下」是"所有"的补语，不该被当成限定词'


def test_extreme_words_avoid_the_substring_traps():
    """词表里不该出现「最低/最高/最多/最少」这类会撞正常说法的词。"""
    banned = ('最高', '最低', '最多', '最少')
    for gi, (pos, neg) in enumerate(cs.POLAR_GROUPS):
        for w in tuple(pos) + tuple(neg):
            for b in banned:
                assert b not in w, (
                    f'第 {gi} 组的 {w!r} 含 {b!r}——子串匹配会撞上'
                    f'「{b}延迟」「{b}收益」这类正常说法')


# ---------------------------------------------------------------------------
# 端到端：告警不能被吞
# ---------------------------------------------------------------------------

def test_qualitative_only_alert_is_not_swallowed():
    """**这一条是第一版最严重的问题。**

    `if not checked` 会打印"无事可查"并返回 0，而 `checked` 只数数字。
    而"所有场景都优于基线"这类断言恰恰**没有数字**——新能力最常单独出现的
    地方，告警却发不出来，等于加了等于没加。
    """
    with tempfile.TemporaryDirectory() as td:
        code, out = _run(Path(td), _md('该方法在所有场景下都优于基线 [2]。',
                                       '所有场景优于基线 [2]。', '全面采用 [2]。'),
                         'onlyqual')
    assert code != 0, f'只有定性告警时却返回"无事可查"：{out[:220]}'
    assert '无可查' not in out, out[:220]
    assert '定性' in out, f'输出没区分数字与定性两类：{out[:220]}'


def test_end_to_end_catches_and_stays_silent():
    """端到端跑一遍：3 条该抓的报、2 条不该抓的静默。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        catches = [
            ('p_flip', _md('框架 A 的召回率低于框架 B [1]。', 'A 低于 B [1]。', '选 A [1]。')),
            ('p_extreme', _md('开源框架 A 效果最差 [3]。', 'A 最差 [3]。', '避开 A [3]。')),
            ('p_scope', _md('该方法在所有场景下都优于基线 [2]。', '所有场景优于 [2]。',
                            '全面采用 [2]。')),
        ]
        silents = [
            ('p_ok', _md('框架 A 的召回率高于框架 B [1]。', 'A 高于 B [1]。', '采用 A [1]。')),
            ('p_trap', _md('该方案的延迟最低 [2]。', '延迟最低 [2]。', '延迟最低 [2]。')),
        ]
        for tag, text in catches:
            code, out = _run(tmp, text, tag)
            assert code != 0, f'{tag} 该报没报：{out[:200]}'
        for tag, text in silents:
            code, out = _run(tmp, text, tag)
            assert code == 0, f'{tag} 误报了：{out[:240]}'


def test_it_is_still_not_a_gate():
    """定性检查只进这个自查工具，不许悄悄进校验门。

    忠实度误报压不到零，就不该让它拦住交付——这是 v6.67 起就定的定位。
    """
    gate = (S / 'validate_report.py').read_text(encoding='utf-8')
    assert 'qualitative_risks' not in gate, \
        '校验门引用了 qualitative_risks——它一旦成为门，误报就会拦住交付'
    assert 'claim_support' not in gate, \
        '校验门引用了 claim_support——自查工具不该变成门禁'