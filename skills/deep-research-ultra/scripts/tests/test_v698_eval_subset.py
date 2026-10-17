# -*- coding: utf-8 -*-
"""v6.98：新收进来的 11 项期望，其判据必须**自己会红**。

## 为什么新增这一层

dr-025 / dr-028 / dr-036 的判据是新写的。一条新判据证明不了任何事 ——
它可能压根没接上被测代码，或者断言恒真。第一版判据就栽过：
`_d030_pie` 喂空语料，两版都返回空串，「看着像通过其实什么都没测」。

所以这里做三件事：

1. **元测试**：每条判据都有非空标签、返回 `(bool, 非空 str)`，
   且**判定条数不得超过原始期望条数**（超了就是把一条期望拆成好几条凑数）。
2. **dr-036 的一半必须被显式声明**：代码里没有的散文半截不许悄悄消失。
   只报「未纳入 N/40」会漏掉它 —— 那部分看起来就像「已经量过了」。
3. **端到端证伪**：把被测行为换成坏的（排序只看 priority、相关性退回 v3 的
   `split()`、`--effort` 不再压过 `--depth`），确认**具体哪几条判据变红**。
   只说「门会红」不够，得知道是哪几条 —— 否则「门失效」会让人去修一个没坏的检查。

## 用打桩而不是改源码

三处证伪都 monkeypatch 运行时行为，不碰仓库里的文件。
理由和 v6.97 那批一样：把「我说不清成因的条件」当判据 = 把测试建在流沙上。
"""
from __future__ import annotations

import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))
if str(S / "evals") not in sys.path:
    sys.path.insert(0, str(S / "evals"))

import run_evals as R  # noqa: E402

NEW = ("dr-025", "dr-028", "dr-036")


# ---------------------------------------------------------------- 元测试

def test_every_check_has_label_and_returns_pair_with_detail():
    for eid, checks in R.CHECKS.items():
        assert checks, "%s 在注册表里但一条判据都没有" % eid
        for label, fn in checks:
            assert label and label.strip(), "%s 里有空标签" % eid
            out = fn()
            assert isinstance(out, tuple) and len(out) == 2, (
                "%s / %s 应返回 (bool, detail)，实得 %r" % (eid, label, type(out)))
            ok, detail = out
            assert isinstance(ok, bool), "%s / %s 的第一个返回值不是 bool：%r" % (
                eid, label, type(ok))
            assert isinstance(detail, str) and detail.strip(), (
                "%s / %s 的 detail 是空的 —— 空 detail 让「量到了什么」无从判断，"
                "而空 detail 的判据通常也就是没在真的量东西" % (eid, label))


def test_judged_count_never_exceeds_original_expectation_count():
    """判定条数不得超过原始期望条数。

    拆细是允许的（dr-005 按两条渲染路径拆成 7 条），
    但那是因为**一条期望确实有多条可判的子句**。
    这里防的是反过来：一句话拆成五条来把「期望级」的分母做大。
    """
    import json
    spec = json.loads(R.EVALS_JSON.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in spec["evals"]}
    for eid, checks in R.CHECKS.items():
        orig = len(by_id[eid].get("expected_behavior") or [])
        assert len(checks) <= orig, (
            "%s 原始期望 %d 条，本版判 %d 条 —— 判定数超过原始期望数，"
            "说明有一条期望被拆成了好几条来虚增分母" % (eid, orig, len(checks)))


def test_documented_partial_coverage_is_actually_declared():
    """收了「一半」的评测，那一半必须逐条列出原因。"""
    for eid in R.PARTIAL_NOTES:
        assert eid in R.CHECKS, "%s 声明了部分未判，但根本不在判定注册表里" % eid
        for what, why in R.PARTIAL_NOTES[eid]:
            assert what and what.strip(), "%s 的未判项缺描述" % eid
            assert why and len(why.strip()) >= 12, (
                "%s / %s 的未判理由太短，等于没写理由" % (eid, what))


