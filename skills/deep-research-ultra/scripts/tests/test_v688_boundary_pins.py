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

import io
import json
import sys
from datetime import datetime
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import score as sc_mod                      # noqa: E402
from score import CraapScorer               # noqa: E402
import verify_quotes as vq                  # noqa: E402
import ledger as lg                          # noqa: E402

from research import filter_by_relevance as rs_fbr   # noqa: E402
from research import cmd_search as rs_cmd_search          # noqa: E402

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

# ===========================================================================
# 七、_score_purpose 的信号分档（L604 / L615 / L625）
# ===========================================================================
# 实测（干净状态，注意签名是 (url, content) —— 我第一版传反了，
# 得到"全是 70.0"的假象，差点据此下一个错结论）：
#
#   空白 70 ｜ 商业内容 40 ｜ 商业域名 50 ｜ 教育内容 85
#   教育域名 80 ｜ 偏见内容 50 ｜ 商业+偏见+域名 10
#
# 三个 `count > 0` 的变异（改成 `>= 0`）**是等价变异**：
# count 为 0 时 `min(30, 0*10) = 0`，`score -= 0` 等于没动。
# 所以**不该**有测试因为它们而红 —— 但整个函数的分档逻辑必须有人钉住，
# 下面这组用例就是干这个的。

def test_purpose_scoring_distinguishes_all_signal_kinds():
    """`_score_purpose` 每一类信号都要能真的改变分数。

    七个输入覆盖：空、商业内容、商业域名、教育内容、教育域名、偏见、
    以及三者叠加。叠加那个是最狠的（70−30−20−10 = 10），
    任何一处符号写反都会立刻露出来。
    """
    sc = CraapScorer()
    table = [
        ("空白",           "https://e.com/a", "", 70.0),
        ("商业内容",       "https://e.com/a",
         "buy discount sponsored 购买 广告", 40.0),
        ("商业域名",       "https://amazon.com/p", "普通内容", 50.0),
        ("教育内容",       "https://e.com/a",
         "tutorial guide 教程 如何", 85.0),
        ("教育域名",       "https://x.edu/p", "普通内容", 80.0),
        ("偏见内容",       "https://e.com/a", "best ever 绝对 保证", 50.0),
        ("商业+偏见+域名", "https://amazon.com/p",
         "buy discount 绝对 100%", 10.0),
    ]
    for label, url, content, want in table:
        got = sc._score_purpose(url, content)
        assert got == want, (
            f'{label}（url={url!r} content={content!r}）应得 {want}，实得 {got}')


def test_purpose_score_stays_in_range_even_with_many_signals():
    """加减多次之后仍要夹在 0~100 —— 叠加惩罚可能算出负数。"""
    sc = CraapScorer()
    heavy = "buy discount sponsored 广告 购买 推广 赞助 best ever 绝对 保证 100%"
    v = sc._score_purpose("https://amazon.com/p", heavy)
    assert 0.0 <= v <= 100.0, f'叠加后越界了：{v}'


# ===========================================================================
# 八、_score_accuracy 的长度分档（L558/560/562/564）
# ===========================================================================
# 实测（内容全用 x —— 不含数字/链接/引用词，只让长度这一项起作用）：
#
#   len   0→30（早退线）｜50→40｜51→55｜200→55｜201→60
#   len 500→60｜501→65｜1000→65｜1001→70
#
# 四个 `> N` 的变异（把 1000 改成 1001 之类）只差在**恰好等于那个数**时。
# 只喂一个长文本的话，四档全都抓不到 —— 必须逐档喂边界值。

_LENGTH_TIERS = [
    (0, 30.0), (50, 40.0), (51, 55.0), (200, 55.0),
    (201, 60.0), (500, 60.0), (501, 65.0), (1000, 65.0), (1001, 70.0),
]


def test_accuracy_length_tiers_hit_every_boundary_value():
    """逐个长度边界喂一遍 —— `> N` 的错改只在恰好等于 N 时才显形。"""
    sc = CraapScorer()
    for n, want in _LENGTH_TIERS:
        got = sc._score_accuracy("x" * n, "https://e.com/a")
        assert got == want, (
            f'长度 {n} 应得 {want}，实得 {got}。'
            f'内容全用 x 是不含数字/链接/引用词，只让长度这一项起作用。')


def test_accuracy_tiers_are_monotonic_in_length():
    """分数必须随长度单调不减（到 1001 封顶为止）。"""
    sc = CraapScorer()
    vals = [sc._score_accuracy("x" * n, "https://e.com/a")
            for n, _ in _LENGTH_TIERS]
    for a, b, (na, _), (nb, _) in zip(vals, vals[1:], _LENGTH_TIERS,
                                        _LENGTH_TIERS[1:]):
        assert a <= b, f'长度 {na} 得 {a}，{nb} 却得 {b} —— 反而降了'


# ===========================================================================
# 十、len 簇：长度阈值的边界（来自 v6.88 边界实跑的存活清单）
# ===========================================================================
# 这一簇的共同形状：**`<` / `<=` / `>` / `>=` 在恰好等于阈值时行为不同**，
# 而"正常"长度的片段/URL/路径全都在阈值另一侧，于是所有测试都绿。
#
# 钉法统一为：**把输入做成恰好等于阈值的那个**，再各退一格作对照。


def test_quoted_fragments_min_len_is_inclusive_at_15():
    """`len(f) >= min_len`（默认 15）—— 15 字要进，14 字不进。

    改成 `> 15` 的话，所有"明显够长"的测试照样绿，只有 15 字这个
    临界长度的片段会被悄悄丢掉 —— 而引文抽不出来意味着
    "这条声明的原文引用没被验证"，是个静默的漏检。
    """
    at14 = vq.quoted_fragments("「" + "x" * 14 + "」")
    at15 = vq.quoted_fragments("「" + "x" * 15 + "」")
    at16 = vq.quoted_fragments("「" + "x" * 16 + "」")
    assert len(at14) == 0, f"14 字不该抽出（低于 min_len=15），实得 {len(at14)}"
    assert len(at15) == 1, f"15 字必须抽出（闭区间），实得 {len(at15)}"
    assert len(at16) == 1, "16 字照常抽出"


