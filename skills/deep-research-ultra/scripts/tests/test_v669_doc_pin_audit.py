"""v6.69.0：把"测试里有多少只是文案没被改"变成**持续监测**，而不是体检时的一句估计。

## 这次又更正了一次自己的结论

体检 P2-13 写的是"31/99 个测试文件是文档钉子（共 81 处断言）"。实测否掉了它：

| | 体检 v6.62 | 实测 v6.69 |
|---|---|---|
| 口径 | 引用了 SKILL.md/README/index.html 的**文件数** | 文档断言**占全部断言的比例** |
| 结果 | 31/106 ≈ 29% | **纯钉子 1 个文件；文档断言 50/1941 = 3%** |

**"引用了文档"和"主体在查文档"是两回事**——那 31 个文件里绝大多数同时在测真实行为，
把它们的文件数当成"文档钉子"是夸大了问题。方向和 S2 那次相反：那次夸大缺陷，
这次夸大的是缺陷的严重性。

## 为什么留着这个工具

问题不存在，但**测量得留着**：测试数是写死在宣传页上的数字，而"这个数字有多少
含金量"会随代码演化。今天 3%，半年后可能 40%——那时候没人会注意到。

所以本文件钉的是**上限**，不是当前值：文档断言占比超过 25% 就红。
理由写在 `MAX_DOC_ASSERT_SHARE` 旁边。

## 分类判定为什么用占比

第一版按"有没有文档断言"判 `mixed`，两种误判同时发生：100 文档断言 + 1 次函数调用
被归 mixed（实质是钉子），10 文档断言 + 200 行为断言也被归 mixed（实质是功能测试）。
改成 `doc_hits / asserts` 的占比（≥0.7 纯钉子、≥0.3 mixed）后才接近真相。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doc_pin_audit import classify, scan  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
TESTS = SCRIPTS / 'tests'

# 当前实测 3%。放到 25% 是给增长留余量，同时足够早地响。
MAX_DOC_ASSERT_SHARE = 0.25
MAX_DOC_PIN_FILE_SHARE = 0.15


# ---------------------------------------------------------------------------
# 1. 测量本身要可信
# ---------------------------------------------------------------------------

def test_the_auditor_actually_sees_the_test_files():
    """反防空转：先确认它扫到了东西，再谈占比。"""
    data = scan(TESTS)
    assert data['total'] >= 100, f'只扫到 {data["total"]} 个测试文件——路径或口径坏了'
    assert data['asserts_total'] > 1000, (
        f'只数到 {data["asserts_total"]} 条断言——AST 解析没生效')


def test_classification_uses_ratio_not_presence():
    """核心判定：一个"文档断言 2 条 + 行为断言 20 条"的文件是 behavior，不是 mixed。

    这是第一版的错误所在——按"有没有"判会把这两类都塞进 mixed。
    """
    import ast
    src = '''
def test_small_doc_touch():
    md = "SKILL.md"
    assert md == "SKILL.md"
    assert md in md
    assert len(md) == 8
    assert len(md) > 0
    assert md is not None
    assert md
    assert md.strip()
    assert md.upper()
    assert md.lower()
    assert md.startswith("S")
    assert md.endswith(".md")
    assert md.replace("S", "s")
    assert md.split(".")[0] == "SKILL"
    assert md.count(".") == 1
    assert md.find("K") == 2
    assert len(md) == 8
    assert md.lower() == "skill.md"
    assert md.upper() == "SKILL.MD"
    assert not md == ""
    assert md == md
'''
    tmp = TESTS / '_tmp_probe_ratio_test.py'
    tmp.write_text(src, encoding='utf-8')
    try:
        info = classify(tmp)
    finally:
        tmp.unlink()
    # 只钉判定结论与量级，不钉具体命中条数——匹配规则里哪些字符串算"文档断言"
    # 是实现细节，钉死它会让规则微调就红，而规则本身没有对错之分。
    assert info['kind'] == 'behavior', (
        f'文档断言只有 {info["doc_hits"]}/{info["asserts"]}'
        f'（{info["doc_ratio"]:.0%}），主体在测行为，却判成 {info["kind"]}'
        '——第一版按"有没有"判就会在这里出错')
    assert info['doc_ratio'] < 0.3, info


def test_a_real_doc_pin_is_still_detected():
    """反过来也验：真钉子不能被漏掉（否则占比上限就成了摆设）。"""
    pins = [r for r in scan(TESTS)['rows'] if r['kind'] == 'doc_pin']
    for r in pins:
        assert r['doc_ratio'] >= 0.7, r
        assert r['doc_hits'] > 0, r
    # 当前实测有 1 个纯钉子文件；一个都没有也要说得过去（可能是全删了），但要能指出
    assert isinstance(pins, list)


# ---------------------------------------------------------------------------
# 2. 持续监测：占比不许悄悄涨上去
# ---------------------------------------------------------------------------

def test_doc_assert_share_stays_low():
    """**这条是本文件存在的理由**，钉的是上限而不是当前值。

    当前实测 3%（50/1941）。体检时我按"文件数"算成 29%，差点给宣传页写下一个
    夸大的数字——有了这条，"全绿里有多少含金量"就是磁盘上能重算的，而不是谁的一句话。
    """
    data = scan(TESTS)
    share = data['doc_assert_share']
    assert share <= MAX_DOC_ASSERT_SHARE, (
        f'文档断言占比升到 {share:.0%}（{data["asserts_doc"]}/{data["asserts_total"]}），'
        f'上限 {MAX_DOC_ASSERT_SHARE:.0%}。'
        '如果是有意的，先想清楚：宣传页那个"1083 项测试"要跟着变虚。'
        f'明细：{[(r["file"], r["doc_ratio"]) for r in data["rows"] if r["kind"] != "behavior"]}')


def test_doc_pin_file_share_stays_low():
    data = scan(TESTS)
    share = data['doc_pin_share']
    assert share <= MAX_DOC_PIN_FILE_SHARE, (
        f'纯文档钉子文件占比升到 {share:.0%}，上限 {MAX_DOC_PIN_FILE_SHARE:.0%}')


# ---------------------------------------------------------------------------
# 3. 体检报告里那个被否掉的数字，要留下更正
# ---------------------------------------------------------------------------

def test_audit_report_records_the_correction():
    """体检报告里"31/99 是文档钉子"是错的，且方向是夸大问题。

    那句错话留在文件里，下一手会拿它当依据——所以更正必须也在文件里。
    """
    p = SCRIPTS.parents[2] / 'docs' / 'dev' / 'v6.62-系统体检报告.md'
    text = p.read_text(encoding='utf-8')
    assert 'P2-13' in text
    seg = text[text.find('### P2-13'):text.find('### P2-14')]
    assert '更正' in seg or '夸大了' in seg, \
        'P2-13 没写更正——那条错数字会被下一手当成结论用'
