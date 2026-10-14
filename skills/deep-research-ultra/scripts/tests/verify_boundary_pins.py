"""验证「边界钉死测试」真的钉得住 —— 装上变异，要求它们变红。

## 为什么必须有这一步

**测试通过 ≠ 钉住了边界。** 一条测试完全可以在变异装上时照样绿 ——
如果它测的压根不是那个边界、或者断言写得太松。

而本项目最贵的一次失误恰恰是"造完就信"：我写过一堆检查机制，
每一堆都在**自己报绿之后**才发现问题。所以这一步不是加分项，是前提。

## 怎么做

对每个 (文件, 行号, 算子) 组合：
1. 在**副本**上装上变异（真实工作区一个字节都不能动 —— v6.89 的教训）
2. 只跑 `test_v688_boundary_pins.py`
3. **必须红**。绿就说明那条边界其实没被钉住，如实报出来

## 它抓过什么

这条脚本自己也被抓过两次：
- 忘了 `craap_score` 属性 → `score_batch` 走 dict 分支直接 TypeError
- 期望值是在**被污染的工作区**上量的（三条全错）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

S = Path(__file__).resolve().parents[1]
REPO = S.parents[2]
sys.path.insert(0, str(S))

import mutate_gen as MG  # noqa: E402
import probe_mutation as PM  # noqa: E402
import analysis.boundaries as BD  # noqa: E402

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
PINS = "test_v688_boundary_pins.py"

# 这些边界由 test_v688_boundary_pins.py（或已存在的测试）钉死。
# 键是 (文件, 行号, 期望的算子) —— 算子用来确认我们找的确实是那个变异。
#
# ⚠️ 这份清单第一版有两条列错了，被验证脚本当场抓出来：
#   · `score.py:426` 我以为是 `_score_relevance` 的 `if not query:`，
#     实际是 `_relevance_is_reliable` 的 —— **而且那个变异是等价的**
#     （空查询走原逻辑也返回 True，非空查询两种写法都返回 True，
#      那个早退是冗余的）。已移到 EQUIVALENT。
#   · `verify_quotes.py:113` 我以为 `floor=2` 在这行，实际 113 是
#     `while i != -1`，`floor=2` 在 **L60** —— 而它已被
#     test_v687 的 `test_quoted_spans_default_floor_stays_at_two` 钉住。
#     改列 L60。
#
# **验证脚本存在的意义就在这里**：这两条如果没被它抓出来，
# 就会一直被我当成"已钉住"。
CLAIMED = [
    ("score.py", 398, "compare"),   # years_ago <= 0
    ("score.py", 400, "compare"),   # years_ago == 1
    ("score.py", 402, "compare"),   # years_ago == 2
    ("score.py", 404, "compare"),   # years_ago == 3
    ("score.py", 406, "compare"),   # years_ago <= 5
    ("score.py", 551, "not"),       # if not content（_score_accuracy）
    ("score.py", 691, "const"),     # total >= 75
    ("score.py", 693, "const"),     # total >= 50
    ("score.py", 736, "compare"),   # min_score > 0
    ("verify_quotes.py", 60, "const"),    # floor=2
    ("verify_quotes.py", 68, "boolop"),   # frag and frag not in out
]

# 等价变异：改了但行为不变，**不该**被任何测试抓到。
# 列在这里是为了让"它存活"有解释，否则会被当成缺口。
EQUIVALENT = [
    ("score.py", 426, "not",
     "`if not query: return True` 去掉 not —— 空查询走原逻辑也返回 True"
     "（没有中文字符），非空查询两种写法都返回 True。那个早退是冗余的。"),
]


def run_suite(scr: Path, timeout=900):
    for d in scr.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    args = [sys.executable, "-m", "pytest", "-q", "--no-header",
            "-p", "no:cacheprovider", str(scr / "tests" / PINS)]
    try:
        r = subprocess.run(args, cwd=str(scr), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env=ENV)
    except subprocess.TimeoutExpired:
        return "hang"
    return "red" if r.returncode != 0 else "green"


def main():
    print("=" * 74)
    print("验证：装上变异，边界钉死测试必须变红")
    print("=" * 74)
    print()

    before = PM._fingerprint(S)
    td = Path(tempfile.mkdtemp(prefix="drux_pinverify_"))
    scr = PM.make_copy(td / "repo")
    base = run_suite(scr)
    print(f"步骤 0：未变异时 {PINS} 必须是 green，实得 {base}")
    if base != "green":
        print("  基线就红 —— 后面全都不可信，先修测试")
        shutil.rmtree(td, ignore_errors=True)
        return 1
    print()

    # 预先算好各文件的变异，避免反复 parse
    gen = {}
    for f, line, op in CLAIMED:
        if f not in gen:
            p = scr / f
            ms, _ = MG.generate(p, cap=10 ** 6)
            gen[f] = {(m.line, m.kind): m for m in ms}

    print(f"{'边界':<34} {'装上':<12} {'钉死测试':<10}")
    print("-" * 74)
    problems = []
    for f, line, op in CLAIMED:
        m = gen[f].get((line, op))
        if m is None:
            print(f"{f + ':' + str(line):<34} {'找不到变异':<12} {'—':<10}")
            problems.append((f, line, "生成器在该行找不到对应算子"))
            continue
        p = m.path
        data = p.read_bytes()
        try:
            p.write_bytes(m.apply(data))
            assert PM._is_under(p, td), f"变异目标 {p} 不在副本下"
            st = run_suite(scr)
        finally:
            p.write_bytes(data)
            PM.clear_pycache(scr)
        ok = st == "red"
        if not ok:
            problems.append((f, line, f"装上 {op} 变异后测试仍 {st} —— 没钉住"))
        print(f"{f + ':' + str(line):<34} "
              f"{op + '（' + m.repl[:8] + '）':<12} {'红 ✓' if ok else st + ' ✗':<10}")

    now = PM._fingerprint(S)
    touched = ([k for k in before if before[k] != now.get(k)]
               + [k for k in now if k not in before])
    print()
    if touched:
        print(f"★ 真实工作区被改动了：{touched[:5]} —— 这就是 v6.89 那个事故")
        problems.append(("<real-tree>", 0, f"真实工作区被改动: {touched[:3]}"))
    else:
        print("真实工作区：一个字节都没动 ✓")

    # --- 等价变异：必须**不**被任何测试抓到 ---
    print()
    print("=" * 74)
    print("等价变异对照：这些改了行为不变，测试**不该**变红")
    print("=" * 74)
    for f, line, op, why in EQUIVALENT:
        m = gen.get(f, {}).get((line, op))
        if m is None:
            print(f"  {f}:{line} [{op}]  生成器没找到该变异 —— 清单与代码脱节了")
            problems.append((f, line, "等价变异清单里的变异生成不出来了"))
            continue
        p = m.path
        data = p.read_bytes()
        try:
            p.write_bytes(m.apply(data))
            st = run_suite(scr)
        finally:
            p.write_bytes(data)
            PM.clear_pycache(scr)
        mark = "green ✓（符合预期）" if st == "green" else f"{st} ✗（等价变异却被抓到了）"
        print(f"  {f}:{line} [{op}] → {mark}")
        if st != "green":
            problems.append((f, line, "等价变异被测试抓到了 —— 也许它其实不等价"))
        print(f"      {why}")

    print()
    claimed = len(CLAIMED) - len({(f, l) for f, l, _ in problems if f != "<real-tree>"})
    print(f"钉住 {claimed}/{len(CLAIMED)} 个边界；"
          f"等价变异 {len(EQUIVALENT)} 个已解释")
    if problems:
        print()
        print("没钉住的：")
        for f, line, why in problems:
            print(f"  {f}:{line}  {why}")
    print()
    print("结论：", "全部钉住" if not problems else f"{len(problems)} 处有问题")
    shutil.rmtree(td, ignore_errors=True)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())