def test_ellipsis_segments_needs_six_chars_on_each_side():
    """`_ellipsis_segments` 里 `len(_fold(p)) >= 6` —— 5 字被丢、6 字保留。

    短于 6 字的片段对"省略号切分"没有意义（定位不到），
    所以这一行是硬门槛；改成 `> 6` 会让 6 字的短片段整段消失。
    """
    short = vq._ellipsis_segments("前段内容甲乙丙…" + "x" * 5, [])
    exact = vq._ellipsis_segments("前段内容甲乙丙…" + "x" * 6, [])
    longer = vq._ellipsis_segments("前段内容甲乙丙…" + "x" * 7, [])
    assert short is None, f"后段 5 字应被门槛挡掉（parts 不足 2），实得 {short}"
    assert exact is not None and len(exact) == 2, \
        f"后段 6 字必须切出 2 段，实得 {exact}"
    assert len(longer) == 2, "后段 7 字同样切出 2 段"


_STRIP_TABLE = [
    ("10.1234/abcd", "10.1234/abcd"),                    # 2 段，不动
    ("10.1234/full", "10.1234/full"),                    # 2 段，full 是 DOI 本体
    ("10.1234/abcd/full", "10.1234/abcd"),               # 3 段，剥掉
    ("10.1234/abcd/fulltext", "10.1234/abcd"),           # 3 段，剥掉
    ("10.1234/a/b/full", "10.1234/a/b"),                 # 多段，剥到 2 段以上为止
]


def test_strip_landing_views_never_eats_a_two_segment_doi():
    """`len(parts) > 2` —— 两段 DOI 是分界线。

    改成 `>= 2` 后 `10.1234/full` 会变成 `10.1234` —— DOI 直接残废，
    而同一个 DOI 再也匹配不到原文，整条溯源链静默断掉。
    """
    for doi, want in _STRIP_TABLE:
        got = lg._strip_landing_views(doi)
        assert got == want, f"{doi!r} 应归一化为 {want!r}，实得 {got!r}"


def test_strip_landing_views_strips_repeatedly():
    """落地页后缀可能叠着，必须一路剥到底。"""
    assert lg._strip_landing_views("10.1234/abcd/full/fulltext/") == "10.1234/abcd", \
        "连剥两个落地页后缀（实测行为，钉住它别被改成只剥一个）"


def test_github_key_does_not_treat_a_dangling_blob_as_a_ref():
    """`len(seg) > 1` —— `.../repo/blob` 没有 ref，不能按 ref 解析。

    ⚠️ **我第一版的这条测试是空转的**：喂的是 `github.com:owner/repo/blob`，
    而 `_github_key` 的正则要求 `https?://` 开头 —— 匹配不上就直接走
    兜底 `return f'github:{u.lower()}'`，断言恒真、装上变异照样全绿。
    是验证脚本抓出来的。改用真 https URL。

    实测：`/blob`（rest 段数为 1）→ path 保留 'blob'；
    `/blob/main`（段数为 2）→ main 被当 ref 吃掉，path 变空。
    改成 `>= 1` 后前者会取 `seg[1]` —— **IndexError**。
    """
    dangling = lg._github_key("https://github.com/owner/repo/blob")
    assert dangling == "github.com:owner/repo@HEAD:blob", (
        f"`/repo/blob` 没有 ref，path 应原样保留 blob（实测），实得 {dangling!r}")

    withref = lg._github_key("https://github.com/owner/repo/blob/main")
    assert withref == "github.com:owner/repo@HEAD:", (
        f"`/repo/blob/main` 的 main 是 ref，应被吃掉、path 留空，实得 {withref!r}")

    filed = lg._github_key("https://github.com/owner/repo/blob/main/f.py")
    assert filed == "github.com:owner/repo@HEAD:f.py", (
        f"三段时 main 是 ref、f.py 是 path，实得 {filed!r}")

    tree = lg._github_key("https://github.com/owner/repo/tree/main/docs")
    assert tree == "github.com:owner/repo@HEAD:docs", (
        f"tree 分支同样要求 len(seg) > 1，实得 {tree!r}")


def test_github_key_keeps_repo_root_distinct_from_readme():
    """兜底分支与主分支的对照：仓库根页与 README 是同一份内容。"""
    root = lg._github_key("https://github.com/owner/repo")
    readme = lg._github_key("https://github.com/owner/repo/blob/main/README.md")
    assert root == "github.com:owner/repo@HEAD:", f"仓库根页实得 {root!r}"
    assert readme == "github.com:owner/repo@HEAD:", (
        f"默认分支的 README 应折叠成仓库根（实测同值），实得 {readme!r}")


def test_se_key_returns_empty_for_bare_stackexchange_domain():
    """`len(host) > len('stackexchange.com')` 的等价性见证（见下方注释）。

    扫过 27 个输入，`>=` 改法零变化 —— 唯一能触发 `>=` 的 host
    就是 'stackexchange.com' 本身，而它 `[:-16]` 仍是 ''，与 else 同值。
    这条测试钉的是**行为**（裸域名无子站 → 返回空），
    那个 `>` 本身没有任何测试能钉，也不该有。
    """
    for u in ("https://stackoverflow.com/q/1",
              "https://stackexchange.com/q/1",
              "https://ai.stackexchange.com/q/1"):
        assert lg._se_key(u) == "", f"{u} 应解析不出站点键，实得 {lg._se_key(u)!r}"


# --- check_quotes 内部的三条：需要账本 + 语料才观察得到 ---

_CORPUS_TEXT = ("The retrieval augmented generation pipeline was evaluated on "
                "three benchmarks. ") * 30


def _cq_corpus(tmp_path, text=_CORPUS_TEXT):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    io.open(raw / "c.txt", "w", encoding="utf-8").write(text)
    return raw