def test_d036_prose_halves_are_declared_not_silently_dropped():
    """dr-036 明确只判了 3/4 条期望，那没判的半截必须出现在 PARTIAL_NOTES 里。"""
    import json
    spec = json.loads(R.EVALS_JSON.read_text(encoding="utf-8"))
    orig = len(next(e for e in spec["evals"] if e["id"] == "dr-036")["expected_behavior"])
    judged = len(R.CHECKS["dr-036"])
    notes = R.PARTIAL_NOTES.get("dr-036", [])
    assert judged < orig, (
        "dr-036 现在判了 %d/%d 条 —— 若已全覆盖，PARTIAL_NOTES 里的条目"
        "就该删掉，否则输出会印出已经判过的东西「未判」" % (judged, orig))
    assert len(notes) >= 1, "dr-036 有未判的期望却没有声明"
    joined = " ".join(w + r for w, r in notes)
    for kw in ("专家团", "红队", "确认门"):
        assert kw in joined, "dr-036 的未判清单里少了「%s」那一项" % kw


def test_detail_text_is_not_inverted():
    """回归钉：dr-028 的 detail 第一版把「整串**不是**子串」印成了「是子串」。

    判据逻辑是对的，文字是反的 —— 读的人会得出与事实相反的结论。
    **量出来的细节文本误导人，比数字错更坏。**
    """
    _ok, detail = R._d028_char_ngram()
    assert "整串**不是**标题子串=True" in detail, (
        "detail 应写「整串**不是**标题子串=True」，实得：%s" % detail[:120])
    assert "查询**不含**拉丁字母=True" in detail, (
        "detail 应写「查询**不含**拉丁字母=True」，实得：%s" % detail[:120])
    assert "整串是标题子串=True" not in detail, "旧的反向措辞又回来了"


# ---------------------------------------------------------------- 证伪 1：降级链排序

def test_d025_checks_go_red_when_layer_is_ignored(monkeypatch):
    """把排序改成「只看 priority、且不排除不可用」—— dr-025 哪几条会红？

    坏掉的实现：
        sorted(self.get_all(), key=lambda e: e.metadata.priority)
    真实实现：
        available = self.get_available(); available.sort(key=(layer, priority))
    两者在「Layer 4 的 priority 比 Layer 1 小」时才分道扬镳 ——
    而夹具里正是 `l4_cheap(4, priority=1)`，所以这条坏实现一定会被抓到。
    """
    from engines.base import EngineRegistry

    def broken(self):
        return sorted(self.get_all(), key=lambda e: e.metadata.priority)

    monkeypatch.setattr(EngineRegistry, "get_fallback_chain", broken)

    reds = []
    for label, fn in R.CHECKS["dr-025"]:
        ok, detail = fn()
        if not ok:
            reds.append((label.split("（")[0], detail[:70]))
    names = [r[0] for r in reds]
    assert reds, (
        "把排序换成「只看 priority 且不过滤不可用」，dr-025 四条判据**一条都没红** —— "
        "它们根本没在量排序")
    assert any("(layer, priority)" in n for n in names), (
        "「按 (layer, priority) 升序」那条必须红，实得红的：%s" % names)
    assert any("Layer 1" in n for n in names), (
        "「Layer 1 最前 / Layer 4 最后」那条必须红，实得：%s" % names)
    assert any("is_available" in n for n in names), (
        "「不可用引擎被排除」那条必须红，实得：%s" % names)


# ---------------------------------------------------------------- 证伪 2：中文相关性

def test_d028_checks_go_red_when_relevance_reverts_to_v3_split(monkeypatch):
    """把相关性退回 v3 的 `query.split()` —— dr-028 哪几条会红？

    v3 的做法：把查询按空格切开，逐个找子串；中文查询切出来是整串，
    整串通常不在标题里 → 覆盖度 0。
    """
    import score as sc

    def v3(self, query, title, content):
        if not query:
            return 60.0
        words = [w for w in query.lower().split() if w]
        if not words:
            return 50.0
        cov = sum(1 for w in words if w in (title or "").lower()) / len(words)
        return cov * 100.0

    monkeypatch.setattr(sc.CraapScorer, "_score_relevance", v3)

    reds = [label.split("（")[0] for label, fn in R.CHECKS["dr-028"] if not fn()[0]]
    assert reds, (
        "把相关性退回 v3 的 split() 实现，dr-028 **一条都没红** —— "
        "中文那几条判据根本没在量中文")
    assert any("不依赖空格分词" in n for n in reds), (
        "「不依赖空格分词」那条必须红，实得：%s" % reds)
    assert any("n-gram" in n for n in reds), (
        "「字符级 n-gram」那条必须红，实得：%s" % reds)
    assert any("relevance 评分 > 0" in n for n in reds), (
        "「中文查询评分 > 0」那条必须红，实得：%s" % reds)


