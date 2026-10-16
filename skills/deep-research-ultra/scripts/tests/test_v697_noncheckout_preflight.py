# -*- coding: utf-8 -*-
"""v6.97：过程门在「不是仓库检出」的位置（也就是**用户实际安装的位置**）必须能过。

## 起因是一次真实的安装，不是设想

把 v7.5.0 装到 Trae 的 skill 目录之后，交付前要跑的那道门是红的：

    [FAIL] v6.83.0 在 CHANGELOG 里有条目  找不到该版本段
    [FAIL] v6.86.0 ...  [FAIL] v6.88.0 ...  [FAIL] v6.95.0 ...  [FAIL] v6.96.0 ...

原因很直白：`install.py` 只拷 `skills/deep-research-ultra/`，
**CHANGELOG.md 留在仓库根**，不在安装位里。而 `SKILL.md` 明写
「交付前跑一次 preflight.py」——于是每次交付都红。

一个永远红的门等于没有门，而且更坏：它教 agent 学会忽略红色。

## 为什么「不适用」和「通过」必须分开印

`PROVENANCE` 登记了 5 个版本段要能在 CHANGELOG 里找到。安装位没有 CHANGELOG，
**这件事无从核对**。把它算成「通过」是撒谎（那是本项目反复吃过的亏：
「没跑的绝不计为通过」）；把它算成 FAIL 同样是撒谎（不是它坏了，是输入不存在）。
所以输出用 `[ -- ]` 明说不适用，并且把「跳过不是通过」写在脸上。

## 这三个用例合起来才是证伪

单独看前两个都可能被「把检查删掉」的假修复骗过：
删掉整个 provenance 分支，第一个也会变绿、第二个会变红——**两个都在**才排除不了。
真正能排除假修复的是第三个：**同一套环境，只多一个空的 `.git/`，结论必须不同。**

- 删掉检查的实现 → 用例 3 也会同向变绿/变红 → 抓住
- 把「不适用」写成「通过」→ 用例 2 断言输出里必须有 `[ -- ]` → 抓住
- 只判文件在不在、不看 .git → 用例 3 抓住（仓库里删掉 CHANGELOG 能骗过门）
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

import preflight  # noqa: E402


def _provenance_with_repo(tmp_repo: Path, capsys):
    """把 preflight 的 REPO 指到临时目录，跑一次 check_provenance，返回 (ok, 输出)。"""
    old = preflight.REPO
    preflight.REPO = tmp_repo
    try:
        ok = preflight.check_provenance()
    finally:
        preflight.REPO = old
    return ok, capsys.readouterr().out


# ---------------------------------------------------------------------------
# 1) 用户实际会遇到的那个位置：非仓库检出 + 无 CHANGELOG → 不适用，不是红
# ---------------------------------------------------------------------------

def test_provenance_outside_checkout_is_not_a_failure(tmp_path, capsys):
    """安装位的形态：没有 .git，也没有 CHANGELOG。门必须放行。"""
    (tmp_path / "skills").mkdir()          # 装出来就是这个形状：有 skills/，没 .git
    ok, out = _provenance_with_repo(tmp_path, capsys)

    assert ok is True, (
        "非仓库检出（用户安装位）被判成红了 —— 真实安装时每次交付都会撞上这个。\n"
        f"输出：\n{out[-900:]}")
    assert "[ -- ]" in out and "不适用" in out, (
        "跳过必须打印出来，且不能算成通过："
        f"否则就是「没跑却记成通过」。\n输出：\n{out[-900:]}")
    assert "跳过不是通过" in out, \
        "输出里要明说「跳过不是通过」——本项目吃过「没跑却算通过」的亏"


def test_provenance_outside_checkout_still_runs_the_analysis_reconciliation(tmp_path, capsys):
    """跳过的是「查 CHANGELOG」，不是整条 provenance。

    analysis/ 里三个 `--check` 脚本随安装包分发、也真能跑 ——
    跳过它们等于把一份还能做的核对白扔了。
    """
    ok, out = _provenance_with_repo(tmp_path, capsys)
    for name in ("boundaries.py", "holdout.py", "relevance.py"):
        assert f"{name} --check 通过" in out, \
            f"{name} 的自证没跑（它随安装包分发，不该被一起跳过）\n输出：\n{out[-900:]}"
    assert ok is True


# ---------------------------------------------------------------------------
# 2) 判据是「有没有 .git」，不是「有没有 CHANGELOG」
# ---------------------------------------------------------------------------

def test_provenance_still_fails_in_a_checkout_whose_changelog_vanished(tmp_path, capsys):
    """仓库检出里 CHANGELOG 被删了 —— 这是真的坏了，必须红。

    这是本次修改最容易被做坏的地方：如果实现成
    「CHANGELOG 不存在就跳过」，那么**有人在仓库里删掉 CHANGELOG 也能骗过这道门**。
    """
    (tmp_path / ".git").mkdir()           # 关键：只多这一个
    ok, out = _provenance_with_repo(tmp_path, capsys)

    assert ok is False, (
        "仓库检出里 CHANGELOG 不见了还放行 —— 门被做成了"
        "「CHANGELOG 不在就跳过」，删文件就能骗过它。\n输出：\n{out[-900:]}")
    assert "文件不见了" in out, \
        f"要报的是「文件不见了」，不是「不适用」——两者含义完全不同。\n输出：\n{out[-900:]}"
    assert "不适用" not in out, \
        "检出里缺文件属于坏了，不能印成「不适用」"


def test_checkout_and_noncheckout_actually_take_different_paths(tmp_path, capsys):
    """证伪主测试：同一套东西，只差一个空的 `.git/`，结论必须相反。

    没有这一条，前两条都可能被「把 provenance 整段删掉」的假修复同时满足。
    """
    plain = tmp_path / "plain"
    plain.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    # 两边都没有 CHANGELOG.md，唯一的差别就是那一个空目录
    ok_plain, out_plain = _provenance_with_repo(plain, capsys)
    ok_checkout, out_checkout = _provenance_with_repo(checkout, capsys)

    assert (ok_plain, ok_checkout) == (True, False), (
        f"两个环境应当得出相反结论，实际 plain={ok_plain} checkout={ok_checkout}。"
        "结论相同说明 `.git` 这个判据根本没起作用。")
    assert ("不适用" in out_plain) != ("不适用" in out_checkout), \
        "只有非检出那份该印「不适用」"


# ---------------------------------------------------------------------------
# 3) 仓库里那条正常路径没被改坏
# ---------------------------------------------------------------------------

def test_repo_checkout_still_verifies_every_registered_section(capsys):
    """真正的仓库里，PROVENANCE 登记的每个版本段仍然必须逐条核对。

    这次改动给 PROVENANCE 循环套了一层 `if text is not None`，
    所以必须钉住「在仓库里它照旧逐条核对」——
    否则「整段被套进 if 里、仓库里也不再核对了」也能让上面两条变绿。
    """
    # 用模块自己的 REPO，不手写 parents[n]。
    # 手写层数就是 v6.84 那次 bug 的成因（parents[2] 指到了 <repo>/skills），
    # 而它第一次跑就报「找不到 CHANGELOG 的版本段」，报错指向数据、实际是路径。
    repo = preflight.REPO
    ok, out = _provenance_with_repo(repo, capsys)
    assert ok is True, f"真仓库里 provenance 没过：\n{out[-900:]}"
    for ver in preflight.PROVENANCE:
        assert f"{ver} 的复算脚本已入库" in out, \
            f"登记的 {ver} 没有被核对 —— 套 if 那层可能把这条路径也跳过了"
    assert "[ -- ]" not in out, "真仓库里有 CHANGELOG，不该印「不适用」"


def test_module_still_importable_after_edit():
    """这条改的是运行时代码路径；先确认模块本身没被改坏。"""
    m = importlib.import_module("preflight")
    assert callable(m.check_provenance)


# ---------------------------------------------------------------------------
# 4) 门自己不许崩：子进程崩了要报 FAIL，不是抛 IndexError
# ---------------------------------------------------------------------------
#
# 这条是在证伪 v6.97 那批测试时**撞出来的**，不是设计出来的。
# 现象：preflight.py 里
#     (r.stdout or "").strip().splitlines()[-1][:70]
# 在子进程「非零退出 + stdout 为空」时抛 IndexError —— 而那正是**脚本自己崩了**
# 时最常见的样子（Python 把 traceback 写 stderr、stdout 空）。
# 结果是：**子进程崩 → 门也跟着崩**，崩的还是 traceback 而不是 FAIL。
#
# 为什么要用打桩而不是真的造一个崩脚本：
# 真造过一次（把 preflight 退回成修复前的样子），但它 12 次里只出现 1 次，
# 成因至今未定（见 HANDOFF v6.97）。拿一个自己都说不清成因的条件当测试判据，
# 等于把测试建在流沙上。所以这里钉的是**判据本身**：
# 给一个「非零退出 + 空 stdout」的子进程，门必须报 FAIL 而不是抛异常。


def test_last_line_never_raises_on_empty_output():
    """兜底函数本身的边界：空、空行、全空、正常，四种都得给得出东西。"""
    from preflight import _last_line
    assert _last_line("") == ""
    assert _last_line(None or "") == ""
    assert _last_line("\n\n\n") == "", "只有空行时也算没有内容"
    assert _last_line("a\nb\nc") == "c", "取最后一行"
    assert _last_line("  x  \n\n  y  \n") == "y", "空行不算内容"
    assert _last_line("z" * 200) != "" and len(_last_line("z" * 200)) == 70, \
        "超长行要截断，否则一行能把门刷爆"


def test_gate_reports_fail_instead_of_crashing_when_child_dies_silently(monkeypatch, capsys):
    """子进程非零退出且 stdout 为空 → 门必须返回 False 并印出 FAIL，不能抛。"""
    import subprocess as sp
    from types import SimpleNamespace

    def fake_run(*a, **kw):
        # 真的崩溃现场：traceback 在 stderr，stdout 一个字节都没有
        return sp.CompletedProcess(args=a[0] if a else [], returncode=1,
                                   stdout="", stderr="Traceback ...\nValueError: 炸了")

    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(
        run=fake_run, PIPE=sp.PIPE))
    ok, out = _provenance_with_repo(preflight.REPO, capsys)

    assert ok is False, "子进程全挂，这道门必须判失败"
    assert "FAIL" in out, f"要印 FAIL，实际输出：\n{out[-600:]}"
    assert "炸了" in out, \
        f"失败原因要露出来（traceback 在 stderr 就该引它）：\n{out[-600:]}"


def test_no_unguarded_last_line_indexing_left_in_source():
    """源码里不许再有裸的 `splitlines()[-1]`。

    这是元测试：上面两条测的是行为，这条钉住「别再写回来」。
    它的必要性在于 —— 那个越界点**不止一处**（analysis 对账、evals 那一阶检查，
    而实跑时又冒出第三处），修一处忘一处的话，下面两条测试仍然全绿。

    用 AST 而不是文本匹配：`_last_line` 的文档字符串里**故意引了那个越界表达式**
    当例子，文本匹配会把说明文字当成代码，一行就误报。
    真正要判的是「有没有 `x.splitlines()[-1]` 这种取最后一个元素的写法」——
    这是语法结构，AST 看得见，字符串看不见。
    """
    import ast

    tree = ast.parse(Path(preflight.__file__).read_text(encoding="utf-8"))
    risky = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.UnaryOp)):
            continue
        if not isinstance(node.slice.op, ast.USub):
            continue
        inner = node.slice.operand
        if not (isinstance(inner, ast.Constant) and isinstance(inner.value, int)):
            continue
        val = node.value
        is_splitlines = (isinstance(val, ast.Call)
                         and isinstance(val.func, ast.Attribute)
                         and val.func.attr == "splitlines")
        if is_splitlines:
            risky.append(node.lineno)
    assert not risky, (
        "这些行还会越界（子进程空输出时门自己崩），改用 _last_line()：L%s"
        % ", L".join(str(n) for n in sorted(risky)))