def _cq_ledger(tmp_path, claims):
    led = tmp_path / "led"
    led.mkdir(exist_ok=True)
    with io.open(led / "ledger.jsonl", "w", encoding="utf-8") as f:
        for cid, text in claims:
            f.write(json.dumps({"type": "claim", "id": cid, "text": text,
                                "topic": "t", "status": "pending"},
                               ensure_ascii=False) + "\n")
    return led


def test_check_quotes_min_len_boundary_goes_to_unchecked_not_checked(tmp_path):
    """`len(frag) < min_len` —— 15 字必须**进对账**，14 字才进 unchecked。

    改成 `<=` 后 15 字的引文会被跳过对账：既不进 `checked` 也不报 MISS。
    那是静默漏检 —— 一条恰好 15 字的逐字引用从此不再被验证。
    实测（min_len=15）：unchecked 只有 14 字那条，checked = 2。
    """
    raw = _cq_corpus(tmp_path)
    led = _cq_ledger(tmp_path, [
        ("c1", "『" + "x" * 14 + "』太短"),
        ("c2", "『" + "x" * 15 + "』刚好"),
        ("c3", "『" + "x" * 16 + "』够长"),
    ])
    res = vq.check_quotes(str(led), str(raw), min_len=15)
    assert len(res["unchecked"]) == 1, (
        f"只有 14 字那条该进 unchecked，实得 {len(res['unchecked'])} 条")
    assert len(res["unchecked"][0]) == 14, (
        f"进 unchecked 的应是 14 字那条，实得长度 {len(res['unchecked'][0])}")
    assert res["checked"] == 2, (
        f"15 与 16 字两条都要参与对账（checked=2），实得 {res['checked']}")


def test_check_quotes_dedupes_unchecked_spans(tmp_path):
    """`frag not in unchecked` —— 同一段短引文重复出现只记一次。"""
    raw = _cq_corpus(tmp_path)
    short = "x" * 14
    led = _cq_ledger(tmp_path, [("c1", "『" + short + "』第一次『" + short + "』第二次")])
    res = vq.check_quotes(str(led), str(raw), min_len=15)
    assert len(res["unchecked"]) == 1, (
        f"重复的 14 字片段只应记一次，实得 {len(res['unchecked'])} 条")


def test_check_quotes_max_len_boundary_is_exclusive(tmp_path):
    """`len(frag) > max_len` —— 恰好等于上限**不算**超长。

    实测（max_len=30）：30 字那条不进 overlong，31 字那条进。
    改成 `>=` 后整篇超过建议上限的告警会提前一格，且对账的语义变了
    （L2 只告警不阻断，所以这格的差别不影响阻断，但会让告警数虚高）。
    """
    raw = _cq_corpus(tmp_path)
    led = _cq_ledger(tmp_path, [
        ("c1", "『" + "y" * 30 + "』正好 30"),
        ("c2", "『" + "y" * 31 + "』超了"),
    ])
    res = vq.check_quotes(str(led), str(raw), max_len=30)
    assert len(res["overlong"]) == 1, (
        f"只有 31 字那条算超长，实得 {len(res['overlong'])} 条")
    assert len(res["overlong"][0]) == 31, (
        f"超长的应是 31 字那条，实得 {len(res['overlong'][0])}")


def test_check_quotes_dedupes_overlong_spans(tmp_path):
    """`frag not in overlong` —— 同一段超长引文重复出现只记一次。"""
    raw = _cq_corpus(tmp_path)
    long_ = "z" * 40
    led = _cq_ledger(tmp_path, [("c1", "『" + long_ + "』甲『" + long_ + "』乙")])
    res = vq.check_quotes(str(led), str(raw), max_len=30)
    assert len(res["overlong"]) == 1, (
        f"重复的 40 字片段只应记一次，实得 {len(res['overlong'])} 条")


# ===========================================================================
# 十一、_relevance_is_reliable 的两道门（L426 / L440）
# ===========================================================================
# ⚠️ **L426 我判错过一次。** 我先用纯英文查询扫了一遍，看不出任何变化，
# 就写进 EQUIVALENT 断言「空查询走原逻辑也返回 True，那个早退是冗余的」。
# 错的：纯英文查询在 **L428** 就 return 了 —— `if not re.search(CJK, query): return True`
# 压根到不了 L426 的效果。那组输入测的是 L428，不是 L426。
#
# 用中文查询重扫，结论反过来：
#   hay=命中 1 个 2-gram -> 原 False，变异后 True
#   hay=零命中        -> 原 False，变异后 True
#
# **「扫了一批输入没变化」不等于等价，除非那批输入真的能走到被测的行。**
# 这是本项目「先解释后验证」的第三个变体：前两次是量错和期望错，这次是量到了别的分支。

# 19 个互不相同的汉字 -> 18 个互不相同的 2-gram；再配 2 个英文词凑成 20 个词。
# ⚠️ 不能用同一个字重复 —— 那 18 个 2-gram 会全部退化成同一个词，命中数虚高。
_CJK = [chr(c) for c in (0x4E00, 0x4E8C, 0x4E09, 0x56DB, 0x4E94, 0x516D,
                        0x4E03, 0x516B, 0x4E5D, 0x5341, 0x7532, 0x4E59,
                        0x4E19, 0x4E01, 0x620A, 0x5DF1, 0x5E9A, 0x8F9B, 0x58EC)]
_BIGRAM = [_CJK[i] + _CJK[i + 1] for i in range(18)]
_Q20 = "aa bb " + "".join(_CJK)          # 词数 = 2 英文 + 18 个 2-gram = 20
_NOWHERE = chr(0x65E0) + chr(0x5173) + chr(0x5185) + chr(0x5BB9)


