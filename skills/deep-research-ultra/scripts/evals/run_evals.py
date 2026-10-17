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

    机械判定 N/M 条评测          <- 真正跑了且通过的比例
    未纳入 (40-M)/40 条（需人判） <- 明说哪些还没被任何东西量过
    期望 K 项中通过 J 项

另外还有**第三个「没量」的口子**：一条评测可能只判了期望的一部分
（代码能算的收了，代码里根本不存在的散文半截没收）——那些用 `[ -- ]`
逐条印在对应评测下面，记在 `PARTIAL_NOTES` 里。
只报「未纳入 N/40」会漏掉它们，而那一半看起来就像「已经量过了」。

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


# ---------------------------------------------------------------- dr-010 / dr-020 / dr-030 / dr-005
_QUERY = "retrieval augmented generation evaluation"
_DIMS = ("currency", "relevance", "authority", "accuracy", "purpose")


def _fixture():
    """同一份夹具给 dr-005 / dr-010 / dr-020 / dr-030 用 —— 判据之间不该各造各的。

    三条来源覆盖三种引擎，让 CRAAP 有区分度（实测 total 分别是 79.9 / 42.0 / 53.0，
    恰好分属 high / low / medium 三个等级）。
    """
    from engines.base import SearchResult
    from plan import ResearchPlan
    plan = ResearchPlan(topic=_QUERY)
    res = [
        SearchResult(title="A paper on RAG evaluation",
                     url="https://arxiv.org/abs/2401.00001",
                     content=_QUERY + " " * 30, source="arxiv", score=0.9),
        SearchResult(title="B industry notes", url="https://news.y.com/b",
                     content="industry adoption notes " * 30, source="web", score=0.5),
        SearchResult(title="C repo readme", url="https://github.com/o/r",
                     content="repository readme content here " * 30, source="github", score=0.7),
    ]
    return plan, res


def _d010_five_dims():
    import score as sc
    _plan, res = _fixture()
    s = sc.CraapScorer().score(res[0], query=_QUERY)
    missing = [d for d in _DIMS if d not in s]
    return not missing, "score() 返回 %d 个键，五维缺 %s" % (len(s), missing or "无")


def _d010_sorted_desc():
    import score as sc
    _plan, res = _fixture()
    out = sc.CraapScorer().score_batch(list(res), query=_QUERY)
    tot = [round(r.craap_score["total"], 2) for r in out]
    # ⚠️ **score_batch 会就地改写入参**（实测 out is res）——
    #    所以判据必须用返回值，不能回头看 res 的顺序。
    return tot == sorted(tot, reverse=True), "score_batch 返回顺序 total=%s（降序=%s）" % (
        tot, tot == sorted(tot, reverse=True))


def _d010_grade_zh():
    import score as sc
    _plan, res = _fixture()
    scorer = sc.CraapScorer()
    bad = []
    for r in res:
        s = scorer.score(r, query=_QUERY)
        zh = scorer.grade_to_chinese(s["grade"])
        if zh == "未知" or not s.get("tier_label"):
            bad.append((s["grade"], zh, s.get("tier_label")))
    return not bad, ("三条来源的 grade/tier_label 都能呈现成中文；不可呈现的：%s"
                     % (bad or "无"))


def _d010_threshold():
    import score as sc
    _plan, res = _fixture()
    scorer = sc.CraapScorer()
    gate = 60.0
    kept = [scorer.score(r, query=_QUERY)["total"] for r in res
            if scorer.score(r, query=_QUERY)["total"] >= gate]
    dropped = [round(scorer.score(r, query=_QUERY)["total"], 1) for r in res
               if scorer.score(r, query=_QUERY)["total"] < gate]
    ok = all(t >= gate for t in kept) and len(kept) + len(dropped) == len(res)
    return ok, ("门槛 %.0f -> 保留 %s / 剔除 %s（保留项全 >= 门槛=%s）"
                % (gate, kept, dropped, all(t >= gate for t in kept)))


def _q20():
    import progress as pg
    plan, res = _fixture()
    return pg.assess_quality(plan, res)


