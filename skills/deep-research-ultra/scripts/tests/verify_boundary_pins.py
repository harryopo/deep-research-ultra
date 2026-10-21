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
    # ⚠️ 426 曾被我错放进 EQUIVALENT，用「纯英文查询扫一遍没变化」下的结论。
    # 错的：英文查询在 L428 `if not re.search(CJK, query)` 就 return 了，
    # 压根到不了 L426。换成中文查询后，命中 1 个 2-gram 的输入
    # 原 False、变异后 True —— 它是真边界，改列 CLAIMED。
    ("score.py", 426, "not", ""),       # if not query（_relevance_is_reliable）
    ("score.py", 440, "compare", ""),   # coverage >= RELEVANCE_COVERAGE_FLOOR
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
    # research.py filter_by_relevance 的四道门（嵌套门槛：外层不够数就整体放回）
    ("research.py", 402, "compare", "<"),        # min_relevance <= 0
    ("research.py", 409, "compare", ">"),        # _relevance(r) >= min_relevance
    ("research.py", 419, "const", "6"),          # min(target_count, 5)
    ("research.py", 420, "compare", ">"),        # len(strong) >= needed
    ("research.py", 834, "not", ""),             # elif not auto_claim
    # cmd_search 里的两道门：要真跑一遍检索流程才观察得到（夹具见测试文件）
    ("research.py", 1161, "compare", ">="),       # args.min_score > 0
    ("research.py", 1163, "compare", ">"),       # craap_score['total'] >= min_score
    ("research.py", 1544, "compare", ">="),      # len(content) > 500
    ("research.py", 1544, "const", "501"),       # content[:500]
    ("ledger.py", 973, "compare", "<="),         # len(abody) < MIN_IDENTITY_BODY
    ("ledger.py", 973, "boolop", "and"),         # ... or ... -> and
    ("ledger.py", 1422, "compare", ">="),        # len(val) > 1 -> >= 1
    ("ledger.py", 1422, "const", "2"),           # len(val) > 1 -> > 2
    ("ledger.py", 1422, "boolop", "or"),         # and -> or
    # validate_report.py：13 个边界一次没被跑过（v6.91 掐断在 67/87，
    # 掐掉的正是这个文件）。v6.92 加 --only 才第一次跑出 50.0%。
    # 未钉住的 7 条按类型：incl 4/5、thresh 2/3、len 1/2；guard 0/3。
    ("validate_report.py", 136, "compare", ">"),     # len(text) >= 16
    ("validate_report.py", 136, "const", "17"),      # text[:16]
    ("validate_report.py", 231, "const", "3"),       # level > 2
    ("validate_report.py", 251, "compare", ">"),     # chars >= MIN_OWN_SECTION_CHARS
    ("validate_report.py", 257, "compare", "!="),    # key == 'bluf'
    ("validate_report.py", 686, "const", "2"),       # sum(1 for ...)
    ("validate_report.py", 689, "compare", ">"),     # low_ratio >= 0.3
    # tier.py：全量实跑 87 个变异跑完后剩下的 5 条未钉，其中 4 条在这里。
    # 逐条实测之后：L133 与 L250 是真缺口，L135 两条是等价变异。
    ("tier.py", 133, "compare", ">"),        # len(parts) >= 3
    ("tier.py", 133, "const", "4"),          # 同上，改常量
    ("tier.py", 133, "boolop", "or"),         # and -> or（两段都要复合后缀）
    ("tier.py", 250, "const", "4"),          # len(args) == 3（--add-tier 恰好三参）
    # ── v6.94：--systematic 抽样撞出来的 6 条 ──────────────────────────────
    # 下面这几条**不在** `analysis/boundaries.py` 的 85 个边界里（那条分母是
    # 按 AST 类型提取的，「CLI 参数默认值」「条目过滤」「IO 重试」不是边界形态）。
    # 它们是 `probe_mutation.py --systematic` 按算子随机抽样撞出来的 ——
    # 也就是说：**边界清单有分母，随机抽样没有；两者互补，不是替代。**
    # 逐条实测过的可观察差异见 test_v688_boundary_pins.py 第十七节。
    ("research.py", 603, "boolop", "and"),    # goal=args.goal or ''  -> and
    ("research.py", 1075, "compare", "in"),   # name not in explicit_sources -> in
    ("research.py", 1105, "compare", "in"),   # 同上（降级链那份拷贝）
    ("research.py", 1217, "compare", "is"),   # ledger is not None -> is None
    ("ledger.py", 587, "const", "3"),         # max_retries=2 -> 3
    ("ledger.py", 1017, "boolop", "or"),      # type=='source' and claim_id -> or
]