def test_reliability_coverage_floor_is_inclusive_at_015():
    """`coverage >= RELEVANCE_COVERAGE_FLOOR(0.15)` —— 恰好 0.15 算可信。

    实测（20 词）：命中 3 → cov 0.15 → True；命中 2 → 0.10 → False；
    命中 4 → 0.20 → True。

    改成 `> 0.15` 后，恰好卡在地板上的那批结果会被判成"不可信"，
    而它们其实是可用的 —— 相关性分被无理由地打上失效标记。
    """
    sc = CraapScorer()
    assert sc._relevance_is_reliable(_Q20, "aa " + _BIGRAM[0] + " " + _BIGRAM[2], "") is True, \
        "cov 恰好 0.15（3/20）必须算可信（闭区间），实得 False"
    assert sc._relevance_is_reliable(_Q20, "aa " + _BIGRAM[0], "") is False, \
        "cov 0.10（2/20）低于地板，应判不可信"
    assert sc._relevance_is_reliable(_Q20, "aa bb " + _BIGRAM[0] + " " + _BIGRAM[2], "") is True, \
        "cov 0.20（4/20）高于地板，应判可信"


def test_reliability_distinguishes_chinese_low_coverage_from_english():
    """**中文查询**且覆盖率低 -> 不可信；纯英文查询不在判据范围内。

    这条是 L426/L428/L440 三道门的判别力见证，也是我第一次量错的地方：
    只喂英文查询的话，L428 直接 return，三道门里两道都测不到。
    """
    sc = CraapScorer()
    q_cn = "".join(_CJK[:8])                       # 8 字 -> 7 个 2-gram
    assert sc._relevance_is_reliable(q_cn, q_cn, "") is True, "全覆盖应可信"
    assert sc._relevance_is_reliable(q_cn, _NOWHERE, "") is False, \
        "中文查询零命中应判不可信（判定器没听懂语料，不是判定为不相关）"
    assert sc._relevance_is_reliable(q_cn, _BIGRAM[0] + _BIGRAM[1], "") is True, \
        "命中 2/7（cov 0.29）高于地板，应可信"
    assert sc._relevance_is_reliable("", "", "") is True, \
        "空查询没有相关性可言，不算失效（L426 的早退）"
    assert sc._relevance_is_reliable("plain english query", "unrelated", "") is True, \
        "纯英文查询不在判据范围内（同语种词法匹配有效，L428）"



# ===========================================================================
# 十二、filter_by_relevance 的四道门（research.py L399/406/416/417）
# ===========================================================================
# 这个函数的门槛是嵌套的：**外层不够数就整体放回内层的过滤结果**。
# 所以"某条结果相关度恰好等于 min_relevance"这类边界，
# 只有在"够数"那个分支上才观察得到 —— 只测单个分支会全绿。
#
# 实测（min_relevance=0.5, [0.9, 0.5, 0.3], target_count=2）：
#   保留 2 条 [0.90, 0.50]  丢弃 1  低相关 1
#   min_relevance 改 0.51 -> 保留 3 条（0.50 掉出 strong，且不够数，全放回）

_ANCHOR_TITLE = ("Vector Database Retrieval Augmented Generation Benchmark Study")


class _Rel:
    """`filter_by_relevance` 只读 `craap_score['relevance']` 与 `title`。"""

    def __init__(self, rel, title=_ANCHOR_TITLE):
        self.title = title
        self.craap_score = {"relevance": rel}

    def __repr__(self):
        return "%.2f" % self.craap_score["relevance"]


def _rels(*vals):
    return [_Rel(v) for v in vals]


def test_filter_keeps_result_exactly_at_min_relevance():
    """`_relevance(r) >= min_relevance` —— **恰好等于门槛的要留下**（闭区间）。

    实测：min_relevance=0.5 时 0.50 那条进 strong；改 0.51 它就掉出去。
    改成 `>` 会把"刚好压线"的合格结果判成低相关 —— 而这恰恰是最该保留的一档。
    """
    rs = _rels(0.9, 0.5, 0.3)
    keep, dropped, low = rs_fbr(rs, 0.5, 2)
    assert len(keep) == 2, f"0.50 恰好等于 min_relevance，应保留（实得 {len(keep)} 条）"
    assert repr(keep[1]) == "0.50", f"第二条应是 0.50 那条，实得 {keep[1]!r}"
    assert (dropped, low) == (1, 1), f"丢弃/低相关应为 (1,1)，实得 ({dropped},{low})"

    # 门槛抬高一分，压线那条就掉出去，且因为不够数而整体放回
    keep2, dropped2, low2 = rs_fbr(rs, 0.51, 2)
    assert len(keep2) == 3, f"min_relevance=0.51 时 0.50 掉出 strong，应整体放回 3 条"
    assert dropped2 == 0 and low2 == 2, (
        f"放回时 dropped 应为 0（没真丢）、low 应为 2，实得 ({dropped2},{low2})")


def test_filter_threshold_at_exactly_needed_still_filters():
    """`len(strong) >= needed` —— **恰好够数就要过滤**，不够才放回。

    实测（strong 本来 3 条）：target_count=3 -> 保留 3 条；
    target_count=4 -> 保留 4 条（3 < 4，不够数，全放回）。

    改成 `>` 后，target_count=3 这个"刚好够"的常见情形会退化成放回 ——
    过滤静默失效，而返回的元组里 dropped=0，看不出任何异常。
    """
    rs = _rels(0.9, 0.8, 0.7, 0.3)
    keep3, dropped3, _ = rs_fbr(rs, 0.5, 3)
    assert len(keep3) == 3, f"target_count=3 恰好够数，应过滤成 3 条，实得 {len(keep3)}"
    assert dropped3 == 1, f"应丢掉那条 0.30，实得 dropped={dropped3}"

    keep4, dropped4, _ = rs_fbr(rs, 0.5, 4)
    assert len(keep4) == 4, f"target_count=4 时 strong 只有 3 条，不够数应放回 4 条"
    assert dropped4 == 0, f"放回时 dropped 应为 0，实得 {dropped4}"