# ---------------------------------------------------------------- 证伪 3：effort 优先

def test_d036_checks_go_red_when_depth_wins_over_effort(monkeypatch):
    """把 `--effort` 不再压过 `--depth` —— 「effort 优先」那条必须红。

    坏掉的实现就是去掉 `effort or depth` 的短路，改成 depth 优先：
        raw = depth or effort
    """
    import plan

    # ⚠️ 证伪要打在**期望点名的那个行为**上。
    #    第一版我去改 EFFORT_TO_DEPTH（让 exhaustive 消失），结果
    #    resolve_preset_key 直接抛 ValueError —— 崩的是判据，不是「判红」，
    #    而我的循环没接异常，整个测试 error 而不是给出可读结论。
    #    现在改成把优先级反过来（depth 优先），这才是「effort 优先于 depth」的反面。
    #
    # 顺带：循环里把异常也算红，与 run_evals.main() 的行为对齐
    #（main() 里 except Exception -> 判 FAIL）。不这么做的话，
    # 「判据崩了」和「判据红了」会被混成同一件事。
    real = plan.resolve_preset_key

    def depth_first(effort=None, depth=None):
        raw = depth or effort                 # ← 故意把 depth 放在前面
        if raw is None:
            return "standard"
        key = plan.EFFORT_TO_DEPTH.get(raw, raw)
        if key not in plan.PRESET_KEYS:
            raise ValueError("未知档位 %r" % (raw,))
        return key

    monkeypatch.setattr(plan, "resolve_preset_key", depth_first)

    reds = []
    for label, fn in R.CHECKS["dr-036"]:
        try:
            ok, _detail = fn()
        except Exception as exc:                        # 与 main() 一致：崩了 = 红
            ok = False
            reds.append("%s（判据抛 %s: %s）"
                        % (label.split("：")[0], type(exc).__name__, exc))
            continue
        if not ok:
            reds.append(label.split("：")[0])

    effort_labels = [l for l, _ in R.CHECKS["dr-036"] if "--effort" in l]
    assert effort_labels, "找不到那条「--effort 优先于 --depth」的判据"
    # 按**标签本身**比对，不拿注释里的措辞去匹配 ——
    # 第一版这里写的是 `any("--effort 优先于 --depth" in r ...)`，
    # 而注册表里的标签是「--effort 与 --depth 同给时以 --effort 为准」，
    # 于是证伪明明成功了（那条确实红了）却被判成失败。
    # **断言匹配措辞 = 断言在赌字符串**，措辞一改就假红/假绿。
    assert any(l.split("：")[0] in r for l in effort_labels for r in reds), (
        "把优先级改成 depth 优先之后，那条判据仍然通过 —— 它没在量优先级。红的：%s" % reds)

    # 恢复后必须仍全绿，否则说明证伪用的补丁污染了判据本身
    monkeypatch.setattr(plan, "resolve_preset_key", real)
    assert all(fn()[0] for _l, fn in R.CHECKS["dr-036"]), (
        "恢复实现后 dr-036 仍有判据不通过 —— 证伪用的补丁可能留下了副作用")


def test_d036_breadth_check_go_red_when_table_changes(monkeypatch):
    """把 EFFORT_BREADTH 的值改掉 —— quick/exhaustive 两条形状判据必须红。

    这两条判的是**配置值本身**（子问题数、breadth），
    所以它们只可能靠「值变了才红」被证伪 —— 也就意味着：
    如果有人把 quick 的 breadth 从 2 改成 3（而期望写的是 2），
    这里会抓到。反过来，如果期望和实现一起被改成 3，它们仍然绿 ——
    **那是期望漂移，靠这类判据抓不到，只能靠人盯 evals.json 的 last_updated。**
    """
    import research

    monkeypatch.setattr(research, "EFFORT_BREADTH",
                        {"quick": 9, "standard": 4, "deep": 8, "exhaustive": 3},
                        raising=False)
    reds = [label for label, fn in R.CHECKS["dr-036"] if not fn()[0]]
    assert len(reds) >= 2, (
        "把 quick 的 breadth 改成 9、exhaustive 改成 3 之后，只有 %d 条红（%s）—— "
        "两条形状判据应当都红" % (len(reds), reds))