# 等价变异：改了但行为不变，**不该**被任何测试抓到。
# 列在这里是为了让"它存活"有解释，否则会被当成缺口。
EQUIVALENT = [
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
    # `args.reflect_rounds > 0` → `>= 0`：会进分支，但 `range(1, 0+1)` 是空循环，
    # 而 `Reflector(max_rounds=0)` 构造本身没有副作用（实测可构造）。
    # 跑三次 cmd_search（rr=0/1/2）归一化时间戳后逐字节比对：**全部相同**。
    # 那一圈唯一的输出差异是报告里的「生成时间」，那是墙钟不是行为。
    ("research.py", 1204, "compare", ">=",
     "`args.reflect_rounds > 0` → `>= 0`：进分支但 range(1,1) 空转，"
     "Reflector(max_rounds=0) 无副作用；rr=0/1/2 三次实跑归一化时间戳后逐字节相同。"),
    # tier.py L135 `if len(parts) >= 2` 的两条：扫 13 个主机全部不变。
    # 原因：`parts[-2:]` 在只有 1~2 段时就等于整个 host，而上一行 L133
    # 新接管的 2 段情形返回 `parts[-3:]`，在 2 段时是同一个值 ——
    # 两行要么一起管要么都不管，阈值动一动没有可观察后果。
    ("tier.py", 135, "compare", ">",
     "`if len(parts) >= 2` → `> 2`：扫 13 个主机（example.com / co.uk / "
     "x.co.uk / a.b.co.uk / localhost / x.org.cn / deep.sub.x.com.cn ...）"
     "全部不变。`parts[-2:]` 在只有 1~2 段时就等于整个 host，"
     "而上一行 L133 新接管的 2 段情形返回 `parts[-3:]`，在 2 段时同值。"),
    ("tier.py", 135, "const", "3",
     "同上的另一种改法（`2` 改成 `3`）：13 个输入实测零变化，"
     "两行要么一起管要么都不管。"),
    # ── v6.94：--systematic 抽样跑出来的 8 个存活者，逐条量完之后 2 条落在这里
    # `and` -> `or`：`bool(Path(...))` 恒为 True（Path 没有 __bool__/__len__），
    # 所以 `p.parent or not p.parent.exists()` 永远短路在第一个操作数上，
    # **两版都会 mkdir**。副本上实测：PARENT_EXISTS/FILE_EXISTS 两边都是 True。
    # 这一条长得极像缺口 —— 它就是为了补目录才写的那半句 —— 但补目录这半个意图
    # 在两版里都实现了。
    ("research.py", 732, "boolop", "or",
     "`p.parent and not p.parent.exists()` → `or`：Path 没有 __bool__/__len__，"
     "`bool(p.parent)` 恒为 True，`or` 短路在第一个操作数，"
     "`p.parent.exists()` 根本不求值 —— 两版都会 mkdir。副本实测输出目录与文件两侧都建成。"),
    # `min(30, len(want))` → `min(31, ...)`：**63 个用例零差异**。
    # 原因是 `head` 只是预筛 —— L115 的
    # `_fold(seg)...[:len(want)] == want` 全等校验才是真门。
    # 而「want[:31] 的全部出现位置」必然是「want[:30] 的出现位置」的子集，
    # 所以 L115 判过的位置两版都会判过，判不过的位置两版都过不了。
    # 扫的长度 10/29/30/31/32/36/60 × 9 种语料形态（全文命中 / 只命中前 29、30、31 /
    # 早一个前缀+后一个全文 / 空语料 / 无关语料），逐个比对返回值：**差异 0**。
    # 与 `score.py:493`（被前序分支遮蔽）、`score.py:604/615/625`（min(N,0)=0）
    # 同族：常量看起来像阈值，实际被下游更严的检查吞掉了。
    ("verify_quotes.py", 109, "const", "31",
     "`head = want[:min(30, len(want))]` → `min(31, ...)`：head 只是预筛，"
     "L115 的 `... [:len(want)] == want` 全等校验才是真门；"
     "而 want[:31] 的出现位置是 want[:30] 的子集，故 L115 的判定两版一致。"
     "长度 10/29/30/31/32/36/60 × 9 种语料形态 = 63 个用例，差异 0。"),
    # ⚠️ 下面这条**曾经**被我当成等价变异放错在这里，留着当反面教材。
    #   它现在的正确归属是 CLAIMED（见上），教训写在这里免得我再犯：
    #   「扫了一批输入没变化」不等于等价 —— 那批输入必须真的能走到被测的行。
    #   我当时喂的是纯英文查询，而 L428 `if not re.search(CJK, query)` 会直接
    #   return，测的是 L428 不是 L426。
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


# ---------------------------------------------------------------------
# ANCHORS：把行号钉在**代码**上
# ---------------------------------------------------------------------
# 行号会随代码改动平移，而清单不会自己跟着动。v6.91 实测踩过：
# 我以为 floor=2 在 verify_quotes.py:113，实际 113 是 `while i != -1`。
# 那次是被「找不到变异」抓到的 —— 但**更危险的反面情形没有任何检查**：
# 行号平移后碰巧命中了同文件的另一个同类算子，验证脚本会全绿，
# 而它验证的根本不是我们想钉的那一条。
#
# 所以每条 (文件, 行号) 都配一段代码指纹，`test_v692_pin_anchors.py`
# 会核对它**此刻仍然在那一行**。代码一改，这里就红，必须手动更新 ——
# 也就是说「行号要跟着代码走」从纪律变成了机械门。
PIN_ANCHORS = {
    ('ledger.py', 113): 'while len(parts) > 2 and parts[-1].lower() in _LANDING_VIEWS:',
    ('ledger.py', 219): "sub = host[:-len('.stackexchange.com')] if len(host) > len('stackexchange.com') else ''",
    ('ledger.py', 366): "if seg[0] in ('blob', 'tree', 'raw', 'resolve') and len(seg) > 1:",
    ('ledger.py', 587): 'raw = _http_get(url, timeout=45, max_retries=2)',
    ('ledger.py', 973): 'if len(abody) < MIN_IDENTITY_BODY or len(tbody) < MIN_IDENTITY_BODY:',
    ('ledger.py', 1017): "if e.get('type') == 'source' and e.get('claim_id'):",
    ('ledger.py', 1422): "if len(val) > 1 and val.startswith('-'):",
    ('research.py', 402): 'if min_relevance <= 0:',
    ('research.py', 409): 'strong = [r for r in results if _relevance(r) >= min_relevance]',
    ('research.py', 419): 'needed = max(1, min(target_count, 5))',
    ('research.py', 420): 'if len(strong) >= needed:',
    ('research.py', 603): "goal=args.goal or '',",
    ('research.py', 732): 'if p.parent and not p.parent.exists():',
    ('research.py', 834): 'elif not auto_claim:',
    # ⚠️ 1072 与 1102 是**同一行代码的两份拷贝**，指纹必然相同。
    #   `test_anchors_are_actually_distinctive_enough` 判的是
    #   「命中多行且不含自己」才报错，两行都在 hits 里所以放过 —— 这是对的：
    #   锚点在这里的作用是「别漂到别的算子上」，而这两行本来就该一起动。
    ('research.py', 1075): "if not engine.has_capability('search') and name not in explicit_sources:",
    ('research.py', 1105): "if not engine.has_capability('search') and name not in explicit_sources:",
    ('research.py', 1161): 'if args.min_score > 0:',
    ('research.py', 1163): "all_results = [r for r in all_results if r.craap_score and r.craap_score.get('total', 0) >= args.min_score]",
    ('research.py', 1204): 'if args.reflect_rounds > 0 and plan:',
    ('research.py', 1217): 'if ledger is not None:',
    ('research.py', 1544): "display_content = content[:500] + ('...' if len(content) > 500 else '')",
    ('score.py', 398): 'if years_ago <= 0:',
    ('score.py', 400): 'elif years_ago == 1:',
    ('score.py', 402): 'elif years_ago == 2:',
    ('score.py', 404): 'elif years_ago == 3:',
    ('score.py', 406): 'elif years_ago <= 5:',
    ('score.py', 426): 'if not query:',
    ('score.py', 440): 'return (hits / len(words)) >= CraapScorer.RELEVANCE_COVERAGE_FLOOR',
    ('score.py', 491): 'if 10 <= title_len <= 80:',
    ('score.py', 493): 'elif title_len < 10:',
    ('score.py', 551): 'if not content:',
    ('score.py', 558): 'if content_len > 1000:',
    ('score.py', 560): 'elif content_len > 500:',
    ('score.py', 562): 'elif content_len > 200:',
    ('score.py', 564): 'elif content_len > 50:',
    ('score.py', 604): 'if commercial_count > 0:',
    ('score.py', 615): 'if educational_count > 0:',
    ('score.py', 625): 'if bias_count > 0:',
    ('score.py', 691): 'if total >= 75:',
    ('score.py', 693): 'elif total >= 50:',
    ('score.py', 736): 'if min_score > 0:',
    ('tier.py', 133): 'if len(parts) >= 3 and parts[-1] in composite and parts[-2] in composite:',
    ('tier.py', 135): 'if len(parts) >= 2:',
    ('tier.py', 250): "if args[0] == '--add-tier' and len(args) == 3:",
    ('validate_report.py', 136): "if len(text) >= 16 and c.get('id'):",
    ('validate_report.py', 231): 'if level > 2:',
    ('validate_report.py', 251): 'if chars >= MIN_OWN_SECTION_CHARS and cites == 0:',
    ('validate_report.py', 257): "if key == 'bluf' and chars >= MIN_OWN_SECTION_CHARS:",
    ('validate_report.py', 686): "low = sum(1 for s in sources if s.get('tier') == 4)",
    ('validate_report.py', 689): 'if low_ratio >= 0.3:',
    ('verify_quotes.py', 60): 'def quoted_spans(text, floor=2):',
    ('verify_quotes.py', 68): 'if frag and frag not in out:',
    ('verify_quotes.py', 74): 'return [f for f in quoted_spans(text) if len(f) >= min_len]',
    ('verify_quotes.py', 109): 'head = want[:min(30, len(want))]',
    ('verify_quotes.py', 130): 'parts = [p for p in _ELLIPSIS_RE.split(frag) if len(_fold(p)) >= 6]',
    ('verify_quotes.py', 209): 'if len(frag) < min_len and frag not in unchecked:',
    ('verify_quotes.py', 213): 'if len(frag) < min_len:',
    ('verify_quotes.py', 218): 'if len(frag) > max_len and frag not in overlong:',
}