def test_filter_needed_saturates_at_five():
    """`needed = max(1, min(target_count, 5))` 的两端实测（推导会算错）。"""
    for tc, want in ((0, 1), (1, 1), (2, 2), (3, 3), (5, 5), (6, 5), (99, 5)):
        got = max(1, min(tc, 5))
        assert got == want, f"target_count={tc} 时 needed 应为 {want}，实得 {got}"
    # 饱和行为要在真函数上可见：target_count 从 5 加到 99 结果条数不再变
    rs = _rels(0.9, 0.8, 0.7, 0.6, 0.5, 0.4)
    assert len(rs_fbr(rs, 0.5, 5)[0]) == len(rs_fbr(rs, 0.5, 99)[0]), (
        "needed 到 5 就饱和，target_count 从 5 加到 99 结果不应再变")


def test_filter_short_circuits_when_min_relevance_is_not_positive():
    """`min_relevance <= 0` 的短路 —— 关键在 **low 计数为 0**，不只是条数。

    实测：min_relevance=0 时返回全量且 low=0；min_relevance=0.001 时
    全量里三条都低相关（low=3）且同样不过滤。

    只断言"条数不变"抓不住它 —— 两条路径返回的条数完全一样，
    区别只在 low 那个数上。而 low 是要报给用户的。
    """
    rs = _rels(0.0, 0.0, 0.0)
    _, _, low0 = rs_fbr(rs, 0, 3)
    _, _, low_neg = rs_fbr(rs, -1, 3)
    _, _, low_pos = rs_fbr(rs, 0.001, 3)
    assert low0 == 0, f"min_relevance=0 走短路，low 应为 0，实得 {low0}"
    assert low_neg == 0, f"min_relevance=-1 走短路，low 应为 0，实得 {low_neg}"
    assert low_pos == 3, f"min_relevance=0.001 不短路，三条都低相关，实得 {low_pos}"



# ===========================================================================
# 十三、_write_ledger 的 dropped 计数（research.py L831）
# ===========================================================================
# `elif not auto_claim:` -> `elif auto_claim:` 会把 dropped 的语义整个反过来：
# 显式要了 --auto-claim 的运行反而开始统计"丢弃"，而它本来一条都不该丢。
#
# `add_evidence` 返回 None 有两个成因，**都是这一条的可观察点**：
#   ① URL 不可溯源（ledger.py L747-748）
#   ② URL 已在 evidence.jsonl 里（L750-751）
# 只测一个成因的话，另一个成因下变异仍然全绿。

class _LRes:
    def __init__(self, title, url):
        self.title, self.url = title, url
        self.content = ""
        self.craap_score = {"total": 70.0, "relevance": 60.0, "tier": 2}
        self.engine = "e"
        self.query = "q"


def _wl(tmp_path, results, **kw):
    """跑一次 _write_ledger，返回 (账本, written 三个计数)。"""
    from ledger import ResearchLedger
    import research

    led = ResearchLedger(str(tmp_path / "led")).init()
    w = research._write_ledger(led, results, None, "topic", **kw)
    return led, w


def test_dropped_is_only_counted_when_not_auto_claiming(tmp_path):
    """实测：不可溯源 URL 在 auto_claim 两侧的 written 完全不同。

      auto_claim=False -> {'claims': 0, 'evidence': 0, 'dropped': 1}
      auto_claim=True  -> {'claims': 1, 'evidence': 0, 'dropped': 0}

    改成 `elif auto_claim:` 后，auto_claim=True 那行会变成 dropped=1。
    """
    _, w_off = _wl(tmp_path / "a", [_LRes("untraceable", "")], auto_claim=False)
    assert w_off == {"claims": 0, "evidence": 0, "dropped": 1}, f"实得 {w_off}"

    led, w_on = _wl(tmp_path / "b", [_LRes("untraceable", "")], auto_claim=True)
    assert w_on == {"claims": 1, "evidence": 0, "dropped": 0}, (
        f"显式 auto_claim 时一条都不该被丢（dropped 必须为 0），实得 {w_on}")
    assert len(led.claims()) == 1, f"auto_claim 显式要了就该立论，实得 {len(led.claims())}"


def test_dropped_counts_the_second_of_a_duplicate_url(tmp_path):
    """重复 URL 是 `add_evidence` 返回 None 的第二个成因。

    实测（两条同 URL）：auto_claim=False -> evidence=1 dropped=1。
    只测"不可溯源"这一个成因的话，这个成因下变异仍然全绿。
    """
    _, w = _wl(tmp_path / "c", [_LRes("dup", "https://x.dev/a"),
                               _LRes("dup", "https://x.dev/a")], auto_claim=False)
    assert w == {"claims": 0, "evidence": 1, "dropped": 1}, f"实得 {w}"


def test_dropped_stays_zero_when_everything_is_traceable(tmp_path):
    """反向对照：可溯源时 dropped 恒为 0（两个成因都不触发）。"""
    for ac in (False, True):
        _, w = _wl(tmp_path / ("d%s" % ac), [_LRes("good", "https://x.dev/a")],
                   auto_claim=ac)
        assert w["dropped"] == 0, f"auto_claim={ac} 时可溯源 URL 不该被丢，实得 {w}"
        assert w["evidence"] == 1, f"auto_claim={ac} 时应记 1 条证据，实得 {w}"



# ===========================================================================
# 十四、cmd_search 的两道门（research.py L1160 / L1201）
# ===========================================================================
# 这两条在 367 行的 cmd_search 里，要真的跑一遍检索流程才观察得到。
# 夹具形状照抄 test_v6170_source_language_queries.py（现成的、可跑通的那套），
# 唯一的坑：引擎必须同时有 `is_available()` 与 `is_configured()`，
# 少一个会在 L984 的 get_configured_chain() 上 AttributeError。
#
# 实测（一条结果 total=68.4 / relevance=92.5）：
#   min_score 68.35 -> 保留 1/1     68.4 -> 保留 1/1     68.45 -> 保留 0/1
#   reflect_rounds 0（plan 非空）-> 不反思              1 -> 反思轮出现