def _d020_coverage():
    q = _q20()
    v = q["scores"].get("coverage")
    return isinstance(v, (int, float)), "scores.coverage=%r（total_score=%r grade=%r）" % (
        v, q.get("total_score"), q.get("grade"))


def _d020_verification():
    # 期望原文写「交叉验证率」，实现叫 verification —— 按**语义**判，不按字段名
    v = _q20()["scores"].get("verification")
    return isinstance(v, (int, float)), "scores.verification=%r" % (v,)


def _d020_contradiction():
    v = _q20()["scores"].get("contradiction_resolution")
    return isinstance(v, (int, float)), "scores.contradiction_resolution=%r" % (v,)


def _d020_result_quality():
    v = _q20()["scores"].get("result_quality")
    return isinstance(v, (int, float)), "scores.result_quality=%r（其余分项：%s）" % (
        v, sorted(_q20()["scores"]))


def _d020_improvements():
    v = _q20().get("improvements")
    return (isinstance(v, list) and len(v) > 0), "improvements 共 %d 条：%s" % (
        len(v) if isinstance(v, list) else -1,
        (v[:2] if isinstance(v, list) else v))


def _d030_issue_tree():
    from report import MermaidGenerator
    plan, _res = _fixture()
    out = MermaidGenerator.issue_tree(plan)
    return out.lstrip().startswith("graph TD"), "issue_tree 首行=%r（%d 字符）" % (
        out.split("\n")[0][:40], len(out))


def _d030_timeline():
    from report import MermaidGenerator
    out = MermaidGenerator.timeline([{"date": "2024-01", "event": "A"},
                                     {"date": "2024-06", "event": "B"}])
    return out.lstrip().startswith("timeline"), "timeline 首行=%r" % out.split("\n")[0][:40]


def _d030_pie():
    from report import MermaidGenerator
    _plan, res = _fixture()
    out = MermaidGenerator.source_distribution(res)
    # ⚠️ 空语料时返回**空串**（实测 len=0）。所以这条判据必须喂真数据 ——
    #    第一版喂了 []，两版都返回空串，看着像「通过」其实什么都没测。
    return out.lstrip().startswith("pie"), "source_distribution 首行=%r（%d 字符）" % (
        out.split("\n")[0][:40] if out else "", len(out))


def _d030_embedded():
    import report as rp
    plan, res = _fixture()
    html = rp.generate_report(plan, res, format="html")
    has_div = 'class="mermaid"' in html
    has_cdn = "mermaid.min.js" in html
    has_init = "mermaid.initialize" in html
    return (has_div and has_cdn and has_init), (
        'class="mermaid"=%s 运行时 CDN=%s mermaid.initialize=%s；'
        '（原期望写的是 <pre class=\'mermaid\'>，实现用 div —— 已按实现对账）'
        % (has_div, has_cdn, has_init))


def _html_once():
    import report as rp
    plan, res = _fixture()
    return rp.generate_report(plan, res, format="html")


def _d005_is_html():
    h = _html_once()
    return h.lstrip().lower().startswith("<!doctype html"), (
        "默认 format='html' -> 输出 %.60r（%d 字符）" % (h[:56], len(h)))


# 期望原文点名的七个章节。用**语义关键词**判，不绑死具体字面 ——
# 因为 evals.json 落后代码 4 个版本，具体措辞对不上不代表章节不存在。
_SECTION_KEYS = [
    ("执行摘要", ("执行摘要",)),
    ("MECE 问题树", ("MECE",)),
    ("CER 结构分析", ("子问题分析", "CER")),
    ("矛盾点", ("矛盾点",)),
    ("时间线", ("时间线",)),
    ("结论", ("结论",)),
    ("附录", ("附录",)),
]


def _d005_sections():
    import re
    h = _html_once()
    titles = re.findall(r"<h[12][^>]*>([^<]{1,44})</h[12]>", h)
    joined = " | ".join(titles)
    missing = [name for name, keys in _SECTION_KEYS
               if not any(k in joined for k in keys)]
    return not missing, ("章节 %d 个：%s%s" % (
        len(titles), titles, ("；**缺**：" + "、".join(missing)) if missing else ""))


