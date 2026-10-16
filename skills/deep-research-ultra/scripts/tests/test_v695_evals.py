# -*- coding: utf-8 -*-
"""v6.95：评测子集（`scripts/evals/run_evals.py`）+ cache 计数器归属修复。

## 这一版在量一阶问题

此前所有量化都在**二阶**：变异检出率 90.6%、边界覆盖 72/72、测试 1372 项。
它们回答「这套测试能不能抓出代码里的 bug」。
**没有一条回答「这插件产出的东西到底对不对」。**

`evals/evals.json` 有 40 条评测，但**全是散文式期望，没有任何东西去跑它**。
于是它是规格，不是测量。

## 第一版跑出来就抓到一条真缺陷

`dr-024` 期望「超过 max_entries 时最久未访问条目被 LRU 淘汰（evicted_lru 计数 +1）」，
实得 `evicted_lru=0`。

`cache._evict_if_needed` 里归属写在**清标记之后**：

    if need_evict_by_count and len(entries) - evicted <= max_entries:
        need_evict_by_count = False          # 先清
    ...
    if need_evict_by_count:
        self._stats['evicted_lru'] += 1      # 再看，已经是 False

按条目数淘汰**每一次**都被记到 `evicted_size`，而 `evicted_lru` 永远是 0。
影响不是「计数器不准」：看 stats() 诊断缓存的人会把条目数超限误读成体积超限，
从而去调 `max_size_mb` —— 调错了参数。

而 1372 项测试里**没有一条断言这两个计数器**。
变异检出率再高也发现不了它 —— **那里根本没有变异可找，bug 就在代码里**。

## 判据自己也要被证明

`test_runner_goes_red_when_the_cache_attribution_breaks` 在副本上把归属改回去，
要求评测器退出 1。这和 `test_v692_pin_anchors.py` 同一个形状：
**「装上缺陷，要求它变红」**。
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path

S = Path(__file__).resolve().parents[1]
REPO = S.parents[2]
sys.path.insert(0, str(S))

import cache as cache_mod                      # noqa: E402

EVALS_DIR = S / "evals"
RUNNER = EVALS_DIR / "run_evals.py"
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")


def _mk(max_entries, max_size_mb, n, tag, payload_size=400):
    d = Path(tempfile.mkdtemp(prefix="v695_%s_" % tag))
    c = cache_mod.LRUCache(cache_dir=d, ttl=timedelta(hours=1),
                           max_entries=max_entries, max_size_mb=max_size_mb)
    pay = {"content": "v" * payload_size, "title": "t"}
    for i in range(n):
        c.set("k%d" % i, dict(pay, url="https://e.example/k%d" % i))
    return c.stats()


# ======================================================================
# 一、cache 计数器归属
# ======================================================================
def test_count_eviction_is_attributed_to_lru_not_to_size():
    """按**条目数**超限时，计数必须记到 evicted_lru，且 evicted_size 不动。"""
    s = _mk(max_entries=3, max_size_mb=100, n=4, tag="cnt")
    assert s["evicted_lru"] >= 1, (
        "按条目数淘汰了却没记到 evicted_lru：%r" % s)
    assert s["evicted_size"] == 0, (
        "按条目数淘汰被错记到 evicted_size 上：%r" % s)


def test_size_eviction_is_attributed_to_size():
    """按**体积**超限时反过来 —— 另一侧必须不动。

    两侧都要钉：只钉一侧的话，把归属整体写反也能全绿。
    """
    d = Path(tempfile.mkdtemp(prefix="v695_sz_"))
    c = cache_mod.LRUCache(cache_dir=d, ttl=timedelta(hours=1),
                           max_entries=1000, max_size_mb=1)
    big = {"content": "v" * (600 * 1024), "url": "https://e.example/big"}
    c.set("s1", big)
    c.set("s2", big)
    s = c.stats()
    assert s["evicted_size"] >= 1, "按体积淘汰没记到 evicted_size：%r" % s
    assert s["evicted_lru"] == 0, "按体积淘汰被错记到 evicted_lru 上：%r" % s


def test_evicted_lru_is_not_structurally_dead():
    """`evicted_lru` 必须在**每个**超出量上都恰好涨那么多。

    原实现下它是恒 0 的死计数器：清标记的条件
    `len(entries) - evicted <= max_entries` 在进来时 `len > max_entries`
    的前提下必然先被满足，于是 `if need_evict_by_count` 永远看不见 True。

    只测「某一次超限」可能碰巧过 —— 这里扫 1/2/7 条三个超出量，
    要求 `evicted_lru == n - max_entries` **精确相等**。
    """
    for over in (1, 2, 7):
        s = _mk(max_entries=3, max_size_mb=100, n=3 + over, tag="o%d" % over)
        assert s["evicted_lru"] == over, (
            "超出 %d 条时 evicted_lru 应恰好 %d，实得 %r" % (over, over, s))
        assert s["evicted_size"] == 0, (
            "超出 %d 条时不该有任何 size 归属，实得 %r" % (over, s))


# ======================================================================
# 二、评测器：分母必须印出来，且没跑的绝不算通过
# ======================================================================
def _run_runner() -> tuple[str, int]:
    r = subprocess.run([sys.executable, "-X", "utf8", str(RUNNER)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, env=ENV, cwd=str(REPO))
    return r.stdout or "", r.returncode


def test_runner_prints_all_three_denominators():
    """**机械判定通过数/已判定数**、**未纳入数/总数**、**期望级通过数/总数**。

    缺任一个分母，这道输出就没法被读成「有多好」——
    「10/10」和「10/40」是完全不同的两件事。
    """
    out, _rc = _run_runner()
    m1 = re.search(r"机械判定 (\d+)/(\d+) 条评测", out)
    m2 = re.search(r"未纳入 (\d+)/(\d+) 条", out)
    m3 = re.search(r"期望级 (\d+)/(\d+)", out)
    assert m1 and m2 and m3, "三个分母没全印出来：\n%s" % out[-900:]
    assert m2.group(2) == "40", "总数应当是 evals.json 的条目数 40，实得 %s" % m2.group(2)
    assert int(m2.group(1)) + int(m1.group(2)) == int(m2.group(2)), (
        "已判定 %s + 未纳入 %s != 总数 %s —— 有一条既没判也没列进未纳入"
        % (m1.group(2), m2.group(1), m2.group(2)))


def test_unscored_evals_are_never_counted_as_passed():
    """「已判定」那个分母必须等于 CHECKS 的条数，**不能**等于 evals.json 的 40。

    这是这类评测最常见的注水方式：把没跑的算成过了。
    """
    sys.path.insert(0, str(EVALS_DIR))
    import run_evals as R
    out, _rc = _run_runner()
    m = re.search(r"机械判定 (\d+)/(\d+) 条评测", out)
    assert m, out[-500:]
    assert int(m.group(2)) == len(R.CHECKS), (
        "分母 %s != CHECKS 条数 %d —— 没纳入的被算成了判定过的" % (m.group(2), len(R.CHECKS)))
    assert len(R.CHECKS) < 40, (
        "全 40 条都判定了？那「需人判」的去哪了 —— 判据多半是假的")


def test_every_check_id_exists_in_evals_json():
    """CHECKS 里引用的 id 必须在 evals.json 里真实存在。

    evals.json 已经落后代码 4 个版本（声明 6.5.0）；哪天它被重编号，
    这个门会当场报出来，而不是让判据静默地对不上的条目。
    """
    import json
    sys.path.insert(0, str(EVALS_DIR))
    import run_evals as R
    ids = {e["id"] for e in json.loads(
        (S.parent / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]}
    ghost = sorted(set(R.CHECKS) - ids)
    assert not ghost, f"CHECKS 里这些 id 在 evals.json 中不存在：{ghost}"


def test_check_count_never_exceeds_the_written_expectations():
    """一条评测的判据数不得多于它写的期望条数 —— 多出来就是编的。"""
    import json
    sys.path.insert(0, str(EVALS_DIR))
    import run_evals as R
    spec = json.loads((S.parent / "evals" / "evals.json").read_text(encoding="utf-8"))
    by = {e["id"]: e for e in spec["evals"]}
    bad = []
    for eid, checks in R.CHECKS.items():
        n_written = len(by.get(eid, {}).get("expected_behavior") or [])
        if len(checks) > n_written:
            bad.append("%s: 判据 %d 条 > 原文期望 %d 条" % (eid, len(checks), n_written))
    assert not bad, "判据数超过原文期望数：" + "; ".join(bad)


def test_runner_exits_zero_only_when_every_scored_check_passes():
    """已判定且全过 -> 0；有任何一条不过 -> 1。"""
    out, rc = _run_runner()
    ok = re.search(r"机械判定 (\d+)/(\d+) 条评测", out)
    assert ok, out[-400:]
    passed, total = int(ok.group(1)), int(ok.group(2))
    assert total > 0
    assert (rc == 0) == (passed == total), (
        "通过 %d/%d 而退出码 %d —— 两者必须一致" % (passed, total, rc))


def test_every_check_reports_measured_detail_not_a_bare_boolean():
    """每条判据都要给出**实测细节**。

    只回 True/False 的判据出问题时没人知道发生了什么；
    本项目栽过好几次「安静地给出一个错误的正常结果」。
    """
    sys.path.insert(0, str(EVALS_DIR))
    import run_evals as R
    for eid, checks in R.CHECKS.items():
        for label, fn in checks:
            res = fn()
            assert isinstance(res, tuple) and len(res) == 2, (
                "%s / %s 没有返回 (bool, detail)" % (eid, label))
            ok, detail = res
            assert isinstance(ok, bool), "%s / %s 的第一个返回值不是 bool" % (eid, label)
            assert isinstance(detail, str) and detail.strip(), (
                "%s / %s 没给出实测细节" % (eid, label))


# ======================================================================
# 三、端到端证伪：把归属改回去，评测器必须退出 1
# ======================================================================
def test_runner_goes_red_when_the_cache_attribution_breaks():
    """副本上把归属改回原样（先清标记再看标记），评测器必须 exit 1。

    **证伪脚本必须断言是哪一条红了**，只看退出码会把别的失败算成自己的功劳。
    """
    import probe_mutation as pm
    td = Path(tempfile.mkdtemp(prefix="v695_proof_"))
    scr = pm.make_copy(td / "repo")
    try:
        assert pm._is_under(scr, td), "副本不在临时目录下 —— 中止"
        cpath = scr / "cache.py"
        good = cpath.read_text(encoding="utf-8")
        good_line = "                reason = 'lru' if need_evict_by_count else 'size'\n"
        assert good_line in good, "找不到修好的那行 —— 源码变了？"
        # 把它换回「先清标记、再看标记」的写法，并把清理挪到归属之后
        broken = good.replace(
            good_line, "").replace(
            "                self._stats['evicted_' + reason] += 1\n",
            "                if need_evict_by_count:\n"
            "                    self._stats['evicted_lru'] += 1\n"
            "                else:\n"
            "                    self._stats['evicted_size'] += 1\n")
        assert broken != good, "没能把缺陷放回去 —— 证伪没意义"
        cpath.write_text(broken, encoding="utf-8", newline="\n")
        pm.clear_pycache(scr)
        r = subprocess.run(
            [sys.executable, "-X", "utf8", str(scr / "evals" / "run_evals.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, env=ENV, cwd=str(scr))
        out = r.stdout or ""
        assert r.returncode != 0, "把归属改回去之后评测器仍然绿：\n%s" % out[-700:]
        hit = [ln for ln in out.splitlines() if ln.startswith("  [FAIL]")]
        assert hit, (
            "退出码非 0，但**不是**因为那条期望没过 —— 证伪无效。输出：\n%s" % out[-700:])
        assert any("LRU" in ln for ln in hit), (
            "红的那条不是我预期的 LRU 归属项：%s" % hit)
        print("        [OK] 放回缺陷后 dr-024 的 LRU 归属项报红并退出 1")
    finally:
        shutil.rmtree(td, ignore_errors=True)