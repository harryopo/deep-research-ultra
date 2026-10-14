"""边界钉死 —— v6.88 变异测试量出来的未钉住边界，逐条补上。

## 这批测试为什么长这样

不是"想到就补"的，是**从测量倒推**的：
`probe_mutation.py --systematic` 跑出 32 个变异、14 个存活，
每一个存活都意味着「这里改了没被发现」。

钉的方式必须跟着**边界类型**走：

| 边界类型 | 钉法 |
|---|---|
| 分段函数的每一档 | 表驱动，把**边界值本身**当输入（`years_ago = 0/1/2/3/4/5/6`） |
| 门槛常量 | 钉门槛**两侧**（`75` 与 `74.99`） |
| 空输入守卫 | 钉退化输入（`''` / `None`） |
| 零值岔口 | 钉 `0` 与 `1` 两边 —— `0` 的含义写在 docstring 里 |

**只写一个"正常值"通过了的测试，等于没钉。**

## 期望值全部在干净状态下量过，且量过两次

第一版我照着源码写期望，三条全错：

| 我猜的 | 第一次实测 | 第二次实测（干净） | 错在哪 |
|---|---|---|---|
| 空正文准确性 → 30 | 40 | **30** | 第一次是在**被污染的**工作区上量的 |
| 空查询相关性 → 60 | 50 | **60** | 同上 |
| 正文含 `2024年` 能抠出年份 | 40 | **40** ✓ | 正则要求年月同时出现 |

中间那次污染来自 v6.89 那个事故：变异探针把 `if not content:` 改成了
`if content:` 留在工作区，我照着那份代码"实测"出了
「空正文 40 分比非空正文 30 分还高、整段启发式不可达」，
还准备当成一个真 bug 报出去 —— **那是污染数据的产物，干净状态下完全正常**
（空 30 / 普通 50 / 内容充分 100）。

**连"我量过了"都可能是假的。**

## 每条测试都要被验证过

写完不等于钉住了。`verify_boundary_pins.py` 把对应变异装到**副本**上，
**要求本文件红**。装上变异后还绿的测试等于没写。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import score as sc_mod                      # noqa: E402
from score import CraapScorer               # noqa: E402
import verify_quotes as vq                  # noqa: E402

YEAR = datetime.now().year


# ===========================================================================
# 一、_score_currency 的分段阶梯（L398/400/402/404/406，5 个边界）
# ===========================================================================
# 实测：years_ago -1→100 ｜ 0→100 ｜ 1→90 ｜ 2→75 ｜ 3→60 ｜ 4→45 ｜ 5→45 ｜ 6→25
# 而 `years_ago <= 0` 的变异（改成 `< 0`）在 1200 项测试里**一路存活**。

def test_currency_ladder_covers_every_branch_at_its_boundary():
    """逐档钉死，边界值一个不漏（实测值，非推算）。"""
    sc = CraapScorer()
    table = [(0, 100.0), (1, 90.0), (2, 75.0), (3, 60.0),
             (4, 45.0), (5, 45.0), (6, 25.0)]
    for years_ago, want in table:
        got = sc._score_currency(str(YEAR - years_ago), "")
        assert got == want, (
            f'{years_ago} 年前应是 {want}，实得 {got}。'
            f'这条阶梯在 1200 项测试里一路存活过 —— '
            f'当年的文献时效性判错是很显眼的错。')


def test_currency_boundary_zero_is_inclusive():
    """`years_ago <= 0` 里的 **0 必须归"当年"**。

    改成 `< 0` 时，0 会掉进后面那串 elif 拿到 90 分 ——
    当年和一年前同分，这类错最难察觉，因为分数仍"看起来合理"。
    """
    sc = CraapScorer()
    assert sc._score_currency(str(YEAR), "") == 100.0, \
        "当年（years_ago == 0）必须拿满分，不能掉进一年前那一档"
    assert sc._score_currency(str(YEAR - 1), "") == 90.0, \
        "一年前必须是 90 —— 与当年拉开 10 分，否则两者同分"


def test_currency_future_year_also_counts_as_current():
    """次年（years_ago 为负）也归"当年"—— 这正是那个 `<=` 的用意。"""
    sc = CraapScorer()
    assert sc._score_currency(str(YEAR + 1), "") == 100.0


def test_currency_falls_back_to_40_when_no_date_anywhere():
    sc = CraapScorer()
    assert sc._score_currency("", "") == 40.0, "既无日期又提不出年份 → 40"
    assert sc._score_currency("", "发布于某个说不清的时候") == 40.0
    assert sc._score_currency("not-a-date", "正文里也没有") == 40.0


def test_currency_extracts_year_from_content_only_with_year_and_month():
    """无 published_date 时会从正文抠日期 —— **但要求年月同时出现**。

    正则是 `(\\d{4})[-/年](\\d{1,2})[-/月]?(\\d{1,2})?`（实测）：
    `2024-01` 抠得出、光一个 `2024年` 抠不出（回 40）。

    两种写法都钉住 —— 后者尤其重要：否则有人"顺手"放宽正则，
    题目里随便提到的年份就会被当成发表日期。
    """
    sc = CraapScorer()
    assert sc._score_currency("", f"发表于 {YEAR - 2}-01 的研讨会") == 75.0, \
        "正文里带年月就该抠出年份"
    assert sc._score_currency("", f"发表于{YEAR - 2}年的一次研讨会") == 40.0, \
        "只有年没有月，抠不出完整日期 —— 老老实实回 40"


# ===========================================================================
# 二、_get_grade 的门槛（L691/693）
# ===========================================================================

def test_grade_thresholds_are_inclusive_at_their_boundary():
    """门槛是闭区间，且**两侧都要钉**。

    只钉 `total=90 → high`，把 `>= 75` 改成 `> 75` 照样全绿 ——
    90 既不小于也不大于 75。
    """
    assert CraapScorer._get_grade(75.0) == "high", \
        "恰好 75 必须算 high（闭区间）；改成 > 75 会掉成 medium"
    assert CraapScorer._get_grade(74.99) == "medium"
    assert CraapScorer._get_grade(50.0) == "medium", "恰好 50 必须是 medium"
    assert CraapScorer._get_grade(49.99) == "low"


# ===========================================================================
# 三、空输入守卫（L426 / L551）
# ===========================================================================

def test_empty_query_falls_back_to_baseline_60_not_zero():
    """查询为空时相关性回落到基线 60，**不是 0**。

    0 在下游表示"评出来不相关"，而"没有查询可评"是另一回事 ——
    这正是 v6.63 引入 `relevance_capped` 要区分的那类。
    """
    sc = CraapScorer()
    got = sc._score_relevance("", "RAG evaluation benchmark", "retrieval")
    assert got == 60.0, f'空查询的相关性应是基线 60（实测值），不是 0；实得 {got}'


def test_empty_content_falls_to_the_30_floor():
    """空正文必须走 30 分那条早退线，**不是照常打分**。

    把 `if not content:` 改成 `if content:`，空内容会**跳过**早退、
    掉进那套按长度/引用/数字打分的启发式 —— 于是"没有证据的条目"
    和"内容很充实但没引用的条目"拿到同一个分，而前者应该是底线。

    实测（干净状态）：空 30 ｜ 普通 50 ｜ 内容充分 100。
    ⚠️ 我一度以为这里有反向 bug（"空正文比非空正文高"）——
    那是 v6.89 事故期间在被污染的 `if content:` 上量出来的假象。
    """
    sc = CraapScorer()
    url = "https://e.com/a"
    empty = sc._score_accuracy("", url)
    plain = sc._score_accuracy("正常正文带引用 [1] 与数字 42 与来源", url)
    rich = sc._score_accuracy("x" * 600 + " 参考文献 references https://e.com 42% 2024 arxiv", url)

    assert empty == 30.0, f'空正文必须走 30 分那条早退线，实得 {empty}'
    assert plain == 50.0, f'普通正文实测 50（走启发式），实得 {plain}'
    assert rich == 100.0, f'内容充分且带引用/链接/百分比/年份实测 100，实得 {rich}'
    assert empty < plain < rich, (
        "三档必须是 30 < 50 < 100 的单调关系 —— "
        "反了就说明守卫写反了，那正是这个变异干的事")


# ===========================================================================
# 四、零值岔口：`min_score > 0`（L736）
# ===========================================================================

class _Result:
    """够评分链用的最小结果对象。

    `craap_score` 必须**先存在**，哪怕是 None：`score_batch` 靠
    `hasattr(result, 'craap_score')` 判断走属性赋值还是 dict 下标。
    不给这个属性，它就去 `result['craap_score'] = score`，
    对象类型直接 TypeError。
    """

    def __init__(self, title, content, url, date):
        self.title, self.content, self.url = title, content, url
        self.published_date, self.author, self.source = date, "A. Author", "J"
        self.snippet, self.summary = content[:200], content[:150]
        self.craap_score = None


def _rich_result():
    """内容充实、时效新、Tier 1 域名 —— 总分明显高于对照。"""
    return _Result("Retrieval Augmented Generation with Long Context",
                   "retrieval augmented generation " * 40 + " references 42% 2024",
                   "https://arxiv.org/abs/2402.00001", str(YEAR))


def _poor_result():
    """无日期无引用无链接 —— 明显更低分。"""
    return _Result("listicle", "short", "https://some-listicle.example/pop", "")


def test_min_score_zero_means_do_not_filter():
    """`min_score == 0` 的语义是**不过滤** —— docstring 明写「0=不过滤」。

    把 `> 0` 改成 `>= 0`，低分条目会被真的滤掉，而调用方本意是"全部返回"。

    ⚠️ `score_results` 是**模块级**函数，不是 `CraapScorer` 的方法
    （我第一版写成 `CraapScorer.score_results`，直接 AttributeError）。
    而且它会先跑 `score_batch`，**覆盖**结果对象上的 `craap_score` ——
    所以想控制分数得控制**输入**，伪造 `craap_score` 是没用的。
    """
    poor = _poor_result()
    kept = sc_mod.score_results([poor], query="retrieval", min_score=0)
    assert len(kept) == 1, (
        f'min_score=0 应原样返回，实得 {len(kept)} 条 —— '
        f'0 是「不过滤」的约定值（docstring 明写），别把它当阈值')


def test_min_score_actually_filters_when_positive():
    """给了正阈值就真要过滤 —— 否则 `min_score` 是个假开关。"""
    poor, rich = _poor_result(), _rich_result()
    kept = sc_mod.score_results([poor, rich], query="retrieval", min_score=50)
    assert len(kept) < 2, \
        f'min_score=50 却没有滤掉任何东西（实得 {len(kept)} 条）—— 假开关'
    assert kept, "min_score=50 不该把全部滤空，样本本身要有一高一低"


# ===========================================================================
# 五、引用抽取的去重（L68）与单字引号（L113 的 floor）
# ===========================================================================

def test_quoted_spans_deduplicates_identical_spans():
    """同一段引文出现多次只抽一次（实测 2→1）。

    把 `frag and frag not in out` 改成 `or` 后几乎每段都满足条件 →
    **重复片段被塞进去**，重复片段会变成重复的 MISS 报给用户。
    """
    text = ('原文『这是一段足够长的引文内容用于去重验证』，'
            '后面再说『这是一段足够长的引文内容用于去重验证』。')
    spans = list(vq.quoted_spans(text))
    assert len(spans) == 1, f'同一段出现两次只应抽一次，实得 {len(spans)}：{spans}'


def test_quoted_spans_keeps_distinct_spans():
    """去重不能误伤：两段不同的引文都要抽出来（实测 2 条）。"""
    text = '甲『第一段完全不同的引文内容在这里』与乙『第二段也不一样的引文内容在那』。'
    spans = list(vq.quoted_spans(text))
    assert len(spans) == 2, f'两段不同引文应抽成两条，实得 {len(spans)}：{spans}'


def test_quoted_spans_skips_single_character_quotes():
    """单字引号不抽 —— 抽了就会变成假 MISS 警报（实测 0）。"""
    for text in ("「字」", "「气」", "「文」"):
        assert list(vq.quoted_spans(text)) == [], \
            f'{text!r} 单字引号不应被当成逐字引用片段'
    assert len(list(vq.quoted_spans("「引用」"))) == 1, \
        "两个字以上仍要照常抽取，别为了躲单字把下限一起抬了"


# ===========================================================================
# 六、刻意不钉的
# ===========================================================================

def test_print_separator_mutant_survives_and_that_is_fine():
    """`research.py:144` 的 `"=" * 60` 变异也存活 —— **这是应该的**。

    它是 MCP 健康检查的打印分隔线，不是行为。改宽度没有任何功能后果，
    所以没有测试会红，也不该有。

    这条不是钉住它，而是**把"我们选择不钉"写下来**：
    机械存活清单里混着纯展示项，照单全钉会把清单变成仪式，
    还会让人误以为「存活 = 有问题」。
    """
    import json

    import pytest

    import probe_mutation as pm

    p = pm.S / ".research" / "mutation_systematic.json"
    if not p.exists():
        pytest.skip("还没跑过 probe_mutation.py --systematic")
    d = json.loads(p.read_text(encoding="utf-8"))
    surv = [r for r in d["results"]
            if r["verdict"] == "SURVIVED" and r["file"] == "research.py"
            and r["line"] == 144]
    assert surv, "research.py:144 应当在存活清单里（打印分隔线改宽度无人察觉）"