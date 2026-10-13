"""变异生成器的自检 —— 生成器坏了，后面那个检测率数字就没意义。

## 为什么单独给生成器写测试

第一版生成器**48 个变异里 22 个语法错**（切出来的是 `'t` 这种碎片），
根因是 `sum(len(l) + 1 ...)` 累加行长 —— `splitlines(keepends=True)`
对 CRLF 每行结尾是 2 个字符，那个 `+1` 让**每一行**都多算 1。

一个坏掉的生成器不会报错，它只会**给出更难看的数字**。所以这里逐条钉住
它必须满足的性质，而不是钉住它恰好生成哪几个。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import mutate_gen as MG  # noqa: E402

MODULES = ("score.py", "verify_quotes.py", "research.py", "ledger.py")


def _all_for(name, cap=400):
    p = S / name
    ms, dropped = MG.generate(p, cap=cap)
    return p, ms, dropped


# ---------------------------------------------------------------------------
# 一、位置算得对不对 —— CRLF 与中文是两头坑
# ---------------------------------------------------------------------------

def test_every_mutant_applies_to_exactly_the_node_it_names():
    """**每个**变异应用后都必须还能编译，且改的正是它报告的那一行。

    第一版 22/48 语法错，就是没做这个检查。CRLF 每行 2 字符结尾，
    `len(l)+1` 让每一行都多算 1；AST 的 col_offset 又是字节不是字符。
    """
    bad = []
    for name in MODULES:
        p, ms, _ = _all_for(name)
        data = p.read_bytes()
        for m in ms:
            try:
                compile(m.apply(data), str(p), "exec")
            except (SyntaxError, ValueError) as e:
                bad.append(f"{m.label()} → {e.msg}")
            # 改完的行号必须还在原处：行号变了会误伤盯行号的测试
            mut = m.apply(data)
            ln = mut[:m.start].count(b"\n") + 1
            if ln != m.line:
                bad.append(f"{m.label()} → 应用后行号变成 {ln}")
    assert not bad, "有变异改坏了位置（这类变异会让套件 ImportError，"\
                    f"每个文件都「被抓到」，检测率虚报到 100%）：\n    " \
                    + "\n    ".join(bad[:8])


def test_generator_is_byte_accurate_on_crlf_files():
    """直接钉住 CRLF 这件事：把源码换成 CRLF，变异仍要算得准。

    仓库文件在 Windows 上是 CRLF（git 每次都警告 LF will be replaced）。
    按字符累加行长在 LF 下碰巧是对的、CRLF 下线性错位 —— 这类 bug
    在只跑 LF 的机器上根本不会暴露。
    """
    src = (S / "score.py").read_bytes().decode("utf-8")
    tmp = S / "__pycache__" / "_crlf_probe.py"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_bytes(src.replace("\r\n", "\n").replace("\n", "\r\n")
                    .encode("utf-8"))
    try:
        ms, _ = MG.generate(tmp, cap=40)
        data = tmp.read_bytes()
        broken = []
        for m in ms:
            try:
                compile(m.apply(data), str(tmp), "exec")
            except (SyntaxError, ValueError) as e:
                broken.append(f"{m.label()} → {e.msg}")
        assert not broken, (
            "CRLF 下变异算错了位置——正是 `len(l)+1` 那个坑：\n    "
            + "\n    ".join(broken[:6]))
    finally:
        tmp.unlink(missing_ok=True)


def test_generator_is_byte_accurate_with_chinese_source():
    """源文件里有中文时，AST 的 `col_offset`（字节）不能按字符算。"""
    has_cn = any(re.search(r"[\u4e00-\u9fff]",
                             (S / n).read_bytes().decode("utf-8"))
                 for n in MODULES)
    assert has_cn, "这批文件里本来就有中文，这条断言的前提没了"
    for name in MODULES:
        p, ms, _ = _all_for(name)
        data = p.read_bytes()
        for m in ms:
            compile(m.apply(data), str(p), "exec")   # 算错就是 SyntaxError


# ---------------------------------------------------------------------------
# 二、抽样：必须按算子平衡，否则测的只是「const 的检出率」
# ---------------------------------------------------------------------------

def test_sampling_is_balanced_across_operators():
    """四种算子都要出现，配额相同。

    笼统随机抽的话样本会被 `const` 淹没（AST 里字面量远多于算子），
    测出来的其实是「const 变异的检出率」，不是总体。
    """
    for name in MODULES:
        _, ms, _ = _all_for(name, cap=12)
        by = {}
        for m in ms:
            by[m.kind] = by.get(m.kind, 0) + 1
        assert len(by) >= 3, f"{name} 只有 {by} —— 算子种类太少，测不出差异"
        top = max(by.values())
        bottom = min(by.values())
        assert top - bottom <= 2, f"{name} 的算子配额不均：{by}"


def test_sampling_is_reproducible():
    """同种子两次生成必须完全一样 —— 否则别人复现不出那个检测率。"""
    for name in MODULES:
        _, a, _ = _all_for(name, cap=8)
        _, b, _ = _all_for(name, cap=8)
        assert [m.label() for m in a] == [m.label() for m in b], \
            f"{name} 同种子两次生成结果不同，记录的检测率无法复现"


def test_sampling_stays_within_cap():
    for name in MODULES:
        _, ms, _ = _all_for(name, cap=6)
        assert len(ms) <= 6, f"{name} 超出上限：{len(ms)}"


# ---------------------------------------------------------------------------
# 三、跳过的位置必须是有理由的跳过
# ---------------------------------------------------------------------------

def test_assert_statements_are_never_mutated():
    """`assert` 不许被变异 —— 改断言等于改**判据**，不是改行为。

    而"判据写错"恰恰是本项目 F 类错误之一。变异判据只会让人误以为
    测出了行为上的差别。
    """
    for name in MODULES:
        p = S / name
        src = src = p.read_bytes().decode("utf-8")
        tree = ast.parse(src)
        assert_lines = {n.lineno for n in ast.walk(tree)
                        if isinstance(n, ast.Assert)}
        _, ms, _ = _all_for(name)
        hit = [m for m in ms if m.line in assert_lines]
        assert not hit, f'{name} 变到了 assert：{[m.label() for m in hit]}'


def test_boilerplate_functions_are_skipped():
    """`main` / `__repr__` 这类函数跳过 —— 改里面的数字通常是文案。"""
    for name in MODULES:
        p = S / name
        tree = ast.parse(p.read_bytes().decode("utf-8"))
        skip_lines = {n.lineno for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name in MG.SKIP_FUNCS}
        _, ms, _ = _all_for(name)
        hit = [m for m in ms if m.line in skip_lines]
        assert not hit, f'{name} 变到了样板函数：{[m.label() for m in hit]}'


def test_generated_count_is_reported_not_silently_dropped():
    """被丢弃的语法错变异必须**报出来**，不能静默吞掉。

    丢掉本身是对的（留着会让套件 ImportError），但吞掉就等于
    「我们只测了能用的那部分」而没人知道比例是多少。
    """
    total_dropped = 0
    for name in MODULES:
        _, ms, dropped = _all_for(name, cap=400)
        total_dropped += dropped
    assert total_dropped >= 0   # 有这个返回值本身就是要求
    import inspect

    import probe_mutation as pm
    assert "丢弃" in inspect.getsource(pm.systematic), \
        "实跑时必须打印丢弃数量，否则读者不知道测的是子集"

# ---------------------------------------------------------------------------
# 四、CLI：不允许「假开关」
# ---------------------------------------------------------------------------
# 第一版 mutate_gen.py 只是个库、没有 main，于是
# `python mutate_gen.py --help` **什么都不打印、退出码还是 0**。
# 而过程门的 smoke 是**按输出内容**判的（v6.84 改的，因为它按退出码判会漏），
# 所以这种模块会**静默地**通过 smoke —— 跟 v6.83 那个「假开关」
# （显式开了却不生效、且不吭声）是同一类毛病。


def test_mutate_gen_has_a_real_cli_that_prints_something():
    """`--help` 必须真的输出用法，否则是假开关而 smoke 不会拦。"""
    import subprocess

    r = subprocess.run([sys.executable, "-m", "mutate_gen", "--help"],
                       cwd=str(S), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"--help 退出码 {r.returncode}"
    out = (r.stdout or "") + (r.stderr or "")
    assert "usage" in out.lower(), \
        f"--help 没有任何输出 —— 那是个假开关，且 smoke 不会拦它：{out[:120]}"
    assert "--cap" in out and "--show-context" in out, \
        f"用法里该有 --cap / --show-context：{out[:200]}"


def test_mutate_gen_cli_lists_mutants_without_modifying_anything():
    """CLI 只列不改 —— 列一下不该动任何文件。"""
    import hashlib
    import subprocess

    watched = [S / n for n in MODULES]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    r = subprocess.run([sys.executable, "-m", "mutate_gen", "score.py",
                        "--cap", "3"], cwd=str(S), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"退出码 {r.returncode}：{r.stderr[:200]}"
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    dirty = [p.name for p in before if before[p] != after[p]]
    assert not dirty, f"只是列一下却改了真文件：{dirty}"
    assert "score.py" in r.stdout and "丢弃" in r.stdout, \
        f"输出里应含文件名与丢弃计数：{r.stdout[:200]}"


# ---------------------------------------------------------------------------
# 五、全量复核必须按**精确偏移**重放，不能按 (line, kind) 重新匹配
# ---------------------------------------------------------------------------
# 复核的全部意义是「收窄有没有藏住失败」。第一版复核重新生成一遍变异，
# 再按 (line, kind) 找回去 —— 而同一行可能有两个同类变异：
# `a or b or c` 会生成**两个** boolop 变异，(line, kind) 一撞就取到另一个。
# 那样复核报告的「全量说 caught」说的根本不是那个存活变异，
# 而它偏偏是用来给检测率打折的。**复核自己配错对象，整份复核就作废。**


def test_survivor_recheck_records_offsets_so_it_replays_exactly():
    """结果里必须带上 start/end/repl —— 有偏移才能精确重放。"""
    import inspect

    import probe_mutation as pm

    src = inspect.getsource(pm.systematic)
    for key in ('"start"', '"end"', '"repl"'):
        assert key in src, f"存活记录里必须存 {key}，否则复核无法精确重放"
    assert "generate(scr / r[" not in src, \
        "复核不许重新生成再按 (line, kind) 匹配 —— 同一行可能有多个同类变异"

def test_same_line_can_carry_multiple_mutants_of_one_kind():
    """前提确认：同一行**确实**会出现多个同类变异。

    钉住这个前提，好让上面那条「复核不许按 (line,kind) 匹配」有据可依。

    注意我第一次猜的例子是错的：`a or b or c` 只生成 **1** 个 boolop 变异
    （那是一个 `BoolOp` 节点），不碰撞。真正碰撞的是**多个同类节点落在同一行**：

    | 写法 | 同类变异数 | 碰撞 |
    |---|---|---|
    | `a or b or c` | 1 | 无 |
    | `if a < b and c > d:` | 2 个 compare | **有** |
    | `if not a and not b:` | 2 个 not | **有** |

    「造完就信」第 N 次：按 (line,kind) 复核的**修法是对的**，
    但我给它配的**理由是错的** —— 理由错了别人就不会信这条门。
    """
    import tempfile

    import mutate_gen as mg

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "two_cmp.py"
        # 必须 write_bytes：write_text 在 Windows 上会把 `\n` 再翻成 `\r\n`，
        # 写成 `\r\r\n`，行结构就乱了（这坑我自己踩过）
        p.write_bytes(b"def f(a, b, c, d):\r\n"
                      b"    if a < b and c > d:\r\n"
                      b"        return 1\r\n")
        ms, _ = mg.generate(p, cap=99)
        key = {}
        for m in ms:
            key.setdefault((m.line, m.kind), []).append(m.start)
        dup = {k: v for k, v in key.items() if len(v) > 1}
        assert dup, (
            f'第 2 行本该有两个 compare 变异，实得 {key} —— '
            f'若将来生成器变了，这条前提测试要重新找例子，'
            f'但上面那条门依然要保留')


# ---------------------------------------------------------------------------
# 六、挂死必须单列，不能混进「抓到」
# ---------------------------------------------------------------------------
# 实测：把 verify_quotes.py:113 的 `while i != -1` 改成 `while i == -1`，
# 套件不是断言失败，而是**永远不结束**（120s 仍未结束，实跑时烧掉 2400s）。
#
# 挂死算不算「抓到」？算 —— 真实 CI 里挂死同样让流水线红。
# 但它和断言失败是两回事：断言失败说明「测试在验证这个行为」，
# 挂死只说明「这个改动让程序停不下来」。混在一起算，
# 报告就会把「没有测试断言它会终止」这件事藏起来。


def test_run_suite_distinguishes_hang_from_red():
    """run_suite 必须能区分「断言红」与「挂死」，且超时上限要合理。"""
    import inspect

    import probe_mutation as pm

    sig = inspect.signature(pm.run_suite)
    assert sig.parameters["timeout"].default <= 600, (
        f'单次套件超时 {sig.parameters["timeout"].default}s 太长：'
        f'收窄跑实测 10~50 秒，为判一个挂死烧几十分钟不成比例')

    src = inspect.getsource(pm.run_suite)
    assert "TimeoutExpired" in src, "必须捕获超时并当挂死处理，而不是让整轮崩掉"
    assert 'return "hang"' in src, '必须返回一个独立的挂死状态'


def test_hang_is_counted_separately_in_the_summary():
    """汇总里挂死要单列，不能只并进「抓到」总数。"""
    import inspect

    import probe_mutation as pm

    src = inspect.getsource(pm.systematic)
    assert '"caught(挂死)"' in src, "挂死必须有独立的判定值"
    assert "靠挂死抓到的" in src, \
        "汇总里要明确写出其中几个是靠挂死抓到的 —— " \
        "混进总数就等于把「没有测试断言它会终止」藏起来"


def test_suggest_has_no_iteration_bound_and_nothing_pins_termination():
    """`_suggest` 没有迭代上界，且没有测试断言它会终止。

    **当前代码没有 bug**：`i = norm.find(head, i + 1)` 每轮至少 +1，一定会终止。
    这条钉的是「上界缺失」这个事实 —— 有朝一日有人把 `i + 1` 写成 `i`，
    那就是真的死循环，而这一版除它以外没有任何东西拦得住。
    """
    import ast
    import inspect
    import textwrap

    import verify_quotes as vq

    src = inspect.getsource(vq._suggest)
    # 必须 textwrap.dedent：cleandoc 只去掉公共前导空白，
    # 函数体相对 def 仍然是缩进的，直接 parse 会 IndentationError
    tree = ast.parse(textwrap.dedent(src))
    whiles = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    assert whiles, "解析不到 while —— 这条测试本身失去意义"
    w = whiles[0]
    # 没有 count/break 上界：只有 find(head, i+1) 这种推进式终止
    has_bound = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("count", "__next__")
                    for n in ast.walk(w))
    assert not has_bound, \
        "看起来加了迭代上界 —— 那这条测试要改成钉「上界存在但没人测」"
    body = "\n".join(src.splitlines())
    assert "i + 1" in body, \
        "终止依赖 find(head, i+1) 的推进；若推进被去掉就是死循环"


def test_baseline_gets_a_separate_budget_from_narrowed_runs():
    """基线是**全量**（实测 260 秒），收窄是 10~50 秒 —— 预算必须分开。

    这条是被自己的 bug 逼出来的：为了「别为一个挂死烧 40 分钟」把
    `run_suite` 默认超时从 2400s 降到 300s，结果**基线全量正好要 260 秒**，
    一次 CPU 竞争就超 300s → 基线被判「挂死」→ 整轮白跑。

    修法不是把默认值调回去（那又回到 40 分钟），
    而是**按调用点给**：收窄 300s，基线/复核 1200s。
    """
    import inspect

    import probe_mutation as pm

    assert pm.BASELINE_TIMEOUT >= 600, \
        f'基线预算 {pm.BASELINE_TIMEOUT}s 太紧：副本全量实测 260 秒，' \
        f'留不出竞争余量'
    assert pm.NARROW_TIMEOUT <= 600, \
        f'收窄预算 {pm.NARROW_TIMEOUT}s 太长：收窄跑实测 10~50 秒'

    for fn in ("report", "systematic"):
        src = inspect.getsource(getattr(pm, fn))
        assert "BASELINE_TIMEOUT" in src, \
            f'{fn}() 的基线自检必须显式给预算，不能吃收窄跑的默认值'


def test_baseline_must_be_green_not_merely_truthy():
    """基线判定必须是 `!= "green"`，不能是「非空即失败」。

    `run_suite` 返回字符串后，任何「非零/真即失败」的写法都会把 `"red"`
    和 `"hang"` 混为一谈 —— 而基线挂死和基线红是两回事：
    前者是环境/超时问题，后者是工作区坏了。
    """
    import inspect

    import probe_mutation as pm

    for fn in ("report", "systematic"):
        src = inspect.getsource(getattr(pm, fn))
        assert '!= "green"' in src, \
            f'{fn}() 必须用 `!= "green"` 判基线；' \
            f'写成「非空即失败」会把 red 与 hang 混起来'
