# -*- coding: utf-8 -*-
"""run_evals.py —— 把 `evals/evals.json` 从**规格清单**变成**能出数字的评测**。

## 为什么要有这个文件

`evals.json` 里有 40 条评测，每条写着「应该出现什么」。但**40 条全是散文式期望，
没有任何东西去跑它、去打分** —— 它是一份规格，不是一次测量。

而本项目此前所有的量化都在**二阶**：变异检出率、边界覆盖率、测试计数。
它们回答的是「这套测试能不能抓出代码里的 bug」，
**没有一条回答「这插件产出的东西到底对不对」**。

1372 项测试、90.6% 变异检出、100% 边界检出，可以完全配一个产出平庸报告的插件。
绿灯只说明灯是亮的。

## 这一版只收「机械可判定」的子集

收进来的判据只有一条：**每一条期望都能从真实代码离线算出来**。

`dr-002 模糊主题澄清 → 触发澄清问题并给出多种方向` 这类**判不了** ——
「问题问得好不好」不是布尔量，硬打分只会造出一个假的精确度。
所以它们**不收**，并在这里如实列出数量。

> **没跑的绝不算成通过。** 输出必须打出「判了多少 / 没判多少」两个分母。

## 三个分母，缺一不可

    机械判定 3/4 条评测          <- 真正跑了且通过的比例
    未纳入 36/40 条（需人判）    <- 明说哪些还没被任何东西量过
    期望 13 项中通过 11 项

把「没跑的」混进「跑过的」是这类评测最常见的注水方式。

## 它抓到过什么

v6.95 第一次跑就红：`dr-024` 期望「超过 max_entries 时 evicted_lru 计数 +1」，
实得 `evicted_lru=0`。**而 1372 项测试里没有任何一条断言这两个计数器** ——
变异检出率再高也发现不了它，因为**根本没有变异，是代码本身就写错了**。

## 退出码

只有**已判定且未通过**才退出 1。没纳入的那 36 条不参与 ——
否则这道门会永远红，而永远红的门没人跑。
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
SKILL = SCRIPTS.parent
REPO = SKILL.parents[1]
EVALS_JSON = SKILL / "evals" / "evals.json"

sys.path.insert(0, str(SCRIPTS))


# ======================================================================
# 一条期望 = 一个零参可调用，返回 (是否通过, 实测细节)
# 细节必须来自**实跑**，不是「应该」。
# ======================================================================
Check = "callable"


def _lru_counts(max_entries, max_size_mb, n, tag):
    """造一个独立 LRUCache 连写 n 条，回读计数器。"""
    import cache as cache_mod
    d = Path(tempfile.mkdtemp(prefix="eval_%s_" % tag))
    c = cache_mod.LRUCache(cache_dir=d, ttl=timedelta(hours=1),
                           max_entries=max_entries, max_size_mb=max_size_mb)
    pay = {"content": "v" * 400, "title": "t"}
    for i in range(n):
        c.set("k%d" % i, dict(pay, url="https://e.example/k%d" % i))
    return c.stats()


# ---------------------------------------------------------------- dr-024
def _d024_ttl():
    import time
    import cache as cache_mod
    d = Path(tempfile.mkdtemp(prefix="eval_ttl_"))
    c = cache_mod.LRUCache(cache_dir=d, ttl=timedelta(seconds=1),
                           max_entries=100, max_size_mb=100)
    c.set("t1", {"content": "x", "url": "https://e.example/t1"})
    time.sleep(1.4)
    got = c.get("t1")
    s = c.stats()
    ok = got is None and s["evicted_ttl"] >= 1
    return ok, "TTL=1s 睡 1.4s 后读=%r evicted_ttl=%s" % (got, s["evicted_ttl"])


def _d024_lru_count():
    # 容量给到 100MB、4 条共约 4KB —— **只有条目数**能触发淘汰
    s = _lru_counts(max_entries=3, max_size_mb=100, n=4, tag="cnt")
    ok = s["evicted_lru"] >= 1 and s["evicted_size"] == 0
    return ok, ("max_entries=3 写 4 条 -> evicted_lru=%s evicted_size=%s entries=%s"
                % (s["evicted_lru"], s["evicted_size"], s["entries"]))


def _d024_size():
    import cache as cache_mod
    d = Path(tempfile.mkdtemp(prefix="eval_sz_"))
    c = cache_mod.LRUCache(cache_dir=d, ttl=timedelta(hours=1),
                           max_entries=1000, max_size_mb=1)
    big = {"content": "v" * (600 * 1024), "url": "https://e.example/big"}
    c.set("s1", big)
    c.set("s2", big)
    s = c.stats()
    ok = s["evicted_size"] >= 1
    return ok, ("max_size=1MB 写 2×600KB -> evicted_size=%s evicted_lru=%s"
                % (s["evicted_size"], s["evicted_lru"]))


def _d024_stats_keys():
    import cache as cache_mod
    d = Path(tempfile.mkdtemp(prefix="eval_st_"))
    c = cache_mod.LRUCache(cache_dir=d, ttl=timedelta(hours=1),
                           max_entries=10, max_size_mb=10)
    keys = set(c.stats())
    need = {"hits", "misses", "evicted_ttl", "evicted_lru", "evicted_size"}
    missing = sorted(need - keys)
    return not missing, ("stats() 有 %d 个键，缺 %s" % (len(keys), missing or "无"))


# ---------------------------------------------------------------- dr-035
def _d035_init_dirs():
    import ledger as lg
    root = Path(tempfile.mkdtemp(prefix="eval_led_")) / "ledger"
    lg.ResearchLedger(str(root)).init()
    got = sorted(p.name for p in root.iterdir())
    need = sorted(["ledger.jsonl", "claims", "sources"])
    return got == need, "init 后目录=%s" % (got,)


def _d035_claim_has_source():
    import ledger as lg
    root = Path(tempfile.mkdtemp(prefix="eval_led2_")) / "ledger"
    led = lg.ResearchLedger(str(root)).init()
    cid = led.add_claim("一条需要出处的结论", "t", "pending", "p", 0.5)["id"]
    empty = len(led.sources_for_claim(cid))
    led.add_source(cid, "https://arxiv.org/abs/2401.00001", title="A", tier=1)
    one = len(led.sources_for_claim(cid))
    return (empty == 0 and one == 1), ("加源前 %d 条 / 加源后 %d 条" % (empty, one))


def _d035_status_sufficient():
    import ledger as lg
    root = Path(tempfile.mkdtemp(prefix="eval_led3_")) / "ledger"
    led = lg.ResearchLedger(str(root)).init()
    cid = led.add_claim("需要两个独立来源且其中一个已验证", "t", "pending", "p", 0.5)["id"]
    led.add_source(cid, "https://arxiv.org/abs/2401.00001", title="A", tier=1)
    led.add_source(cid, "https://blog.example.com/x", title="B", tier=4)
    st = led.status()
    top = list(st.values())[0]
    has_keys = "independent_sources" in top and "sufficient" in top
    return (has_keys and top["independent_sources"] == 2
            and top["sufficient"] is False), (
        "2 个来源 0 verified -> independent_sources=%s sufficient=%s"
        % (top.get("independent_sources"), top.get("sufficient")))


def _d035_export():
    import ledger as lg
    root = Path(tempfile.mkdtemp(prefix="eval_led4_")) / "ledger"
    led = lg.ResearchLedger(str(root)).init()
    cid = led.add_claim("可导出的结论", "t", "pending", "p", 0.5)["id"]
    led.add_source(cid, "https://arxiv.org/abs/2401.00001", title="A", tier=1)
    md = led.export_md()
    js = led.export_json()
    # ⚠️ export_json 返回的是 **dict**，不是字符串。
    #    第一版我写 `isinstance(js, str)`，于是判据报 FAIL 而代码是对的 ——
    #    **没量就写判据**，与本项目此前那些次一模一样。
    #    教训固化在这里：判据里出现类型断言，先跑一次把类型打出来。
    ok = (isinstance(md, str) and len(md) > 40
          and isinstance(js, dict) and bool(js)
          and "stats" in js)
    return ok, ("export_md %s(%d 字符) / export_json %s(%d 顶层键 %s)"
                % (type(md).__name__, len(str(md)),
                   type(js).__name__, len(js) if hasattr(js, "__len__") else -1,
                   sorted(js) if isinstance(js, dict) else "-"))


CHECKS = {
    # id -> [(期望短名, 可调用)]
    "dr-024": [
        ("TTL 过期条目被自动清理（evicted_ttl+1）", _d024_ttl),
        ("超 max_entries 时按 LRU 淘汰（evicted_lru+1）", _d024_lru_count),
        ("超 max_size_bytes 时淘汰（evicted_size+1）", _d024_size),
        ("stats() 返回 hits/misses/evicted_ttl/evicted_lru/evicted_size", _d024_stats_keys),
    ],
    "dr-035": [
        ("init 建出 ledger.jsonl + claims/ + sources/", _d035_init_dirs),
        ("每条 claim 关联 >=1 个 source", _d035_claim_has_source),
        ("status 输出独立来源数与 sufficient 判据", _d035_status_sufficient),
        ("export_md/export_json 可导出完整账本", _d035_export),
    ],
}


# ======================================================================
def main() -> int:
    spec = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    evals = spec["evals"]
    by_id = {e["id"]: e for e in evals}

    print("=" * 78)
    print("evals.json 机械判定子集 —— 「产出的东西对不对」，不是「测试够不够强」")
    print("=" * 78)
    print()
    print(f"  评测文件：{EVALS_JSON.relative_to(REPO)}"
          f"（声明版本 {spec.get('version')}，last_updated {spec.get('last_updated')}）")
    print(f"  条目总数：{len(evals)}")
    print()

    passed_ev, failed_ev, n_expect, n_expect_ok = [], [], 0, 0
    errors = []

    for eid, checks in CHECKS.items():
        meta = by_id.get(eid)
        print("-" * 78)
        print(f"[{eid}] {meta.get('name') if meta else '（评测文件里没有这一条！）'}")
        print(f"       原始期望 {len(meta.get('expected_behavior') or [])} 条，"
              f"本版机械判定 {len(checks)} 条")
        # ⚠️ 每个判据**只跑一次**。第一版为了算「整条过没过」又调了一遍，
        # 于是 TTL 那条白睡 1.4 秒，而且判据里的临时目录被建了两遍 ——
        # 判据自己有副作用时，重复执行不是「多花点时间」，是**结论不可信**。
        ev_ok = True
        for label, fn in checks:
            n_expect += 1
            try:
                ok, detail = fn()
            except Exception as exc:                    # 判据本身崩了也算失败
                ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
                errors.append((eid, label, traceback.format_exc()))
            n_expect_ok += bool(ok)
            ev_ok = ev_ok and bool(ok)
            mark = "OK  " if ok else "FAIL"
            print(f"  [{mark}] {label}")
            print(f"         {detail}")
        (passed_ev if ev_ok else failed_ev).append(eid)

    unscored = [e["id"] for e in evals if e["id"] not in CHECKS]

    print()
    print("=" * 78)
    print(f"机械判定 {len(passed_ev)}/{len(CHECKS)} 条评测"
          f"（期望级 {n_expect_ok}/{n_expect}）")
    print(f"未纳入 {len(unscored)}/{len(evals)} 条 —— 需人判，不计为通过")
    print("=" * 78)
    if unscored:
        by_cat = {}
        for e in evals:
            if e["id"] in unscored:
                by_cat.setdefault(e.get("category", "?"), []).append(e["id"])
        print()
        print("未纳入明细（按分类）：")
        for cat, ids in sorted(by_cat.items()):
            print(f"  {cat:<22} {len(ids):>2}  {', '.join(ids)}")

    if errors:
        print()
        print("判据自身抛异常（判据有 bug，不是被测代码有问题）：")
        for eid, label, tb in errors:
            print(f"  {eid} / {label}")
            print("    " + tb.strip().splitlines()[-1])

    print()
    verdict = ("机械判定的部分全部通过" if not failed_ev
               else "机械判定的部分有 %d 条不过：%s" % (len(failed_ev), failed_ev))
    print("结论:", verdict)
    if not CHECKS:
        return 1
    return 1 if failed_ev else 0


if __name__ == "__main__":
    raise SystemExit(main())