_CS_TOPIC = "retrieval augmented generation evaluation"
_CS_TITLE = "Retrieval Augmented Generation Evaluation Benchmark"
_CS_CONTENT = "retrieval augmented generation " * 20
_CS_TOTAL = 68.4          # 实测值，见本节上方的说明


def _cs_engine():
    from engines.base import EngineMetadata

    class _E:
        def __init__(self):
            self.metadata = EngineMetadata(
                name="alpha", layer=1, description="d", requires_config=False,
                config_keys=[], capabilities=["search"], priority=1)

        def get_name(self):
            return self.metadata.name

        def get_layer(self):
            return self.metadata.layer

        def has_capability(self, cap):
            return cap in self.metadata.capabilities

        def is_available(self):
            return True

        def is_configured(self):
            """v6.62 起 registry.get_configured_chain() 会问这个；
            漏掉它会在 L984 直接 AttributeError。"""

            return True

        def search(self, query, max_results=10, **kw):
            from engines.base import SearchResult

            return [SearchResult(title=_CS_TITLE, url="https://a.example/p1",
                                 content=_CS_CONTENT, source="alpha", score=0.9)]

    return _E()


def _cs_run(tmp_path, **over):
    """跑一次 cmd_search，返回它的 stderr+stdout。"""
    import argparse
    import contextlib
    import io

    import cache as cache_mod

    from engines.base import EngineRegistry

    cache_mod.CACHE_DIR = tmp_path / "cache"     # 别让缓存跨轮次串味
    base = dict(query=_CS_TOPIC, sources="alpha", source_query=None, all=False,
                limit=10, depth="standard", effort="quick", breadth=1,
                dimensions=None, perspectives=None, reflect_rounds=0,
                language="en", region="us", ledger=None, auto_claim=False,
                no_cache=True, no_plan=False, min_score=0, min_relevance=0,
                llm_score=False, format="markdown", output=None)
    base.update(over)
    reg = EngineRegistry()
    reg.register(_cs_engine())
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
        rs_cmd_search(argparse.Namespace(**base), reg)
    return buf.getvalue()


def test_min_score_keeps_result_scoring_exactly_at_the_threshold(tmp_path):
    """`craap_score['total'] >= args.min_score` —— **恰好等于阈值要留下**。

    实测（total=68.4）：min_score 68.35 / 68.40 -> 保留 1/1；68.45 -> 保留 0/1。
    改成 `>` 后，恰好压线的那条会被静默丢掉，而用户给的门槛就是它本身。
    """
    import re
    kept = {}
    for ms, want in ((_CS_TOTAL - 0.05, "1"), (_CS_TOTAL, "1"), (_CS_TOTAL + 0.05, "0")):
        out = _cs_run(tmp_path / ("m%s" % ms), min_score=ms)
        m = re.search(r"过滤后: (\d+)/(\d+)", out)
        assert m, f"min_score={ms} 没触发过滤段，输出：{out[-200:]}"
        kept[ms] = m.group(1)
        assert m.group(1) == want, (
            f"min_score={ms} 时应保留 {want} 条（total=68.4），实得 {m.group(1)}")
    assert kept[_CS_TOTAL] == "1", "恰好等于阈值的这条必须留下"


def test_min_score_zero_does_not_enter_the_filter_branch(tmp_path):
    """`if args.min_score > 0` —— 0 不进过滤段（整段被跳过）。"""
    out = _cs_run(tmp_path / "zero", min_score=0)
    assert "过滤后:" not in out, (
        "min_score=0 时不该进入过滤段（没有门槛可过滤），输出里却出现了「过滤后:」")


def test_reflect_rounds_zero_means_no_reflection_even_with_a_plan(tmp_path):
    """`args.reflect_rounds > 0 and plan` —— **0 轮就是不反思**。

    实测（no_plan=False，plan 非空）：rounds=0 -> 无「反思轮」；
    rounds=1 -> 出现「反思轮」。改成 `>= 0` 后，0 轮会走进去，
    `range(1, 0+1)` 空转不报错 —— 于是"没开反思"和"开了但一轮都没跑"
    在输出上完全一样，配置失效静默无声。
    """
    off = _cs_run(tmp_path / "r0", reflect_rounds=0)
    on = _cs_run(tmp_path / "r1", reflect_rounds=1)
    assert "反思轮" not in off, "reflect_rounds=0 却跑了反思"
    assert "反思轮" in on, "reflect_rounds=1 却没跑反思"


def test_no_plan_short_circuits_reflection_regardless_of_rounds(tmp_path):
    """反向对照：`and plan` 那半边 —— no_plan=True 时几轮都不反思。"""
    for rr in (0, 1):
        out = _cs_run(tmp_path / ("np%s" % rr), reflect_rounds=rr, no_plan=True)
        assert "反思轮" not in out, f"no_plan=True 且 rounds={rr} 却跑了反思"



# ===========================================================================
# 十五、ledger._value 的「像选项」守卫（ledger.py L1422）
# ===========================================================================
# `if len(val) > 1 and val.startswith('-')` —— 长度门槛把**单个连字符**排除在外。
#
# ⚠️ **可观察量是报错文案，不是退出码。** 实测三种值都 exit 2：
#   '-'         守卫不触发，被下游拒（"来源 - 点不回原文"）
#   'sub-dir/a' 守卫不触发，被下游拒
#   '--text'    守卫触发（"那看起来是下一个选项"）
# 用退出码断言的话，这三种一模一样，测试恒绿。
#
# 两侧都要钉：
#   长度 1 的 '-'  ->  守卫**不该**触发（改成 >= 1 会被抓）
#   长度 2 的 '-a' ->  守卫**该**触发（改成 > 2 会被抓）

_LEDGER_PY = S / "ledger.py"
_VALUE_GUARD_TEXT = chr(0x770B) + "起" + chr(0x6765) + chr(0x662F) + chr(0x4E0B) + chr(0x4E00) + chr(0x4E2A) + chr(0x9009) + chr(0x9879)
# ↑ 「看起来是下一个选项」—— 用码点拼，绕开 shell heredoc 的中文损坏