def _d005_numbering_unique():
    import re
    from collections import Counter
    h = _html_once()
    nums = re.findall(r"<h[12][^>]*>\s*(\d+)\.", h)
    dup = sorted(k for k, v in Counter(nums).items() if v > 1)
    return not dup, "标题编号序列 %s%s" % (nums, ("；**重复**：" + "、".join(dup)) if dup else "")


# ---------------------------------------------------------------- dr-005 的骨架路径
# ⚠️⚠️ **本项目有两条报告渲染路径，能力差别极大，别再混着量。**
#
# `skeleton.py` —— 规范路径，**从证据账本生成** Markdown：
#     ## 一页拍板 / 执行摘要 / <主题> / 调研方法 / 结论与建议 / 来源
#     每条 claim 行尾挂 [N]（账本 primary_index），来源登记表带 Tier/标题/URL，
#     未验证 claim 标 ⚠️ 并写明原因。`validate_report.py` 审的正是这一套。
#
# `report.py` —— v4/v5 血统的 HTML 路径（Mermaid 图表），**账本那套 [N] 约定没有**。
#
# 我第一版把 dr-005 全部判据都挂在 `report.py` 上，量出「[N] 引用 0 次、
# 没有结论」—— **那是彻底的错误结论**，而它看上去完全合理。
# 这是本项目**第三次**栽在「量到了别的分支」（v6.91 verify_quotes.py:113、
# afb059a 文档串命中）。
_SKEL_QUERY = "rag"


def _skeleton_ledger():
    """真账本：1 条 verified（2 独立来源）+ 1 条 pending（单源）。

    必须有真账本 —— `skeleton.py` 的 [N] 是**按账本 primary_index** 生成的，
    空账本生成不出引用，于是量到的还是「0 次」但原因完全不同。
    """
    import tempfile as _tf
    import ledger as lg
    root = Path(_tf.mkdtemp(prefix="eval_skel_")) / "ledger"
    L = lg.ResearchLedger(str(root)).init()
    c1 = L.add_claim("检索增强生成在 RAG 系统里显著降低幻觉（已验证）",
                     _SKEL_QUERY, "verified", "general", 0.85)["id"]
    c2 = L.add_claim("单源结论：某库默认关闭重排", _SKEL_QUERY, "pending", "general", 0.4)["id"]
    L.add_source(c1, "https://arxiv.org/abs/2401.00001", title="A paper", tier=1)
    L.add_source(c1, "https://news.y.com/b", title="B notes", tier=3)
    L.add_source(c2, "https://news.y.com/b", title="B notes", tier=3)
    return str(root)


def _d005_skeleton_citations():
    """骨架路径：每条 claim 行尾挂 [N]，可回源。"""
    import re
    import skeleton as sk
    md = sk.build_skeleton(_skeleton_ledger(), title="RAG 调研")
    cites = re.findall(r"\[(\d+)\]", md)
    return (len(cites) > 0 and len(set(cites)) > 0), (
        "骨架 Markdown %d 字符，[N] 引用 %d 处、编号 %s"
        % (len(md), len(cites), sorted(set(cites), key=int)))


def _d005_skeleton_source_table():
    """骨架路径：来源登记表含 编号/Tier/标题/URL。"""
    import skeleton as sk
    md = sk.build_skeleton(_skeleton_ledger(), title="RAG 调研")
    ok = ("| 编号 | Tier | 标题 | URL |" in md
          and "arxiv.org/abs/2401.00001" in md)
    return ok, "来源登记表表头在=%s、具体 URL 在=%s" % (
        "| 编号 | Tier | 标题 | URL |" in md, "arxiv.org/abs/2401.00001" in md)


def _d005_skeleton_marks_unverified():
    """骨架路径：未验证 claim 带 ⚠️ 且写明原因。"""
    import skeleton as sk
    md = sk.build_skeleton(_skeleton_ledger(), title="RAG 调研")
    return ("⚠️" in md and "pending" in md), (
        "⚠️ 出现 %d 次，含未达判据的说明=%s" % (md.count("⚠️"), "pending" in md))


