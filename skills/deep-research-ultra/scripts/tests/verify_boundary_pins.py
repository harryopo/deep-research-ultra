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
# 键是 (文件, 行号, 算子, 替换值) —— **替换值必须进键**，
# 因为同一行可以有多个同类算子：L491 的 `10 <= title_len <= 80`
# 同时生成 `10→11` 和 `80→81` 两个 const，只用 (line, kind) 会撞车
# （第二版验证脚本就踩了这个，只跑到了其中一个）。
#
# ⚠️ 这份清单被验证脚本抓出过的错，全部留着不删：
#   · `score.py:426` 我以为是 `_score_relevance` 的 `if not query:`，
#     实际是 `_relevance_is_reliable` 的 —— **而且那个变异是等价的**。
#     已移到 EQUIVALENT。
#   · `verify_quotes.py:113` 我以为 `floor=2` 在这行，实际 113 是
#     `while i != -1`，`floor=2` 在 **L60**。改列 L60。
#   · `score.py:493` 我以为那是标题长度的下边界（`elif title_len < 10`），
#     补了"逐个长度喂"的测试后**仍然全绿** —— 因为 L491 的
#     `if 10 <= title_len <= 80` 已经把 `>= 10` 全接走了，
#     elif 里那个 `10` 是**被遮蔽的常量**：能进这一行的值域
#     只有 `title_len < 10` 和 `> 80`，阈值改成 11/12/999 都不影响。
#     扫标题长度 0..200 × 2 种查询共 401 个输入，实测零变化。
#     真正的边界在 L491，改列 L491 的两个 const。
#
# **验证脚本存在的意义就在这里**：这三条如果没被它抓出来，
# 就会一直被我当成"已钉住"或"缺口"。
CLAIMED = [
    ("score.py", 398, "compare", ""),   # years_ago <= 0
    ("score.py", 400, "compare", ""),   # years_ago == 1
    ("score.py", 402, "compare", ""),   # years_ago == 2
    ("score.py", 404, "compare", ""),   # years_ago == 3
    ("score.py", 406, "compare", ""),   # years_ago <= 5
    ("score.py", 551, "not", ""),       # if not content（_score_accuracy）
    ("score.py", 691, "const", "76"),   # total >= 75
    ("score.py", 693, "const", "51"),   # total >= 50
    ("score.py", 736, "compare", ""),   # min_score > 0
    ("verify_quotes.py", 60, "const", ""),    # floor=2
    ("verify_quotes.py", 68, "boolop", ""),   # frag and frag not in out
    # v6.88 边界实跑后补的簇
    ("score.py", 491, "const", "11"),   # 标题长度下界 10
    ("score.py", 491, "const", "81"),   # 标题长度上界 80
    ("score.py", 558, "const", "1001"),  # content_len > 1000
    ("score.py", 560, "const", "501"),   # content_len > 500
    ("score.py", 562, "const", "201"),   # content_len > 200
    ("score.py", 564, "const", "51"),    # content_len > 50
    # len 簇（v6.88 存活清单里的 8 条 len）—— 阈值两侧各退一格作对照
    ("verify_quotes.py", 74, "compare", ">"),    # len(f) >= min_len
    ("verify_quotes.py", 130, "compare", ">"),   # len(_fold(p)) >= 6
    ("verify_quotes.py", 209, "compare", "<="),  # len(frag) < min_len
    ("verify_quotes.py", 209, "compare", "in"),  # frag not in unchecked
    ("verify_quotes.py", 213, "compare", "<="),  # len(frag) < min_len
    ("verify_quotes.py", 218, "compare", ">="),  # len(frag) > max_len
    ("verify_quotes.py", 218, "compare", "in"),  # frag not in overlong
    ("ledger.py", 113, "compare", ">="),         # len(parts) > 2
    ("ledger.py", 113, "compare", "not in"),     # parts[-1] in _LANDING_VIEWS
    ("ledger.py", 366, "compare", ">="),         # len(seg) > 1
    ("ledger.py", 366, "compare", "not in"),     # seg[0] in (...)
]

