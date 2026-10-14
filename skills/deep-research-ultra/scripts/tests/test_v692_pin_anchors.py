"""行号锚点：把「钉的是哪一行」从纪律变成机械门。

## 要挡什么

`verify_boundary_pins.py` 的 `CLAIMED` / `EQUIVALENT` 清单里写的是
**行号**。行号会随代码改动平移，而清单不会自己跟着动。

v6.91 实测踩过一次：我以为 `floor=2` 在 `verify_quotes.py:113`，
实际 113 是 `while i != -1`，`floor=2` 在 **L60**。

那一次运气好 —— 生成器在 113 找不到对应算子，验证脚本报「找不到变异」
把它抓了出来。**但更危险的反面情形没有任何检查**：

    行号平移后，碰巧命中了同文件的**另一个**同类算子
    -> 验证脚本跑出一个合法的变异
    -> 钉死测试变红 -> 全绿
    -> 而它验证的根本不是我们想钉的那一条

那条路会**一路绿到底**。这是本项目「静默的部分失效比报错更坏」
的又一个实例，只不过这次失效的是验证机制本身。

## 怎么做

`verify_boundary_pins.PIN_ANCHORS` 给每个 (文件, 行号) 配一段代码指纹。
本文件核对它**此刻仍然在那一行**。代码一改，这里就红，
必须手动更新 —— 于是「行号要跟着代码走」从纪律变成了门。

## 为什么不用哈希而不用原文

原文能让人在失败时一眼看出「现在那行是什么、当时那行是什么」。
哈希更短，但失败时只给一个不匹配的摘要，读起来像玄学。
47 条锚点，一眼看懂的收益值得那几十行。

## 这条门自己也可能被架空

见 `test_anchors_cover_every_claimed_line`：如果有人加了 CLAIMED 条目
却忘了加锚点，那条就**不受任何行号漂移保护**。所以那一条也在本文件里。

## 这个机制被证明过

在副本上把 `score.py` 的 L398 换成 L400 的内容（模拟"行号平移后碰巧命中
同文件的另一个同类算子"），本文件**报红**并指出期望指纹与实际内容；
未改代码时 4 项全绿。真实工作区全程未被触碰。

理由同上：造完就信是本项目最贵的失误源，而"锚点核对"看起来太简单，
简单到像是不会失效 —— 正因如此更要证明它。
"""
from __future__ import annotations

import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import probe_mutation as pm  # noqa: E402


def _src_lines(fname: str) -> list[str]:
    raw = pm.S.joinpath(fname).read_bytes().decode("utf-8")
    return raw.split("\n")


def test_every_anchor_still_points_at_the_code_it_claims():
    """每个锚点的那一行，**此刻仍然包含**当初记下的指纹。"""
    import verify_boundary_pins as vbp

    bad = []
    for (fname, lineno), frag in vbp.PIN_ANCHORS.items():
        lines = _src_lines(fname)
        if lineno > len(lines):
            bad.append(f"{fname}:{lineno}  越界（文件只有 {len(lines)} 行）")
            continue
        cur = lines[lineno - 1].split("#")[0].strip()
        if frag not in cur:
            bad.append(
                f"{fname}:{lineno}\n"
                f"      期望含: {frag!r}\n"
                f"      实际是: {cur!r}")
    assert not bad, (
        "行号锚点与代码脱节了 —— 代码改动之后行号平移，清单没跟着动。"
        "**这种漂移最坏的情形是验证脚本验证了错误的那一行却全绿。**\n"
        "  把 PIN_ANCHORS 里对应的指纹更新成当前那一行的内容。\n  "
        + "\n  ".join(bad))


def test_anchors_cover_every_claimed_line():
    """CLAIMED / EQUIVALENT 里的每一行都必须有锚点。

    没有锚点的条目**不受行号漂移保护** —— 那是加条目时最容易漏的一步。
    """
    import verify_boundary_pins as vbp

    covered = set(vbp.PIN_ANCHORS)
    missing = []
    for label, table in (("CLAIMED", vbp.CLAIMED), ("EQUIVALENT", vbp.EQUIVALENT)):
        for entry in table:
            fname, lineno = entry[0], entry[1]
            if (fname, lineno) not in covered:
                missing.append(f"{label}: {fname}:{lineno}")
    assert not missing, (
        "这些条目没有行号锚点，代码一改就会静默指向别的行：\n  "
        + "\n  ".join(missing))


def test_anchor_table_has_no_dead_entries():
    """PIN_ANCHORS 里不能有清单已经不引用的行 —— 那是清理干净的信号。

    留着不报错，看起来无害；但它会让人以为那个位置仍被保护着。
    """
    import verify_boundary_pins as vbp

    used = {(e[0], e[1]) for e in vbp.CLAIMED}
    used |= {(e[0], e[1]) for e in vbp.EQUIVALENT}
    dead = sorted(set(vbp.PIN_ANCHORS) - used)
    assert not dead, f"这些锚点已无清单条目引用，请删掉：{dead}"


def test_anchors_are_actually_distinctive_enough():
    """锚点要在该文件里能定位到**唯一**一行 —— 否则等于没钉。

    同一文件里出现两行相同指纹（去掉行尾注释后）时，
    锚点无法区分它们；此时应当把指纹加长到能区分为止。
    """
    import verify_boundary_pins as vbp

    by_file = {}
    for (fname, lineno), frag in vbp.PIN_ANCHORS.items():
        by_file.setdefault(fname, []).append((lineno, frag))

    problems = []
    for fname, items in by_file.items():
        lines = _src_lines(fname)
        norm = [l.split("#")[0].strip() for l in lines]
        for lineno, frag in items:
            hits = [i + 1 for i, c in enumerate(norm) if frag and frag in c]
            if len(hits) > 1 and lineno not in hits:
                problems.append(
                    f"{fname}:{lineno} 指纹 {frag!r} 同时命中 {hits}，"
                    f"唯独不含它自己")
    assert not problems, (
        "这些锚点在本文件里指向多行，无法唯一定位：\n  "
        + "\n  ".join(problems))