def _d005_skeleton_sections():
    """骨架路径：一页拍板 / 执行摘要 / 调研方法 / 结论与建议 / 来源 都在。"""
    import re
    import skeleton as sk
    md = sk.build_skeleton(_skeleton_ledger(), title="RAG 调研")
    heads = re.findall(r"^##\s+(.+)$", md, re.M)
    need = ["一页拍板", "执行摘要", "调研方法", "结论与建议", "来源"]
    missing = [n for n in need if not any(n in h for h in heads)]
    return not missing, "章节 %s%s" % (heads, ("；缺：" + "、".join(missing)) if missing else "")


# ---------------------------------------------------------------- dr-025
# EngineRegistry 降级链。四条期望**全部离线可判**：注册表只读内存里的
# `_engines` 字典，排序发生在 `get_fallback_chain()` 里，没有任何 IO。
#
# 为什么值得收：dr-025 的 `test_file` 字段指向
# `tests/test_core.py::TestEngineRegistry::test_fallback_chain` —— 那条测试
# **已经存在**，但它只注册了 2 个引擎、每个层一个，只断言「Layer 1 在 Layer 4 前面」。
# **同层 priority 排序**与**不可用引擎被排除**这两条期望它一条都没测。
# 有测试 ≠ 期望被覆盖过，这里补的是真实空白。
def _d025_registry():
    """造一个注册表：两层各多档 priority，外加两个 is_available()=False 的引擎。

    不可用的那两个**故意放在最前排的位置**（layer=1 priority=1）——
    如果排除逻辑坏了，它们会立刻爬到链首，判据立刻红，而不是「碰巧通过」。
    """
    from engines.base import EngineRegistry, SearchEngine, EngineMetadata

    spec = [
        # (名字, layer, priority, 可用)
        ("l4_cheap", 4, 1, True),      # Layer 4 但 priority 最小 —— 层必须压过 priority
        ("l2_a", 2, 99, True),
        ("l1_b", 1, 50, True),
        ("l1_a", 1, 10, True),         # 与 l1_b 同层，priority 更小 → 必须排在前面
        ("l1_dead_first", 1, 1, False),  # 不可用却排在最前位
        ("l3_dead", 3, 1, False),        # 不可用
    ]

    def make(name, layer, priority, ok):
        class _E(SearchEngine):
            @property
            def metadata(self):
                return EngineMetadata(name=name, layer=layer, description="", priority=priority)

            def is_available(self):
                return ok

            def search(self, query, max_results=10, **kw):
                return []
        _E.__name__ = "E_%s" % name
        return _E()

    reg = EngineRegistry()
    # 逆序注册：注册顺序不该影响降级链顺序
    for name, layer, priority, ok in reversed(spec):
        reg.register(make(name, layer, priority, ok))
    return reg, spec


def _d025_ordering():
    reg, spec = _d025_registry()
    chain = reg.get_fallback_chain()
    keys = [(e.get_layer(), e.metadata.priority) for e in chain]
    return keys == sorted(keys), "降级链 (layer,priority)=%s，升序=%s" % (
        keys, keys == sorted(keys))


def _d025_layer_order():
    reg, _spec = _d025_registry()
    layers = [e.get_layer() for e in reg.get_fallback_chain()]
    return (layers and layers[0] == 1 and layers[-1] == 4), (
        "链首 layer=%s、链尾 layer=%s（期望 1 → 4）" % (layers[0], layers[-1]))


def _d025_same_layer_priority():
    reg, _spec = _d025_registry()
    chain = reg.get_fallback_chain()
    per_layer = {}
    for e in chain:
        per_layer.setdefault(e.get_layer(), []).append(e.metadata.priority)
    bad = {k: v for k, v in per_layer.items() if v != sorted(v)}
    return (not bad and len(per_layer) >= 3), (
        "各层 priority %s；层内未升序的：%s" % (per_layer, bad or "无"))


