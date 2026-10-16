# -*- coding: utf-8 -*-
"""v6.94：复核修正的方向必须是**上调**，不能是下调。

## 这条门挡的是什么

`--systematic` 跑完会抽样几个存活者跑全量复核。所谓「假存活」是
**收窄说 SURVIVED、而全量说抓到** —— 收窄漏掉了跨路径的失败。

而报出来的检测率用的是**收窄**结果。所以它**偏低**。

v6.94 第一版的警告写的是「收窄会藏住失败，检测率**偏高**，按比例**下调**」。
方向与自己统计的量相反。照做的人会把一个**被低估**的检测率再往下调 ——
数字朝「显得更差」的方向偏，照样是错。

## 为什么要给文字加一条测试

修正量本身是 `n_caught + fl * n_surv / sampled`，几个加乘而已。
**只测算术抓不住方向写反** —— 算术对、文案反的情况会一路绿灯。

所以这里测两件事，而且第二件是**结构上不同**的检查（读源码里有没有那句反向措辞），
不是让 agent 自己复述一遍自己的代码。同 `test_v693` 里那条
「断言注释里不含『--only 优先』」的做法。
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import probe_mutation as pm  # noqa: E402


def test_correction_raises_the_count_not_lowers_it():
    """3 个存活里翻了 2 个 -> 抓到的数必须**增加**。"""
    # v6.94 实测：n_caught=29, n_res=32, fl=2/3, 存活 3 个（全部抽样）
    est, exact = pm._recheck_correction(29, 32, 2, 3, 3)
    assert exact is True, "存活者全部抽样过时应当报『精确』"
    assert est == 31.0, f"应为 29+2=31，实得 {est}"
    assert est > 29, "修正量必须把抓到的数往上抬"


def test_correction_is_exact_only_when_every_survivor_was_sampled():
    """抽样不全时只能外推，且必须自称是估的。"""
    _, exact_all = pm._recheck_correction(29, 32, 2, 3, 3)
    assert exact_all is True
    est, exact_part = pm._recheck_correction(29, 32, 2, 2, 8)
    assert exact_part is False, "8 个存活只抽了 2 个，不能自称精确"
    assert abs(est - (29 + 2 * 8 / 2)) < 1e-9


def test_no_correction_when_nothing_flipped():
    """没有假存活就不许改动那个数。"""
    for args in ((29, 32, 0, 3, 3), (29, 32, 2, 0, 3)):
        est, _ = pm._recheck_correction(*args)
        assert est == 29, f"无假存活却把数字改了：{args} -> {est}"


def _printed_strings(func):
    """`func` 里所有会被**打印出来**的字符串字面量（已还原隐式拼接）。

    ## 为什么要剥掉注释

    v6.94 第一版这条测试直接 `inspect.getsource(systematic)` 然后子串搜 ——
    于是它抓到了**我自己写的历史注记**（注释里引用了那句错的话以便留档），
    以及文档串里「手工挑的变异 75% 系统性偏高」这个**无关且正确**的表述。

    这与 `afb059a` 记下的那条是同一个坑：**全文搜索分不清代码与说明文字**。
    我在那里栽过一次 —— `src.index("p.write_bytes(m.apply(data))")` 命中了
    文档串里的注释，导致我得出「断言排在写盘之后」的错结论。

    所以这里用 `tokenize` 丢掉 COMMENT token，只留 STRING。
    而文档串也是 STRING —— 所以判据要更具体：找**同时**含「偏高」与「下调」的
    那句，以及含「下调」又提「收窄」的那句，而不是见到「偏高」就报。

    ## 为什么要还原隐式拼接 —— 这条门第一版**真的失效过**

    `print("…检测率**偏高**，"
          "按比例下调…")` 是两个相邻的 STRING token。而那正是被修掉的那句的
    原本形状。第一版判据要求两个词在**同一个** token 里，于是：

        在副本上把那两句错话放回去 -> 测试仍然 6 passed

    门是绿的，放行的却是错的那边。**这条门自己被端到端证伪了才发现** ——
    和本项目此前十余次「造完就信」同一个形状，只是这次证伪的对象是那道
    本来就是用来抓错的门。所以下面有 `test_implicit_concatenation_is_rejoined`。
    """
    import io
    import tokenize

    src = inspect.getsource(func)
    # 括号里的换行会产出 NL token，隐式拼接的两个 STRING 之间正好夹着它 ——
    # 所以「相邻」要按「中间没有实义 token」来判，而不是「上一个 token 是 STRING」。
    # 第一版按后者写，拼接没还原成功，门放行了错的那边。
    SKIP = {tokenize.STRING, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
            tokenize.DEDENT, tokenize.COMMENT, tokenize.ENCODING, tokenize.ENDMARKER}
    runs, cur = [], []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.STRING:
            cur.append(tok.string)
        elif tok.type in SKIP:
            continue                      # 换行/缩进不打断拼接
        else:
            if cur:
                runs.append("".join(cur))  # 还原成一个真正的字面量
            cur = []
    if cur:
        runs.append("".join(cur))
    return runs


def test_systematic_never_tells_the_reader_to_adjust_downward():
    """**结构检查**：打印给用户的话里不得出现反向措辞。

    只测算术抓不住「算术对、文案反」，所以这一条查 `systematic()` 会打印什么。
    判据是两个词**同时**出现 —— 因为文档串里单独出现「偏高」是对的
    （说的是手工挑变异那批的选择偏差，与修正方向无关）。
    """
    import io
    import tokenize

    lits = _printed_strings(pm.systematic)
    HI = "\u504f\u9ad8"          # 偏高
    DOWN = "\u4e0b\u8c03"       # 下调
    NARROW = "\u6536\u7a84"     # 收窄

    bad = []
    for s in lits:
        # 「偏高」和「下调」同时出现在**同一段**打印文案里 = 方向说反了
        if HI in s and DOWN in s:
            bad.append(s[:120])
        # 或者明说要「下调」，且谈的是收窄 —— 那正是被修掉的那句
        elif DOWN in s and NARROW in s:
            bad.append(s[:120])
    assert not bad, (
        "systematic() 会打印出把修正方向说反的话 %s —— "
        "复核把存活翻成『全量抓到』意味着收窄**漏掉**了失败，"
        "报出来的检测率偏低，修正方向是**上调**。" % bad)


def test_implicit_concatenation_is_rejoined():
    """自证：相邻 STRING token 必须被拼回**一个**字面量。

    这条门第一版就是死在这里的 —— 端到端证伪时（副本上放回那两句错话，
    测试仍然 6 passed）才发现。所以这里用一个构造出来的例子钉住行为，
    免得「简化」回去。
    """
    import textwrap

    import probe_mutation as _pm

    def fake():
        print("AAA偏高，"
              "BBB下调BBB")

    runs = _printed_strings(fake)
    joined = [r for r in runs if "AAA" in r and "BBB" in r]
    assert joined, f"相邻 STRING token 没被拼回去：{runs}"
    assert "偏高" in joined[0] and "下调" in joined[0], (
        "拼回去之后两个词应当落在同一个字面量里，实得 %r" % (joined[0],))

    def fake_ok():
        print("收窄漏掉失败，检测率偏低，应当上调")

    runs_ok = _printed_strings(fake_ok)
    assert runs_ok, "单行字符串也该被收进来"


def test_the_correction_note_says_the_direction_is_up():
    """反向对照：应当明说『偏低』。写不出来就是没修。"""
    src = inspect.getsource(pm.systematic)
    assert "\u504f\u4f4e" in src, "复核修正的说明里必须出现「偏低」"
    assert "_recheck_correction" in src, "systematic() 应调用抽出来的纯函数算修正量"


def test_docstring_of_the_helper_states_the_direction_too():
    """helper 的文档字符串也要说对方向 —— 它是最容易被复制走的那段。"""
    doc = pm._recheck_correction.__doc__ or ""
    assert "\u4e0a\u8c03" in doc, "helper 文档里必须写明方向是上调"
    assert "\u504f\u4f4e" in doc, "helper 文档里必须写明原数字偏低"