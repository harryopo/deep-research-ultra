"""指纹守卫分级：只有被测模块的改动才算失败。

## 为什么分级

v6.89 的教训是「变异写进了真实工作区」，所以我第一版比**全树**指纹。
那次是对的 —— 一个变异探针如果默默接受「跑的过程中工作区变了」，
它就是 v6.89 事故本身。

但那个版本有个副作用：v6.93 那次实跑，我在它跑到一半时新建了
`tests/boundary_status.py`，探针在结束核对时发现工作区变了，
**拒绝出结果、退出 1** —— 87 个变异全跑完了，数字在日志里。

保守到让人不敢碰任何文件的门，是废门：我正是因为怕撞上它，
才不敢在跑的过程中写文档。

## 精确的威胁模型

`mutate_gen` **只会**变异 `BD.MODULES` 里那几个文件。所以真正必须
「一个字节都不变」的就是它们。

其余文件（测试、文档、我自己写的分析脚本）在跑的过程中变化，
对这次测量**没有任何影响**：测试跑在副本上，副本在 T0 就定好了。

于是分两级：

| 变了什么 | 判定 |
|---|---|
| `BD.MODULES` 里的文件 | **硬失败** |
| 其余任何文件 | 打印出来，不失败 |

## 这条分级不能被悄悄退回全树

见最后一项：`test_only_modules_are_hard_failures`，它读的是函数签名与
报错文案，而不是「跑一遍看看」。跑一遍要 90 分钟，门不能那么慢。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import analysis.boundaries as BD  # noqa: E402
import probe_mutation as pm  # noqa: E402


def _src() -> str:
    import inspect

    return inspect.getsource(pm.boundary_run)


def test_module_fingerprint_only_covers_the_requested_modules(tmp_path):
    """`_module_fingerprint(root, modules)` 只看给定的那几个文件。"""
    root = tmp_path / "r"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "b.py").write_text("y = 1\n", encoding="utf-8")
    (root / "c.py").write_text("z = 1\n", encoding="utf-8")

    fp = pm._module_fingerprint(root, ["a.py", "b.py"])
    assert set(fp) == {"a.py", "b.py"}, f"指纹只该含给定模块，实得 {sorted(fp)}"

    # c.py 变了不影响指纹
    (root / "c.py").write_text("z = 2\n", encoding="utf-8")
    assert pm._module_fingerprint(root, ["a.py", "b.py"]) == fp

    # a.py 变了就要变
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert pm._module_fingerprint(root, ["a.py", "b.py"]) != fp


def test_module_fingerprint_records_missing_files_as_none(tmp_path):
    """模块不存在时记 None，而不是抛异常或悄悄跳过。

    跳过的话，「这个模块没了」和「这个模块没变」就分不出来了。
    """
    root = tmp_path / "r"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    fp = pm._module_fingerprint(root, ["a.py", "gone.py"])
    assert fp["a.py"] is not None
    assert fp["gone.py"] is None, "缺失模块应记 None 而非被跳过"


def test_boundary_run_hard_fails_on_module_changes():
    """被测模块变了 -> **抛 RuntimeError**。"""
    src = _src()
    assert "broken = [" in src, "缺少「被测模块变了」的判定"
    assert "_module_fingerprint(S, modules)" in src
    assert "\u88ab\u6d4b\u6a21\u5757\u88ab\u6539\u52a8\u4e86" in src, \
        "报错文案要说清是「被测模块」被改了，而不是笼统的工作区"
    assert "RuntimeError" in src


def test_boundary_run_only_warns_about_other_changes():
    """其余文件变了 -> 打印，不抛。"""
    src = _src()
    i_warn = src.find("touched[:6]")
    assert i_warn > 0, "没有对非模块文件变化的提示"
    tail = src[i_warn:i_warn + 600]
    assert "RuntimeError" not in tail, (
        "非被测文件的变化不该导致 RuntimeError —— "
        "正是这一条让保守的门变成了「跑之前不敢碰任何文件」的废门")


def test_the_hard_check_runs_before_the_summary_is_printed():
    """硬门必须在打印汇总**之前** —— 否则数字已经印在屏幕上了。"""
    src = _src()
    i_check = src.find("broken = [")
    i_summary = src.find("\u8fb9\u754c %d" if False else "print()\n        print(\"=\" * 78)")
    assert i_check > 0, "没找到硬门判定"
    assert i_summary > 0, "没找到汇总打印"
    assert i_check < i_summary, "硬门排在汇总之后 —— 那时数字已经印出去了"


def test_strict_full_tree_check_is_not_used_in_boundary_run():
    """反向护栏：别把硬门悄悄退回全树指纹。

    全树比法存在（`_fingerprint` 仍被用于**打印**），
    但判定必须只用 `_module_fingerprint`。
    """
    src = _src()
    check = src[src.find("now_modules = _module_fingerprint"):]
    end = check.find("results = []")
    if end > 0:
        check = check[:end]
    # 「只警告」分支内部不得有 raise
    i_warn = check.find("if touched:")
    assert i_warn > 0, "没找到对非模块文件变化的提示分支"
    body = check[i_warn:i_warn + 700]
    assert "raise" not in body and "RuntimeError" not in body, (
        "非被测文件变化的分支里出现了 raise —— "
        "那会让跑的过程中不敢写任何东西")
    # 全树指纹仍应用于打印非模块变化
    assert "_fingerprint(S)" in src, "全树指纹应仍用于打印非模块变化（有用）"
    assert "real_modules" in src and "now_modules" in src


def test_every_module_in_boundary_run_comes_from_the_module_list():
    """硬门比对的模块集合，必须与实际参与变异的是同一批。"""
    import inspect

    src = inspect.getsource(pm.boundary_run)
    assert "_module_fingerprint(S, modules)" in src, (
        "硬门必须比 modules（--only/--skip 收窄后的那批），"
        "而不是 BD.MODULES 全量 —— 否则 --only 的运行也会被没收窄的模块误伤")
    assert "modules = _pick_modules(list(BD.MODULES)" in src


def test_modules_list_exists_before_the_fingerprint_is_taken():
    """`modules` 必须先算出来再取指纹 —— 顺序反了会 NameError。"""
    import inspect

    src = inspect.getsource(pm.boundary_run)
    i_pick = src.find("modules = _pick_modules(")
    i_fp = src.find("real_modules = _module_fingerprint(S, modules)")
    assert i_pick > 0 and i_fp > 0
    assert i_pick < i_fp, "取指纹早于选定模块 —— 顺序反了"


def test_bd_modules_is_the_real_mutation_target_set():
    """反向对照：`mutate_gen` 只会碰 BD.MODULES 里的文件。

    这是「只把 BD.MODULES 当硬门」这个设计的**前提**。
    哪天 mutate_gen 改成能变异别的文件，这条会先红。
    """
    assert set(BD.MODULES) == {
        "score.py", "verify_quotes.py", "research.py",
        "ledger.py", "tier.py", "validate_report.py",
    }, f"BD.MODULES 变了：{sorted(BD.MODULES)}"
    for name in BD.MODULES:
        assert (pm.S / name).is_file(), f"{name} 不在 scripts/ 下"


# ==========================================================================
# 两个模式必须对称
# ==========================================================================
# v6.89 的本质不是「我写错了」，而是**一道门修了、它的兄弟没修**：
# `boundary_run` 里 `mutate_gen.generate(S / f)` 把变异写进了真实工作区，
# 而同一文件里的 `systematic` 一直是 `scr / f`（对的）。
# 于是事后 `boundary_run` 加了三道防线，`systematic` 一道也没有 ——
# **它离同样的事故只差一次改动的距离，而没有任何东西会告诉我。**
#
# 下面这几项把「对称」变成门：任何一边少一道，另一边立刻红。

MODES = ("systematic", "boundary_run")


def _src_of(name):
    import inspect

    return inspect.getsource(getattr(pm, name))


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_asserts_the_mutation_target_is_under_the_copy(mode):
    """每个模式在写盘前都要断言目标在副本下。"""
    # ⚠️ **必须按代码行判定，不能用 `src.index(...)`**。
    # 我第一版用 index() 比位置，而 `p.write_bytes(m.apply(data))` 这段文本
    # 在 boundary_run 的**文档串注释里也出现过** —— index() 命中的是那句注释，
    # 于是我得出「断言排在写盘之后」的**错结论**，并据此又插了一条重复断言。
    # **全文搜索分不清代码与说明文字**，而这类错会一路伪装成真实发现。
    lines = _src_of(mode).splitlines()
    i_write = next(n for n, l in enumerate(lines)
                   if l.strip().startswith("p.write_bytes(m.apply"))
    i_assert = next((n for n, l in enumerate(lines)
                     if l.strip().startswith("assert _is_under")), None)
    assert i_assert is not None, f"{mode} 没有 _is_under 断言"
    assert i_assert < i_write, (
        f"{mode} 的断言排在写盘之后（第 {i_assert + 1} 行 vs 第 {i_write + 1} 行）"
        f" —— 那只能发现、不能阻止")


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_takes_a_module_fingerprint_before_and_after(mode):
    """每个模式都要跑前留、跑后比。"""
    src = _src_of(mode)
    assert "real_modules = _module_fingerprint(" in src, f"{mode} 跑前没留模块指纹"
    assert "now_modules = _module_fingerprint(" in src, f"{mode} 跑后没核对"
    assert "broken = [" in src, f"{mode} 没算出「被测模块里哪些变了」"
    assert "\u88ab\u6d4b\u6a21\u5757\u88ab\u6539\u52a8\u4e86" in src, \
        f"{mode} 的报错文案要说清是「被测模块」"


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_raises_before_printing_its_summary(mode):
    """硬门必须排在汇总打印之前，否则数字已经印出去了。"""
    lines = _src_of(mode).splitlines()
    i_raise = next(n for n, l in enumerate(lines)
                   if l.strip().startswith("broken = ["))
    # 汇总段：任何一条 "=" * N 的分隔线
    # 汇总段：`print("=" * N)` 那一行（不写正则 —— raw string 里的
    # 反斜杠转义很容易写成 `\\d` 而匹配不到，那正是我第一版栽的地方）
    i_sum = next(n for n, l in enumerate(lines)
                 if '"=" *' in l and l.strip().startswith("print"))
    assert i_raise < i_sum, (
        f"{mode} 的硬门排在汇总之后（第 {i_raise + 1} 行 vs 第 {i_sum + 1} 行）"
        f" —— 那时数字已经印出去了")


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_only_warns_about_non_module_changes(mode):
    """非被测文件的变化只打印、不抛 —— 否则门会挡路。"""
    src = _src_of(mode)
    i_warn = src.index("if touched:")
    body = src[i_warn:i_warn + 700]
    assert "raise" not in body, f"{mode} 把非模块变化也当成失败了"


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_generates_mutants_from_the_copy_path(mode):
    """变异对象必须来自 `scr / f` —— `Mutant.path` 跟着走，它决定写到哪儿。"""
    src = _src_of(mode)
    assert "p = scr / f" in src or "cp = scr / f" in src, \
        f"{mode} 不是从副本路径取变异"
    assert "mutate_gen.generate(S /" not in src, \
        f"{mode} 从**真实路径**取变异 —— 这就是 v6.89 的根因"
    assert "mutate_gen.generate(p, cap=cap)" in src or \
           "mutate_gen.generate(cp, cap=10 ** 6)" in src, \
        f"{mode} 的生成调用不见了"


def test_systematic_mutates_only_the_files_it_declares():
    """`systematic` 的硬门要比它**实际变异的那几个文件**，而不是 BD.MODULES 全量。

    否则 --systematic 跑 4 个文件，硬门却查 6 个，
    没变异的那两个被别人改一下就会误报失败。
    """
    import inspect

    src = inspect.getsource(pm.systematic)
    assert "real_modules = _module_fingerprint(S, files)" in src, \
        "systematic 的硬门必须比 files（它实际变异的那批）"
    assert "now_modules = _module_fingerprint(S, files)" in src
    # files 默认是 4 个模块，不是 BD.MODULES 的 6 个
    assert "tier.py" not in inspect.signature(pm.systematic).parameters["files"].default, \
        "systematic 默认不该变异 tier.py（边界模式才变异它）"
