# -*- coding: utf-8 -*-
"""v6.100.1：修一个**我自己刚犯的、和 v6.97 一模一样**的错，并钉住它。

## 事情是这样的

v6.100.0 我给 `preflight.py` 加了 `check_metadata()`，其中一条判据是
「`SKILL.md` 的 `version:` 必须在 CHANGELOG 里有对应版本段」。

装到宿主 skill 目录之后跑，**红了**：
`[FAIL] SKILL.md 的 version=6.88.0 在 CHANGELOG 里有版本段 找不到 ## v6.88.0`

原因和 v6.97 修掉的 `provenance` 缺陷**是同一个**：
我把「CHANGELOG 不存在」只当了一种情况（文件被删了），
而实际有两种 —— **用户安装的位置正落在第二种**：

| | `REPO = SKILL.parents[1]` 指向 | CHANGELOG | `.git` |
|---|---|---|---|
| 包布局 | 包根 | **在** | 无 |
| 安装布局 | 共享 skills 池（实测 `~/.trae-cn`） | **不在** | 无 |
| 仓库 | 仓库根 | 在 | 在 |

**包内绿、安装位红。**

## 为什么没被更早抓到

因为**我只在包布局里验证**。包布局下 `REPO` 恰好等于包根，
CHANGELOG 就在那儿，所以包内全绿 —— 一切都对，直到真的装上去。

> **「包内绿」不等于「装上去能用」。** 这两处的 `REPO` 指向完全不同的东西，
> 而只验前者是我一直以来默认的做法。

所以除了修判据，还改了工具：`package_release.py` 现在除了验包内，
还把 skill 单独拷进一个**空技能池**，在**安装布局**里再跑一遍 `preflight.py`
与 `evals/run_evals.py`。不这么做的话，下一次同样的错还会溜过去。

## 这个错的形状值得记住

v6.97 修过一次（provenance），v6.100.0 又犯了一次（metadata），
**间隔三个版本、同一句话**。这说明它不是「我忘了」，而是
「写新检查时没有把 v6.97 那条教训带过来」。所以这里除了修，
还要有一条测试在**每次**检查里问同一个问题：

    这道门在**非仓库检出**的位置会怎么样？

判据取 `.git` 在不在，不取「文件在不在」—— 否则删掉仓库里的 CHANGELOG
也能骗过它，而那正是 v6.97 已经钉过的教训。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

import preflight as P  # noqa: E402


def _fake(tmp_path, *, checkout=True, skill_version="6.88.0", changelog=True,
          good_evals=True):
    """造假仓库（checkout=True）或假技能池（checkout=False）。"""
    root = tmp_path / ("repo" if checkout else "pool")
    skill = root / "skills" / "deep-research-ultra"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: x\nversion: %s\n---\n" % skill_version, encoding="utf-8")
    if checkout:
        (root / ".git").mkdir()
    if changelog:
        (root / "CHANGELOG.md").write_text(
            "# CHANGELOG\n\n## v6.88.0\n\n内容\n\n## v6.99.0\n\n内容\n",
            encoding="utf-8")
    spec = {"version": "6.5.0", "last_updated": "2026-09-18",
            "evals": [{"id": "dr-001", "name": "A", "expected_behavior": ["x"]}]}
    if not good_evals:
        spec["evals"] = [{"id": "dr-001", "name": "A"},
                          {"id": "dr-001", "name": "B", "expected_behavior": ["y"]}]
    (skill / "evals" / "evals.json").write_text(
        json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return root, skill


def _run(root, skill, capsys):
    old = (P.REPO, P.SKILL)
    P.REPO, P.SKILL = root, skill
    try:
        ok = P.check_metadata()
    finally:
        P.REPO, P.SKILL = old
    return ok, capsys.readouterr().out


# ---------------------------------------------------------------- 仓库检出

def test_checkout_with_matching_changelog_passes(tmp_path, capsys):
    root, skill = _fake(tmp_path)
    ok, out = _run(root, skill, capsys)
    assert ok, "一致的仓库检出应该通过：\n%s" % out[-500:]


def test_checkout_without_changelog_goes_red(tmp_path, capsys):
    """仓库检出里 CHANGELOG 被删了 —— 真的坏了，必须红。"""
    root, skill = _fake(tmp_path, checkout=True, changelog=False)
    ok, out = _run(root, skill, capsys)
    assert not ok, "仓库检出里 CHANGELOG 不见了却判通过"
    assert "不适用" not in out, (
        "检出里缺文件属于坏了，不能印成「不适用」——两者含义完全不同")


def test_checkout_with_unlisted_skill_version_goes_red(tmp_path, capsys):
    root, skill = _fake(tmp_path, checkout=True, skill_version="9.99.9")
    ok, out = _run(root, skill, capsys)
    assert not ok, "SKILL.md 写 9.99.9 而 CHANGELOG 里没有它，仍判通过"
    assert "9.99.9" in out


# ---------------------------------------------------------------- 安装布局

def test_install_layout_without_changelog_is_not_a_failure(tmp_path, capsys):
    """⚠️ 这条钉的就是 v6.100.0 的那个真事故。

    安装布局：没有 CHANGELOG、没有 `.git`。这道门必须**不适用**，而不是红。
    一个永远红的门等于没有门，还会教 agent 学会忽略红色。
    """
    root, skill = _fake(tmp_path, checkout=False, changelog=False)
    ok, out = _run(root, skill, capsys)
    assert ok, (
        "安装布局（无 CHANGELOG、无 .git）被判成红了 —— "
        "这正是装到宿主之后每次交付都撞上的那个。\n%s" % out[-600:])
    assert "[ -- ]" in out and "不适用" in out, (
        "跳过必须打印出来并说明不适用；跳过不是通过。\n%s" % out[-600:])
    assert "FAIL" not in out, (
        "安装布局下不该出现 FAIL：\n%s" % out[-600:])


def test_install_layout_still_runs_the_evals_json_check(tmp_path, capsys):
    """跳过的是「查 CHANGELOG」，不是整条 metadata。

    `evals.json` 的结构核对照跑 —— 它只依赖 SKILL 相对路径，处处成立。
    """
    root, skill = _fake(tmp_path, checkout=False, changelog=False)
    _ok, out = _run(root, skill, capsys)
    assert "evals.json 每条评测结构完整且 id 唯一" in out, (
        "evals.json 结构核对被一起跳过了：\n%s" % out[-500:])
    assert "[OK  ]" in out, "evals.json 那条应当照常判：\n%s" % out[-500:]


def test_install_layout_still_goes_red_on_broken_evals_json(tmp_path, capsys):
    """安装布局下，evals.json 结构坏了**照样红** —— 不能借「跳过」把真问题一起放过去。"""
    root, skill = _fake(tmp_path, checkout=False, changelog=False,
                        good_evals=False)
    ok, out = _run(root, skill, capsys)
    assert not ok, (
        "安装布局下 evals.json 有重复 id 却判通过 —— "
        "「CHANGELOG 不适用」不该把 evals.json 的核对一起放过去")


def test_the_criterion_is_git_not_changelog_presence(tmp_path, capsys):
    """证伪主测试：同样没有 CHANGELOG，只差一个空的 `.git/`，结论必须相反。

    没有这一条，一个「CHANGELOG 不在就跳过」的实现能同时满足上面几条 ——
    仓库里删掉 CHANGELOG 也能骗过这道门，而那正是 v6.97 已钉过的教训。
    """
    a_root, a_skill = _fake(tmp_path / "a", checkout=False, changelog=False)
    b_root, b_skill = _fake(tmp_path / "b", checkout=True, changelog=False)
    ok_a, out_a = _run(a_root, a_skill, capsys)
    ok_b, out_b = _run(b_root, b_skill, capsys)

    assert ok_a is True and ok_b is False, (
        "两个环境应当得出相反结论（无 .git→不适用 / 有 .git→红），"
        "实际 got %s / %s。结论相同说明 `.git` 这个判据没起作用。" % (ok_a, ok_b))
    assert ("不适用" in out_a) != ("不适用" in out_b), \
        "只有非检出那份该印「不适用」"