def _d025_excludes_unavailable():
    reg, spec = _d025_registry()
    chain = reg.get_fallback_chain()
    dead = [n for n, _l, _p, ok in spec if not ok]
    leaked = [e.get_name() for e in chain if e.get_name() in dead]
    total_avail = sum(1 for _n, _l, _p, ok in spec if ok)
    return (not leaked and len(chain) == total_avail), (
        "注册 %d 个（不可用 %s）→ 链上 %d 个，期望 %d；漏进来的：%s"
        % (len(spec), dead, len(chain), total_avail, leaked or "无"))


# ---------------------------------------------------------------- dr-028
# 中文查询。先量过再写判据（实测）：
#   _score_relevance('FastAPI性能', ...)          -> 100
#   _score_relevance('FastAPI 性能测试', ...)      -> 75.0
#   _score_relevance('   ')                       -> 50.0（中性基线，非 0）
#   score(...) 的签名要带 .url 的结果对象，不是 (query,title,content) ——
#   按期望原文直接调会抛 AttributeError。判据一律走 `_score_relevance`。
#
# ⚠️ exp1 与 exp3 在期望原文里高度重叠（一个说机制、一个说结果）。
#    这里**不把两条合并成一条**：exp1 判的是「机制上不依赖空格分词」
#    ——所以额外断言「按空格切出的那个整串**不是**标题的子串」，
#    这样正分只能来自更细粒度的匹配；exp3 判的是用户可见的结果（分数 > 0）。
#    合并成一条会让「机制」那一半变成没人验证的散文。

def _d028_scores(query, title, content):
    import score as sc
    return sc.CraapScorer()._score_relevance(query, title, content)


def _d028_no_space_dependency():
    q, title = "FastAPI性能", "FastAPI 性能基准"
    v = _d028_scores(q, title, "FastAPI 在中文场景下的性能测试与基准对比")
    # v3 的 query.split() 在这里得到 ['FastAPI性能']，而标题里是 'FastAPI 性能基准'
    # ——**整串不是子串**，所以 v3 的覆盖度必然是 0。
    whole_is_sub = q.lower() in title.lower()
    ok = v > 0 and not whole_is_sub
    # ⚠️ 标签写成「整串**不是**标题子串=True」而不是「整串是子串=False」。
    #    两种写法都能表达同一件事，但前者的 True 读起来是「符合预期」。
    #    **第一版我把 `whole_not_sub` 印成「整串是标题子串=True」——判据对、文字反了**，
    #    读的人会得出与事实相反的结论。量出来的细节文本误导人，比数字错更坏。
    return ok, ("查询 %r（无空格）对标题 %r -> %s；整串**不是**标题子串=%s"
                "（为真才说明正分不可能来自空格分词，只能来自更细粒度匹配）"
                % (q, title, v, not whole_is_sub))


def _d028_char_ngram():
    # 构造一个**只有字符级 2-gram 能命中**的语料：
    # 查询整串「向量数据库选型」不在标题里，查询里也没有任何英文 token
    # （所以「英文按空格分词」这条路一点都走不通）。
    q, title = "向量数据库选型", "向量数据库横向对比"
    v = _d028_scores(q, title, "向量数据库的选型维度与对比结论")
    whole_is_sub = q in title
    has_latin = any("a" <= ch.lower() <= "z" for ch in q)
    ok = v > 0 and not whole_is_sub and not has_latin
    return ok, ("查询 %r 对标题 %r -> %s；整串**不是**标题子串=%s、查询**不含**拉丁字母=%s"
                "（两者皆为真 ⇒ 英文按空格分词这条路完全走不通，"
                "命中只可能来自字符级 n-gram）"
                % (q, title, v, not whole_is_sub, not has_latin))


