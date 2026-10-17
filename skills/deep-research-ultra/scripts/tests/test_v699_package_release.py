# -*- coding: utf-8 -*-
"""v6.99：打包工具的 skip 对账必须**会红** —— 它曾经是本项目最贵的一个假绿灯。

## 事情的经过

`package_release.py` 的每一版都住在 TEMP 里，于是每一版都自带同一个 bug：
按 `"SKIP "`（带空格）去匹配 `pytest -rs` 印的 `SKIPPED [1] …`，
一个都匹配不上 ⇒ 抓到 0 条 ⇒ **判成「没有异常 skip」通过**，
而同一屏的 `run_all_tests.py` 明明写着 `6 skipped`。

它一共存在了三个版本我才抓到。而且抓到它的是**我自己的另一个脚本**
（那个脚本用了正确的过滤）—— 也就是说：**如果我不顺手写第二个脚本，
这个假绿灯会一直留在打包流程里。**

## 为什么钉这三条规则，而不是钉「输出长这样」

`reconcile_skips()` 现在有三条硬规则：

1. 匹配 `SKIPPED`，剥掉 `[n] path:line: ` 前缀
2. **空集合直接判有问题** —— 它与两处汇总数字矛盾就是矛盾
3. 逐条抓到的条数必须等于 `run_all_tests.py` 报的数字（两处独立来源）

第 2 条是最要紧的：**「没抓到」必须被当成问题，不能被当成「没问题」**。
这条对所有过滤器都成立，不只是这个函数。
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

import package_release as PR  # noqa: E402


def _rs_output(lines):
    """拼一份形状真实的 `pytest -q -rs` 尾部输出。"""
    head = [".F..", ""]
    tail = ["=========================== short test summary info ==========================="]
    tail += ["SKIPPED [1] %s" % l for l in lines]
    tail += ["", "1 passed, %d skipped in 12.34s (0:00:12)" % len(lines)]
    return "\n".join(head + tail)


OK_SKIPS = [
    r"skills\deep-research-ultra\scripts\tests\test_v6223_mcp_config_writer.py:121: "
    r"本机无 bash（Windows）：setup-mcp.sh 是 bash 脚本，此环境跑不了",
    r"skills\deep-research-ultra\scripts\tests\test_v687_mutation_probe.py:179: "
    r"需要 git 检出（探针靠 git archive 造副本）；变异副本里没有 .git",
    r"skills\deep-research-ultra\scripts\tests\test_v688_boundary_pins.py:304: "
    r"还没跑过 probe_mutation.py --systematic",
]


def test_reconcile_accepts_the_real_thing():
    """形状真实的 3 条 skip、且都在白名单里 → 不该报任何问题。"""
    reasons, problems = PR.reconcile_skips(_rs_output(OK_SKIPS), claimed=3)
    assert len(reasons) == 3, "逐条抓到的条数不对：%r" % reasons
    assert not problems, "不该报问题，却报了：%s" % problems


def test_prefix_is_stripped_so_the_reason_is_readable():
    """`[1] path:line: ` 前缀必须被剥掉 —— 否则白名单匹配的是整行路径，判不出来。"""
    reasons, problems = PR.reconcile_skips(_rs_output(OK_SKIPS), claimed=3)
    assert all(not r.startswith("SKIPPED") for r in reasons), reasons
    assert all("[1]" not in r for r in reasons), reasons
    assert not problems, problems


# ---------------------------------------------------------------- 三条硬规则

def test_empty_match_is_a_problem_not_a_pass():
    """⚠️ 这条就是那个假绿灯本身。

    汇总行说 3 条 skipped，但输出里**一条都匹配不到** ——
    必须判有问题。曾经它被判成「没有异常 skip」而 exit 0。
    """
    out = "…\n1 passed, 3 skipped in 12.34s (0:00:12)\n"
    reasons, problems = PR.reconcile_skips(out, claimed=3)
    assert reasons == [], "本该抓到 0 条（输入里确实没有 SKIPPED 行）"
    assert problems, (
        "一条 SKIPPED 都匹配不到，却判成通过 —— "
        "「没抓到」被当成了「没有问题」。这正是打包脚本里那个假绿灯。")


def test_skip_summary_matching_bug_is_pinned():
    """钉住**匹配的是 `SKIPPED` 而不是 `SKIP `**。

    输入用 `SKIPPED`，如果实现退回成 `startswith('SKIP ')`，
    这条会立刻红 —— 不需要等到某次打包才发现。
    """
    out = _rs_output(OK_SKIPS)
    assert "SKIPPED [1]" in out
    reasons, problems = PR.reconcile_skips(out, claimed=3)
    assert len(reasons) == 3 and not problems, (
        "实现没匹配上 pytest 印的 SKIPPED：抓到 %d 条，问题 %s"
        % (len(reasons), problems))


def test_count_disagreement_with_run_all_tests_is_a_problem():
    """两处独立来源（pytest 汇总 / run_all_tests）不一致 ⇒ 判有问题。"""
    out = _rs_output(OK_SKIPS)          # 汇总说 3
    _reasons, problems = PR.reconcile_skips(out, claimed=4)   # run_all_tests 说 4
    assert any("来源不一致" in p for p in problems), (
        "两处来源的数字对不上却判通过：%s" % problems)


def test_unknown_skip_reason_is_a_problem():
    """白名单之外的 skip 理由 = 可能真的是缺文件，必须报出来。"""
    reasons = OK_SKIPS + [
        r"skills\deep-research-ultra\scripts\tests\test_x.py:9: "
        r"找不到数据文件 fixtures/sample.json",
    ]
    _r, problems = PR.reconcile_skips(_rs_output(reasons), claimed=4)
    assert any("无法解释" in p for p in problems), (
        "白名单之外的 skip 没有被报出来：%s" % problems)


# ---------------------------------------------------------------- 工具本身

def test_help_exits_zero():
    """过程门的 smoke 会对 scripts/ 下每个脚本跑 `--help`，这里死了门会红。"""
    r = subprocess.run([sys.executable, str(PR.__file__), "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    assert r.returncode == 0, "--help 崩了：\n%s" % (r.stderr or "")[-400:]
    assert "--version" in (r.stdout or ""), "--help 里没有 --version"


def test_must_have_lists_files_that_actually_exist():
    """MUST_HAVE 里写错路径 = 每次打包都报一个假「缺失」。

    ⚠️ 基准是**仓库根**不是 skill 目录：第一版我用 `PR.SKILL` 当基准，
    于是 11 条全部报「不存在」——测试自己红，还报得一本正经。
    """
    missing = [f for f in PR.MUST_HAVE if not (PR.REPO / f).exists()]
    assert not missing, (
        "MUST_HAVE 里有 %d 个路径在仓库里不存在，打包时会一直报假缺失：%s"
        % (len(missing), missing))
    assert len(PR.MUST_HAVE) >= 10, (
        "MUST_HAVE 只列了 %d 个文件，太少了 —— 包里少东西是这类产物最常见的事故"
        % len(PR.MUST_HAVE))


def test_key_fix_marks_point_at_the_right_file():
    """每项关键修复都要指明查哪个文件，且那个文件要真的存在。

    第一版三项全查 `preflight.py`，而 `PARTIAL_NOTES` 在 `evals/run_evals.py` ——
    于是工具报「包内缺 v6.98 的修复」，而包里明明有。
    **一个报错的检查比没有检查更坏**：它会让你去修一个没坏的东西。

    这里刻意**不扫源码文本**：上一版断言 `"need_marks = [" in src`，
    我把变量改名成 `NEED_MARKS` 之后它就红了 —— **断言在赌字符串**。
    判结构（是三元组、文件存在、needle 非空）而不是判写法。
    """
    assert isinstance(PR.NEED_MARKS, list) and len(PR.NEED_MARKS) >= 3, (
        "NEED_MARKS 应该是逐项带文件名的列表，实得 %r" % type(PR.NEED_MARKS))
    for item in PR.NEED_MARKS:
        assert isinstance(item, tuple) and len(item) == 3, (
            "NEED_MARKS 的每项应是 (文件, 说明, 查找串) 三元组，实得 %r" % (item,))
        rel, what, needle = item
        assert (PR.REPO / rel).exists(), (
            "关键修复检查指向了不存在的文件 %s —— 那个检查会永远报缺失（%s）" % (rel, what))
        assert needle.strip(), "%s 的查找串是空的，等于没检查" % what


def test_module_is_importable_without_side_effects():
    m = importlib.import_module("package_release")
    assert callable(m.build) and callable(m.reconcile_skips)