def _run_ledger(*args):
    import subprocess

    r = subprocess.run([sys.executable, str(_LEDGER_PY), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def _guarded(tmp_path, value):
    """用 `--url <value>` 试一次，返回 (退出码, _value 守卫是否触发)。"""
    led = tmp_path / "led"
    _run_ledger("add-claim", "--session", str(led), "--text", "x", "--id", "c1")
    code, out = _run_ledger("add-source", "--session", str(led), "--claim-id", "c1",
                            "--url", value, "--title", "T", "--craap", "70")
    return code, _VALUE_GUARD_TEXT in out


def test_value_guard_does_not_fire_on_a_lone_hyphen(tmp_path):
    """单个 `-` 是合法取值（stdin 约定），**不该**被当成"下一个选项"。

    实测：`--url -` 时守卫不触发，错误来自下游（"来源 - 点不回原文"）。
    改成 `len(val) >= 1` 之后，守卫会抢先触发并给出误导性的提示。
    """
    code, fired = _guarded(tmp_path / "hy", "-")
    assert not fired, (
        f"单个连字符不该触发「像选项」守卫（实测未触发），却触发了；exit={code}")


def test_value_guard_fires_from_length_two_upwards(tmp_path):
    """长度 >= 2 且以 `-` 开头 -> 必须触发守卫。

    实测：`-a` / `-abc` / `--text` 都触发。改成 `> 2` 之后 `-a` 会被漏掉 ——
    而 `-a` 恰恰是最容易由 shell 变量落空顶上来的一种。
    """
    for val in ("-a", "-abc", "--text", "--session"):
        code, fired = _guarded(tmp_path / ("g" + val.strip("-")), val)
        assert fired, (
            f"{val!r}（长度 {len(val)}）应触发「像选项」守卫，实得未触发；exit={code}")


def test_value_guard_ignores_values_that_merely_contain_a_hyphen(tmp_path):
    """反向对照：不以 `-` 开头就不触发（哪怕中间含连字符）。"""
    code, fired = _guarded(tmp_path / "mid", "sub-dir/a")
    assert not fired, f"'sub-dir/a' 不以 - 开头，不该触发守卫（exit={code}）"


def test_value_guard_lets_a_real_url_through(tmp_path):
    """守门不能变成门本身：正常 URL 必须照旧通过。"""
    code, fired = _guarded(tmp_path / "ok", "https://example.org/a")
    assert not fired and code == 0, (
        f"正常 URL 被挡住了（exit={code}）：这是门本身，不是守门")



# ===========================================================================
# 十六、HTML 报告的正文截断（research.py L1541）
# ===========================================================================
# `content[:500] + ('...' if len(content) > 500 else '')`
#
# 实测：499 -> 499 字无省略号；**500 -> 500 字无省略号**；
#       501 -> 503 字（500 + '...'）；900 -> 503 字。
#
# 两个变异分别要两侧都钉：
#   `> 500` -> `>= 500`   只有"恰好 500"才显形
#   `[:500]` -> `[:501]`   只有"恰好 501"才显形（501 时截断长度变了）

def _html_content(out):
    import re

    m = re.search(r"<div class='content'>(.*?)</div>", out, re.S)
    assert m, f"报告里没有 content 段：{out[-200:]}"
    return m.group(1)


class _HtmlRes:
    def __init__(self, content):
        self.title, self.url, self.source = "T", "https://x.dev/a", "s"
        self.content = content
        self.craap_score = {"total": 70.0, "grade": "medium"}


def test_html_report_keeps_exactly_500_chars_without_ellipsis(tmp_path):
    """**恰好 500 字不加省略号** —— `len(content) > 500` 是严格大于。

    改成 `>= 500` 之后，正文刚好 500 字的结果会凭空多出三个点，
    而"内容被截断了"是个会误导读者的信号（他以为还有下文）。
    """
    import research as rs

    for n, want_len, want_dots in ((499, 499, False), (500, 500, False),
                                   (501, 503, True), (900, 503, True)):
        out = rs._generate_simple_html({}, [_HtmlRes("y" * n)], None)
        got = _html_content(out)
        assert len(got) == want_len, (
            f"content 长度 {n} 时输出应为 {want_len} 字，实得 {len(got)}")
        assert got.endswith("...") is want_dots, (
            f"content 长度 {n} 时省略号应为 {want_dots}，实得 {got[-5:]!r}")


def test_html_report_truncates_to_exactly_500(tmp_path):
    """`[:500]` 的截断长度也要单独钉 —— `[:501]` 只在 501 字时露出来。"""
    import research as rs

    out = rs._generate_simple_html({}, [_HtmlRes("y" * 501)], None)
    body = _html_content(out)
    assert body == "y" * 500 + "...", (
        f"501 字应截成 500 字加三点，实得长度 {len(body)}：{body[-6:]!r}")




# ===========================================================================
# 十七、content_identity 的正文长度门槛（ledger.py L973）
# ===========================================================================
# `len(abody) < MIN_IDENTITY_BODY or len(tbody) < MIN_IDENTITY_BODY`
# MIN_IDENTITY_BODY = 400（任一侧正文不足 400 字按空壳拒：404 / 风控页 / JS 壳）
#
# ⚠️ **门槛量的是 `_norm_body()` 之后的长度，不是原始长度。**
# `_norm_body` 会把连续空白压成一个空格并 strip —— 我第一版用
# `("nav " * 20) + FRAG + ...` 构造，原始 256 字、归一化只有 236，
# 于是「400 字」那个用例其实只有 236 字，被拒得莫名其妙。
# 夹具改成用 'x' 填充（'x' 不产生空白），才能把归一化后长度精确控住。
#
# 实测（归一化后长度）：
#   400/400 -> 绑成同一制品    399/400 -> 拒    400/399 -> 拒    399/399 -> 拒

_CI_DOCS = "https://docs.example.com/en/gpu/index.html"
_CI_REPO = "https://raw.githubusercontent.com/v/x/main/docs/gpu.md"
_CI_FRAG = ("vLLM does not support Windows natively. Use WSL instead.")
_CI_MIN_BODY = 400          # 实测值 = ledger.MIN_IDENTITY_BODY


def _ci_body(n):
    """归一化后长度恰好 n 的正文，且含那条逐字片段。"""
    return (_CI_FRAG + " " + "x" * (n - len(_CI_FRAG) - 1))[:n]


def _ci_probe(tmp_path, n_doc, n_repo):
    """跑一次 content_identity，返回 (绑成几条, stderr)。"""
    import contextlib
    import io

    from ledger import ResearchLedger

    led = ResearchLedger(str(tmp_path / ("l%s_%s" % (n_doc, n_repo)))).init()
    led.add_claim("doc says " + chr(0x300C) + _CI_FRAG + chr(0x300D), topic="t")
    cid = led.claims()[0]["id"]
    led.add_source(cid, _CI_DOCS, title="doc", tier=1)
    bodies = {_CI_DOCS: _ci_body(n_doc), _CI_REPO: _ci_body(n_repo)}
    # 断言夹具本身准确 —— 长度量错的话，下面所有断言都失去意义
    import ledger as lg
    assert len(lg._norm_body(bodies[_CI_DOCS])) == n_doc, "doc 夹具长度不对"
    assert len(lg._norm_body(bodies[_CI_REPO])) == n_repo, "repo 夹具长度不对"
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
        n = led.content_identity([cid], _CI_DOCS, _CI_REPO,
                                 body_of=lambda u: bodies.get(u, ""))
    return n, buf.getvalue()


def test_identity_accepts_bodies_exactly_at_the_minimum(tmp_path):
    """两侧都**恰好 400 字**时必须绑成同一制品（`len < 400` 是严格小于）。

    改成 `<= 400` 之后，正文刚好 400 字的这一档会被当成空壳拒掉 ——
    而 400 字远够不短，拒它的理由（"404 / 风控页 / JS 壳"）在这里不成立。
    """
    n, out = _ci_probe(tmp_path, _CI_MIN_BODY, _CI_MIN_BODY)
    assert n == 1, f"两侧各 {_CI_MIN_BODY} 字应绑成同一制品，实得 n={n}；stderr={out[:160]}"


def test_identity_rejects_when_either_side_is_one_char_short(tmp_path):
    """两侧独立：任一侧 399 字就拒（anchor 侧与 target 侧都要验）。"""
    short = _CI_MIN_BODY - 1
    for n_doc, n_repo, label in ((short, _CI_MIN_BODY, "锚点侧不足"),
                                 (_CI_MIN_BODY, short, "反查侧不足"),
                                 (short, short, "两侧都不足")):
        n, out = _ci_probe(tmp_path, n_doc, n_repo)
        assert n == 0, (
            f"{label}（{n_doc}/{n_repo}）应被拒，实得 n={n}")
        assert chr(0x6B63) + chr(0x6587) + chr(0x4E0D) + chr(0x8DB3) in out, (
            f"{label} 的拒绝理由应说明正文不足，stderr={out[:160]}")


def test_identity_minimum_matches_the_module_constant(tmp_path):
    """夹具里的 400 不是抄来的 —— 断言它等于 ledger.MIN_IDENTITY_BODY。"""
    import ledger as lg

    assert lg.MIN_IDENTITY_BODY == _CI_MIN_BODY, (
        f"夹具写的是 {_CI_MIN_BODY}，模块常量是 {lg.MIN_IDENTITY_BODY} —— "
        f"常量改了而夹具没改，这条测试会在错误的长度上通过")




# ===========================================================================
# 九、_score_relevance 的标题长度分档（L491/493/495）
# ===========================================================================
# `10 <= title_len <= 80` → 1.0 ｜ `< 10` → 0.5 ｜ `> 80` → 0.7
#
# ⚠️ 隔离技巧：query = "aa"、标题与内容同长且都是同一串字符 ——
# 于是两个 coverage 恒为 1.0（除了 len<2 那种 "aa" 装不进 "a" 的情况），
# **分数里唯一在动的就是 length_score**，分档值因此是干净可读的。
#
# 我第一版喂的是真实英文标题（30/19/9/3 字），一个都没落在 10 上，
# 所以装上变异后全绿 —— 这正是「只喂正常值」的那种漏法。

_TITLE_LEN_TIERS = [(9, 90.0), (10, 100.0), (11, 100.0),
                    (80, 100.0), (81, 94.0)]


def test_relevance_title_length_tiers_hit_their_edges():
    """标题长度的两个边界值（10 和 80）都要逐个喂。"""
    sc = CraapScorer()
    q = "aa"
    for n, want in _TITLE_LEN_TIERS:
        t = "a" * n
        got = sc._score_relevance(q, t, t)
        assert got == want, (
            f'标题 {n} 字应得 {want}，实得 {got}。'
            f'两端边界值（10 与 80）是最容易被漏掉的：'
            f'把 `elif title_len < 10` 改成 `< 11`，只有恰好 10 字时才显形。')


def test_relevance_very_short_title_scores_worst_of_the_three_tiers():
    """过短标题（0.5）必须比过长标题（0.7）更差 —— 别把两档写反。"""
    sc = CraapScorer()
    q = "aa"
    short = sc._score_relevance(q, "a" * 9, "a" * 9)     # 90.0
    ideal = sc._score_relevance(q, "a" * 20, "a" * 20)   # 100
    long_ = sc._score_relevance(q, "a" * 90, "a" * 90)   # 94.0
    assert short < long_ < ideal, (
        f'过短 {short} / 过长 {long_} / 适中 {ideal} —— '
        f'正确顺序是 0.5 < 0.7 < 1.0，反了就说明分档写颠倒了')