def _d028_relevance_positive():
    # ⚠️ 标题**故意不含查询整串**（`推理成本优化` vs `大模型推理的成本优化路径`，
    #    中间隔了个「的」）。第一版我把标题写成 `大模型推理成本测算` ——
    #    整串正好是子串，于是**连 v3 的 split() 都能命中**，
    #    把相关性退回 v3 实现时这条判据照样绿 ⇒ **一条没有区分力的判据**。
    #    期望原文括号里写的就是「v3 会是 0」，所以判据必须选一个 v3 真的会得 0 的语料。
    q, title = "推理成本优化", "大模型推理的成本优化路径"
    v = _d028_scores(q, title, "推理成本的优化手段与取舍")
    whole_is_sub = q in title
    return (v > 0 and not whole_is_sub), (
        "纯中文查询 %r 对标题 %r -> %s；整串**不是**标题子串=%s"
        "（为真 ⇒ v3 的 split() 会得 0，这条判据才有区分力）"
        % (q, title, v, not whole_is_sub))


def _d028_mixed_query():
    v = _d028_scores("FastAPI 性能测试", "FastAPI 性能测试报告",
                     "FastAPI 性能测试方法与瓶颈定位")
    return v > 0, "中英混合查询 'FastAPI 性能测试' relevance=%s（期望 > 0）" % (v,)


# ---------------------------------------------------------------- dr-036
# effort 分级路由。先量过（实测）：
#   PlanGenerator.DEPTH_PRESETS: quick/standard/deep/extreme 的 max_sub_questions
#                              = 3 / 5 / 8 / 12
#   research.EFFORT_BREADTH     = {'quick':2,'standard':4,'deep':8,'exhaustive':12}
#   resolve_preset_key(effort='quick', depth='extreme')     = 'quick'
#   resolve_preset_key(effort='exhaustive', depth='quick') = 'extreme'
#
# ⚠️ 期望原文里的「跳过专家团 / 单 Agent 串行 / red-team 对抗评审 / 多轮修订 /
#    计划确认门待确认清单」**不是代码，是 SKILL.md 里的工作流散文**：
#    搜遍 scripts/*.py 与 scripts/engines/*.py 没有任何按 effort 分级的
#    专家团/红队/修订轮常量；`待确认`/`确认门`/`计划确认` 只在 SKILL.md 出现
#    （5 / 3 / 3 处）。**代码里没有的东西不能机械判** —— 收进来就是造假精确度。
#    所以本条只判代码能判的那几项，剩下的在 PARTIAL_NOTES 里逐条列出原因。
def _d036_quick_shape():
    from plan import PlanGenerator
    import research
    sub = PlanGenerator.DEPTH_PRESETS["quick"]["max_sub_questions"]
    breadth = research.EFFORT_BREADTH["quick"]
    return (sub <= 3 and breadth == 2), (
        "quick：max_sub_questions=%s（期望 <=3）、EFFORT_BREADTH=%s（期望 2）"
        % (sub, breadth))


def _d036_exhaustive_shape():
    from plan import PlanGenerator, resolve_preset_key
    import research
    key = resolve_preset_key(effort="exhaustive")
    sub = PlanGenerator.DEPTH_PRESETS[key]["max_sub_questions"]
    breadth = research.EFFORT_BREADTH["exhaustive"]
    return (sub >= 10 and breadth == 12), (
        "effort=exhaustive → 预设键 %r：max_sub_questions=%s（期望 >=10）、"
        "EFFORT_BREADTH=%s（期望 12）" % (key, sub, breadth))


def _d036_effort_beats_depth():
    from plan import resolve_preset_key
    a = resolve_preset_key(effort="quick", depth="extreme")
    b = resolve_preset_key(effort="exhaustive", depth="quick")
    c = resolve_preset_key(depth="extreme")
    ok = (a == "quick" and b == "extreme" and c == "extreme")
    return ok, ("effort+depth 同给：quick+extreme -> %r（期望 quick）、"
                "exhaustive+quick -> %r（期望 extreme）；只给 depth=extreme -> %r"
                % (a, b, c))


