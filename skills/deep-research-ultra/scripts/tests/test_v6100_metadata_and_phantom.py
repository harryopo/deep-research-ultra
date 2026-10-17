# -*- coding: utf-8 -*-
"""v6.100：两件新东西各自会红的证明。

## 第一件：`run_evals.py` 判一个 evals.json 里**不存在**的条目

第一版只在标题里印一句「（评测文件里没有这一条！）」，然后照跑判据、
照常计入「机械判定 N/M」—— 也就是说：**从 evals.json 里删掉一条评测，
判定器会继续判它，并且把它算成通过。**

方向和「没跑的绝不计为通过」相反，但同一条道理：
**连判据的依据都没了，还判它通过。**

## 第二件：`check_metadata()` —— 声明的元数据不许在骗人

起因是打包时撞见的缺口：`SKILL.md` 的 `version:` 与 CHANGELOG 的版本序列
**之间没有任何门核对**。打出包那天我才看见 CHANGELOG 已到 v6.96、
SKILL.md 仍写 6.88.0 —— 单看每一边都自洽，合起来没人保证对得上。

三条判据里最要紧的是**第三条故意不判红**：`evals.json` 声明的版本
落后 94 个中版本，但规格内容确实没变过。给它设门会逼着人改一个准确的数字 ——
**保守到逼人造假的门比没门更坏**。所以这条钉死「只打印」，
免得有人日后悄悄把它变成会红的门。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))
if str(S / "evals") not in sys.path:
    sys.path.insert(0, str(S / "evals"))

import preflight as P          # noqa: E402
import run_evals as R          # noqa: E402


# =========================================================== 幽灵评测

def test_every_registered_eval_id_really_exists_in_evals_json():
    """前提：注册表里的每个 id 都在 evals.json 里。"""
    spec = json.loads(R.EVALS_JSON.read_text(encoding="utf-8"))
    ids = {e["id"] for e in spec["evals"]}
    ghost = [k for k in R.CHECKS if k not in ids]
    assert not ghost, (
        "注册表里有 evals.json 中不存在的条目：%s —— 它们会被判、"
        "而且会被算成通过" % ghost)


def test_phantom_eval_is_judged_failed_not_printed_and_counted(capsys):
    """把注册表塞一个不存在的 id，`main()` 必须 exit 1 并印出 FAIL。"""
    real = R.CHECKS
    R.CHECKS = {
        "dr-999": [("随便一个判据", lambda: (True, "通过"))],
        "dr-024": real["dr-024"],
    }
    try:
        rc = R.main()
        out = capsys.readouterr().out
    finally:
        R.CHECKS = real

    assert rc == 1, (
        "注册了一个 evals.json 里不存在的条目，判定器仍然 exit 0 —— "
        "「连判据的依据都没了，还判它通过」")
    assert "dr-999" in out and "不在" in out and "FAIL" in out, (
        "没有把幽灵条目印成 FAIL。输出里 dr-999 附近：%s"
        % out[out.find("dr-999") - 120:out.find("dr-999") + 200]
        if "dr-999" in out else out[-400:])
    assert "dr-999" in (out.split("机械判定")[-1] or ""), (
        "幽灵条目应该出现在结论的失败列表里，而不是消失")


def test_phantom_eval_still_counts_toward_the_denominator(capsys):
    """幽灵条目占着注册表的位置，所以分母要照加 —— 不能让它悄悄蒸发。"""
    real = R.CHECKS
    R.CHECKS = {"dr-999": [("a", lambda: (True, "x")),
                           ("b", lambda: (True, "y"))]}
    try:
        R.main()
        out = capsys.readouterr().out
    finally:
        R.CHECKS = real
    line = [l for l in out.splitlines() if "期望级" in l]
    assert line, "没打出期望级分母"
    # 分母里应有这 2 条（分子 0）
    assert "/2" in line[-1] or "2 项" in line[-1], (
        "幽灵条目的 2 条判据没有进分母：%s" % line[-1])


# =========================================================== metadata 门

def _fake_repo(tmp_path, skill_version="6.88.0", changelog_has=None,
               evals=None):
    """造一个 REPO/SKILL 形状的假仓库，供 check_metadata 用。

    布局照抄真实的：SKILL = <root>/skills/deep-research-ultra，
    REPO = SKILL.parents[1]（这正是 preflight 自己算的方式）。
    """
    repo = tmp_path / "repo"
    skill = repo / "skills" / "deep-research-ultra"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: deep-research-ultra\nversion: %s\n---\n" % skill_version,
        encoding="utf-8")
    body = ["# CHANGELOG", ""]
    for v in (changelog_has if changelog_has is not None
              else ["v6.88.0", "v6.99.0"]):
        body += ["## %s" % v, "", "内容", ""]
    (repo / "CHANGELOG.md").write_text("\n".join(body), encoding="utf-8")
    spec = evals if evals is not None else {
        "version": "6.5.0", "last_updated": "2026-09-18",
        "evals": [{"id": "dr-001", "name": "A", "expected_behavior": ["x"]},
                  {"id": "dr-002", "name": "B", "expected_behavior": ["y"]}],
    }
    (skill / "evals" / "evals.json").write_text(
        json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return repo, skill


def _run_meta(repo, skill, capsys):
    old = (P.REPO, P.SKILL)
    P.REPO, P.SKILL = repo, skill
    try:
        ok = P.check_metadata()
    finally:
        P.REPO, P.SKILL = old
    return ok, capsys.readouterr().out


def test_metadata_passes_on_a_consistent_repo(tmp_path, capsys):
    repo, skill = _fake_repo(tmp_path)
    ok, out = _run_meta(repo, skill, capsys)
    assert ok, "一致的假仓库应该通过：\n%s" % out[-600:]


def test_metadata_goes_red_when_skill_version_has_no_changelog_section(tmp_path, capsys):
    """把 SKILL.md 的版本抬到一个 CHANGELOG 里没有的号 → 必须红。

    这是这道门唯一真正在拦的东西：**包里印的版本号在变更日志里查不到**。
    """
    repo, skill = _fake_repo(tmp_path, skill_version="9.99.9",
                             changelog_has=["v6.88.0", "v6.99.0"])
    ok, out = _run_meta(repo, skill, capsys)
    assert not ok, (
        "SKILL.md 写 9.99.9 而 CHANGELOG 里没有 `## v9.99.9`，仍然判通过 —— "
        "这道门形同虚设。\n%s" % out[-600:])
    assert "9.99.9" in out and "找不到" in out, (
        "要指出是哪个版本号找不到。输出：\n%s" % out[-600:])


def test_metadata_goes_red_on_duplicate_eval_ids(tmp_path, capsys):
    repo, skill = _fake_repo(tmp_path, evals={
        "version": "6.5.0", "last_updated": "2026-09-18",
        "evals": [{"id": "dr-001", "name": "A", "expected_behavior": ["x"]},
                  {"id": "dr-001", "name": "B", "expected_behavior": ["y"]}],
    })
    ok, out = _run_meta(repo, skill, capsys)
    assert not ok, "id 重复却判通过 —— run_evals.py 按 id 取条目，重复会静默出错"
    assert "重复" in out, out[-400:]


def test_metadata_goes_red_on_incomplete_eval_entry(tmp_path, capsys):
    repo, skill = _fake_repo(tmp_path, evals={
        "version": "6.5.0", "last_updated": "2026-09-18",
        "evals": [{"id": "dr-001", "name": "A", "expected_behavior": ["x"]},
                  {"id": "dr-002", "name": "B"}],          # 缺 expected_behavior
    })
    ok, out = _run_meta(repo, skill, capsys)
    assert not ok, "评测条目缺 expected_behavior 却判通过"
    assert "expected_behavior" in out, out[-400:]


def test_metadata_goes_red_on_broken_json(tmp_path, capsys):
    repo, skill = _fake_repo(tmp_path)
    (skill / "evals" / "evals.json").write_text("{ 不是 JSON", encoding="utf-8")
    ok, out = _run_meta(repo, skill, capsys)
    assert not ok, "坏 JSON 却判通过 —— 那会让整份规格静默失效"


# ---------------------------------------------------------------- 关键：第三条不判红

def test_metadata_does_NOT_red_on_a_large_version_gap(tmp_path, capsys):
    """⚠️ 这条钉的是「故意不设门」的那个决定。

    `evals.json` 声明 version=6.5.0 而 CHANGELOG 已到 v6.99.0，差 94 个中版本 ——
    但**规格内容确实没变过**（这 94 个版本改的是代码，不是这份规格）。
    声明落后 ≠ 声明说谎。给它设门会逼着人去改一个准确的数字，
    **保守到逼人造假的门比没门更坏**。

    所以这里用**远超任何阈值**的差距（6.5.0 vs v6.99.0）断言它仍然通过，
    并且必须把差距打印出来 —— 只打印不等于静默。
    """
    repo, skill = _fake_repo(tmp_path, evals={
        "version": "1.0.0", "last_updated": "2020-01-01",
        "evals": [{"id": "dr-001", "name": "A", "expected_behavior": ["x"]}],
    })
    ok, out = _run_meta(repo, skill, capsys)
    assert ok, (
        "版本差距 98 个中版本就判红了 —— 这正是我们要避免的："
        "逼着人改一个其实准确的数字。\n%s" % out[-600:])
    assert "1.0.0" in out and "不判红" in out, (
        "差距必须被打印出来并说明为什么不判红，否则就是静默放过。\n%s" % out[-600:])


# =========================================================== dr-009

def test_d009_timing_expectation_is_declared_unjudgeable():
    """dr-009 收了 3/4 条；没判的那条必须显式声明理由。"""
    notes = dict(R.PARTIAL_NOTES["dr-009"])
    joined = " ".join(notes)
    assert "响应时间" in joined, (
        "「响应时间显著缩短」必须显式声明为未判 —— "
        "耗时是环境相关的连续量，没有可机械判定的阈值")
    import json as _j
    spec = _j.loads(R.EVALS_JSON.read_text(encoding="utf-8"))
    orig = len(next(e for e in spec["evals"] if e["id"] == "dr-009")["expected_behavior"])
    assert len(R.CHECKS["dr-009"]) < orig, (
        "dr-009 现在全判了 —— 那 PARTIAL_NOTES 里那条该删掉，"
        "否则输出会印出已判过的东西「未判」")


def test_d009_hit_detail_actually_measured_a_miss():
    """回归钉：detail 里不许出现我没量过的数字。

    第一版印「查不存在的键 misses=0」来佐证「命中与未命中是两个计数器」，
    可那次查询根本没发生 —— misses=0 只是因为压根没查。
    现在真的查一次，detail 里必须出现 misses=1。
    """
    _ok, detail = R._d009_hit_counted()
    assert "misses=1" in detail, (
        "detail 里应报告真实查到的那次未命中（misses=1），实得：%s" % detail)


def test_d009_hit_check_rejects_a_cache_that_does_not_count_hits(monkeypatch):
    """把 hits 计数器打坏 —— 「第二次取记为命中」那条必须红。"""
    import cache as cache_mod

    # ⚠️ 两处都是第一版栽的坑：
    #  (a) 补丁里写 `cache_mod.LRUCache.get(self, key)` —— 那已经是补丁自己，
    #      直接 RecursionError。**打补丁必须先抓住原函数。**
    #  (b) 第一版包了 `get` 当作「破坏命中计数」，但真方法**照样累加 hits** ——
    #      等于什么都没破坏，证伪静默失效（这才是更危险的那个：
    #      「证伪没打中」如果没被发现，就会被当成「判据很稳」）。
    #      判据是从 `stats()` 的公开面读 hits 的，所以要破坏就压 stats。
    real_stats = cache_mod.LRUCache.stats

    def flat_stats(self):
        d = real_stats(self)
        d["hits"] = 0            # 命中数永远不增长
        return d

    monkeypatch.setattr(cache_mod.LRUCache, "stats", flat_stats)
    ok, detail = R._d009_hit_counted()
    assert not ok, (
        "hits 不再增长，而「第二次取记为命中」仍然判通过（detail=%s）" % detail[:80])
    monkeypatch.undo()