# 等价变异：改了但行为不变，**不该**被任何测试抓到。
# 列在这里是为了让"它存活"有解释，否则会被当成缺口。
EQUIVALENT = [
    ("score.py", 426, "not", "",
     "`if not query: return True` 去掉 not —— 空查询走原逻辑也返回 True"
     "（没有中文字符），非空查询两种写法都返回 True。那个早退是冗余的。"),
    # 三个 `count > 0`：改成 `>= 0` 时，count 为 0 → min(30, 0*10) = 0
    # → `score -= 0`，**行为不变**。这三个是边界实跑里 `zero` 那一类
    # （33.3%）的全部存活者 —— 它们不是缺口，是等价变异。
    ("score.py", 604, "compare", "", "`if commercial_count > 0:` → `>= 0`：`min(30, 0*10)`=0，加减 0 无效果。"),
    ("score.py", 615, "compare", "", "`if educational_count > 0:` → `>= 0`：`min(15, 0*5)`=0，加减 0 无效果。"),
    ("score.py", 625, "compare", "", "`if bias_count > 0:` → `>= 0`：`min(20, 0*10)`=0，加减 0 无效果。"),
    # **被同一 if/elif 链的前序分支遮蔽的常量** —— 静态可判定的那一类等价变异。
    # L491 `if 10 <= title_len <= 80` 已经把 title_len >= 10 全接走；
    # L493 `elif title_len < 10` 只在 title_len < 10 或 > 80 时被求值，
    # 而这两个区间与阈值 10 无关。扫长度 0..200 × 2 种查询 = 401 个输入，实测零变化。
    # `len(host) > len('stackexchange.com')` → `>=`：唯一能触发 `>=` 的 host
    # 就是 'stackexchange.com' 本身，而它 `[:-16]` 仍是 ''，与 else 分支同值；
    # `sub` 之后只喂 `if site in ('', 'api', 'www'): return ''`，殊途同归。
    # 扫 27 个 host×path 组合实测零变化 —— 没有测试能钉它，也不该有。
    ("ledger.py", 219, "compare", ">=",
     "`len(host) > len('stackexchange.com')` → `>=`：唯一能触发的是裸域名，"
     "而 `'stackexchange.com'[:-16] == ''` 与 else 分支同值，27 个输入实测零变化。"),
    ("score.py", 493, "const", "11",
     "`elif title_len < 10` 的 10 被 L491 的 `10 <= title_len <= 80` 遮蔽 —— "
     "改成 11 后 401 个输入全部不变，**没有任何测试能钉它**。"),
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

    # 预先算好各文件的变异，避免反复 parse。
    # 键必须含 repl：同一行可能有多个同类算子（L491 的 10 和 80 都是 const）。
    gen = {}
    for entry in CLAIMED + EQUIVALENT:
        f = entry[0]
        if f not in gen:
            p = scr / f
            ms, _ = MG.generate(p, cap=10 ** 6)
            gen[f] = {(m.line, m.kind, m.repl): m for m in ms}

    def _find(f, line, op, repl):
        table = gen.get(f, {})
        if repl:
            return table.get((line, op, repl))
        hits = [m for (ln, kd, _), m in table.items() if ln == line and kd == op]
        if len(hits) > 1:
            return None          # 歧义 —— 逼调用方把 repl 写出来
        return hits[0] if hits else None

    print(f"{'边界':<34} {'装上':<12} {'钉死测试':<10}")
    print("-" * 74)
    problems = []
    for f, line, op, repl in CLAIMED:
        m = _find(f, line, op, repl)
        if m is None:
            print(f"{f + ':' + str(line):<34} {'找不到变异':<12} {'—':<10}")
            problems.append((f, line, f"生成器在 (行={line}, 算子={op}, 替换={repl or '未指定'}) 找不到", "CLAIMED"))
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
            problems.append((f, line, f"装上 {op} 变异后测试仍 {st} —— 没钉住", "CLAIMED"))
        print(f"{f + ':' + str(line):<34} "
              f"{op + '（' + m.repl[:8] + '）':<12} {'红 ✓' if ok else st + ' ✗':<10}")

    now = PM._fingerprint(S)
    touched = ([k for k in before if before[k] != now.get(k)]
               + [k for k in now if k not in before])
    print()
    if touched:
        print(f"★ 真实工作区被改动了：{touched[:5]} —— 这就是 v6.89 那个事故")
        problems.append(("<real-tree>", 0, f"真实工作区被改动: {touched[:3]}", "TREE"))
    else:
        print("真实工作区：一个字节都没动 ✓")

    # --- 等价变异：必须**不**被任何测试抓到 ---
    print()
    print("=" * 74)
    print("等价变异对照：这些改了行为不变，测试**不该**变红")
    print("=" * 74)
    for f, line, op, repl, why in EQUIVALENT:
        m = _find(f, line, op, repl)
        if m is None:
            print(f"  {f}:{line} [{op}]  生成器没找到该变异 —— 清单与代码脱节了")
            problems.append((f, line, "等价变异清单里的变异生成不出来了", "EQUIVALENT"))
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
            problems.append((f, line, "等价变异被测试抓到了 —— 也许它其实不等价", "EQUIVALENT"))
        print(f"      {why}")

    print()
    # problems 里同一行可能有多条（例如 L491 的 10 和 80 两个 const），
    # 所以按**整条**去重，不能按 (文件, 行号) —— 那样会把两条并成一条、
    # 让「钉住 N/M」的 N 虚高。src 用来区分是 CLAIMED 还是 EQUIVALENT 出的问题。
    bad_claimed = [p for p in problems if p[3] == "CLAIMED"]
    claimed = len(CLAIMED) - len(bad_claimed)
    print(f"钉住 {claimed}/{len(CLAIMED)} 个边界；"
          f"等价变异 {len(EQUIVALENT)} 个已解释")
    if problems:
        print()
        print("问题：")
        for f, line, why, src in problems:
            print(f"  [{src}] {f}:{line}  {why}")
    print()
    print("结论：", "全部钉住" if not problems else f"{len(problems)} 处有问题")
    shutil.rmtree(td, ignore_errors=True)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())