CHECKS = {
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
    "dr-010": [
        ("每条结果都带 CRAAP 五维评分", _d010_five_dims),
        ("score_batch 按 CRAAP 总分降序返回", _d010_sorted_desc),
        ("每条结果带可信度等级（grade + tier_label）且可映射成中文", _d010_grade_zh),
        ("按 total 过滤后剩下的都 >= 门槛", _d010_threshold),
    ],
    "dr-020": [
        ("输出覆盖率 scores.coverage", _d020_coverage),
        ("输出交叉验证率 scores.verification", _d020_verification),
        ("输出矛盾处理率 scores.contradiction_resolution", _d020_contradiction),
        ("输出结果质量/平均 CRAAP scores.result_quality", _d020_result_quality),
        ("给出待深挖方向建议 improvements", _d020_improvements),
    ],
    "dr-030": [
        ("issue_tree 生成 graph TD 流程图", _d030_issue_tree),
        ("timeline 生成 timeline 时间线", _d030_timeline),
        ("source_distribution 生成 pie 饼图", _d030_pie),
        ("图表代码嵌进带 mermaid class 的元素，且已加载 mermaid 运行时", _d030_embedded),
    ],
    "dr-005": [
        ("默认输出 HTML 格式", _d005_is_html),
        ("HTML 报告含执行摘要/MECE/CER/矛盾点/时间线/结论/附录", _d005_sections),
        ("HTML 章节编号不重复且与目录一致", _d005_numbering_unique),
        ("骨架 Markdown 含一页拍板/执行摘要/调研方法/结论与建议/来源", _d005_skeleton_sections),
        ("骨架 Markdown 每条 claim 行尾挂 [N] 可回源", _d005_skeleton_citations),
        ("骨架 Markdown 来源登记表含编号/Tier/标题/URL", _d005_skeleton_source_table),
        ("骨架 Markdown 未验证 claim 带 ⚠️ 且写明原因", _d005_skeleton_marks_unverified),
    ],
    "dr-025": [
        ("降级链按 (layer, priority) 升序排列", _d025_ordering),
        ("Layer 1（MCP）排最前、Layer 4（降级）排最后", _d025_layer_order),
        ("同一 layer 内按 priority 数字小→大排", _d025_same_layer_priority),
        ("is_available()=False 的引擎被排除", _d025_excludes_unavailable),
    ],
    "dr-028": [
        ("中文查询不依赖空格分词（v3 split() 已修复）", _d028_no_space_dependency),
        ("使用字符级 n-gram 提取关键词（只有 2-gram 能命中的语料）", _d028_char_ngram),
        ("中文查询 relevance 评分 > 0", _d028_relevance_positive),
        ("支持中英混合查询", _d028_mixed_query),
    ],
    "dr-036": [
        ("quick 级：子问题 ≤3 且 breadth=2", _d036_quick_shape),
        ("exhaustive 级：子问题 ≥10 且 breadth=12", _d036_exhaustive_shape),
        ("--effort 与 --depth 同给时以 --effort 为准", _d036_effort_beats_depth),
    ],
}


# 收了「一部分」的评测：那些**代码里根本没有对应符号**的期望半截。
# 必须显式列出来 —— 否则这条评测会看起来「全判过了」，而实际上有一半没人量。
#
# 判据：代码里能算出来的判，代码里根本不存在的**不判**。
# 「专家团 / 红队」这类工作流散文不是布尔量，硬打分只会造出假的精确度
# ——与本项目从 v6.95 起就在守的那条规矩同源。
PARTIAL_NOTES = {
    "dr-036": [
        ("quick 级「跳过专家团、单 Agent 串行」",
         "scripts/ 下没有任何按 effort 分级的专家团开关；这是 SKILL.md 的编排散文"),
        ("exhaustive 级「red-team 对抗评审、多轮修订」",
         "同样没有按 effort 分级的红队/修订轮常量"),
        ("计划确认门输出待确认清单",
         "`待确认`/`确认门`/`计划确认` 只出现在 SKILL.md（5/3/3 处），"
         "plan.py 与 research.py 里没有任何对应符号"),
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
        # 收了「一半」的评测要把没判的那一半印出来。
        # 不印的话，这条评测会显示成「全判过了」，而实际上有一半根本没人量过。
        for what, why in PARTIAL_NOTES.get(eid, []):
            print(f"  [ -- ] {what}")
            print(f"         未判：{why}")
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