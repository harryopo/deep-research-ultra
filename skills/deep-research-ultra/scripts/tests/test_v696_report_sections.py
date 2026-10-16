# -*- coding: utf-8 -*-
"""v6.96：HTML 报告的章节编号必须自洽，且**别把骨架那套 [N] 约定弄丢**。

## 这一版的由来

v6.95 把 evals.json 变成可执行评测后，`dr-005` 报出两处红：

1. **HTML 章节编号重复** —— `_html_recommendations` 写死 `7. 推荐度评分与排序`，
   `_html_quality` 也写死 `7. 调研质量自评`；而目录里写的是 `8` 和 `9`。
   **三处编号各说各的**，读者按目录跳过去会落在错的章节上。
2. **没有「结论」章、没有「附录」章** —— 执行摘要讲的是「做了什么」，
   不是「所以呢」。对调研产物来说那是读者唯一真正要的一段。

修完补两道门。

## 另一条更贵的教训：量错了渲染器

我第一版把 dr-005 的**全部**判据都挂在 `report.py`（HTML 路径）上，
量出「`[N]` 引用 0 次、报告没有结论」，看着像一组重大发现。

**它是彻底错的。** 本项目有**两条**报告渲染路径：

| | `skeleton.py` | `report.py` |
|---|---|---|
| 输出 | 规范 Markdown | HTML（v4/v5 血统） |
| 来源 | **从证据账本生成** | 从 results/verification 直接渲染 |
| `[N]` 引用 | **有**（按账本 `primary_index`） | 无 |
| 来源登记表 | 有（编号/Tier/标题/URL） | 有引用列表但不是那套 |
| 未验证标记 | `⚠️` + 原因 | 无 |
| 结论章 | `## 结论与建议` | v6.96 补上 |
| 谁审它 | **`validate_report.py`** | 不在任何门的射程内 |

`validate_report.cited_claim_ids(report_md, ...)` 解析的正是骨架那套 `[N]`。
拿 HTML 去量，量到的「0 次」只是因为**那条路径本来就不产出 `[N]`**。

这是本项目**第三次**栽在「量到了别的分支」（v6.91 `verify_quotes.py:113`、
`afb059a` 全文搜索命中文档串）。所以下面有一条门专门钉住骨架路径：
**谁要是把骨架的 `[N]` 弄丢了，这道门会报红**，而 HTML 那边的红它看不见。
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import report as rp                       # noqa: E402
from engines.base import SearchResult      # noqa: E402
from plan import ResearchPlan              # noqa: E402

_QUERY = "retrieval augmented generation evaluation"


def _html(ledger=None, verification=None):
    plan = ResearchPlan(topic=_QUERY)
    res = [
        SearchResult(title="A paper on RAG evaluation",
                     url="https://arxiv.org/abs/2401.00001",
                     content=_QUERY + " " * 30, source="arxiv", score=0.9),
        SearchResult(title="B industry notes", url="https://news.y.com/b",
                     content="industry adoption notes " * 30, source="web", score=0.5),
    ]
    return rp.generate_report(plan, res, verification=verification,
                             format="html", ledger=ledger)


def _h2_numbers(html: str) -> list[str]:
    return re.findall(r"<h2[^>]*>\s*(\d+)\.", html)


def _toc_entries(html: str) -> list[tuple[str, str]]:
    """目录里每一项 -> (编号, 锚点)。

    ⚠️ 正则的分组顺序是 **(锚点, 编号)**。第一版按 `(编号, 锚点)` 解包，
    于是「编号」那一列拿到的是锚点名 —— 断言 `toc_nums == body_nums`
    拿 `['summary','issue-tree',...]` 去比 `['1','2',...]`，必然红。
    而**红的原因不在报告上**。量错东西的时候，先确认被量的那个是不是你以为的那个。
    """
    out = []
    for anchor, num in re.findall(
            r'<li><a href="#([^"]+)">(\d+)\.', html):
        out.append((num, anchor))
    return out


# ======================================================================
# 一、编号与目录自洽
# ======================================================================
def test_h2_numbers_are_unique_and_contiguous_from_one():
    nums = _h2_numbers(_html())
    assert nums, "报告里一个带编号的 h2 都没有 —— 渲染坏了？"
    dup = sorted({n for n in nums if nums.count(n) > 1})
    assert not dup, f"章节编号重复：{dup}（全文序列 {nums}）"
    assert nums == [str(i) for i in range(1, len(nums) + 1)], (
        "章节编号应当是 1..N 连续，实得 %s" % nums)


def test_toc_numbers_match_the_body_and_every_anchor_exists():
    """目录里的编号必须与正文 h2 一致，且**每个锚点在正文里真的存在**。

    v6.96 之前目录写 8/9、正文写 7/7，差一号；附录又以 h4「附录 D」的形式
    挂在别处 —— **三处各说各的**。
    """
    html = _html()
    toc = _toc_entries(html)
    assert toc, "目录里没有条目 —— 目录是不是渲染坏了？"
    body_nums = _h2_numbers(html)
    toc_nums = [n for n, _ in toc]
    assert toc_nums == body_nums, (
        "目录编号 %s 与正文编号 %s 对不上" % (toc_nums, body_nums))
    ids = set(re.findall(r'id="([^"]+)"', html))
    missing = [a for _, a in toc if a not in ids]
    assert not missing, f"目录指向的锚点在正文里不存在：{missing}"


# ======================================================================
# 二、结论与附录两节必须在
# ======================================================================
def test_conclusion_section_exists_and_says_something():
    html = _html()
    assert '<h2 id="conclusion">8. 结论</h2>' in html, "报告缺「8. 结论」章"
    body = html.split('id="conclusion"', 1)[1].split("</h2>", 1)[-1]
    text = re.sub(r"<[^>]+>", " ", body).strip()
    assert len(text) > 20, f"结论章是空的：{text[:80]!r}"


def test_conclusion_does_not_invent_conclusions_without_verification_data():
    """没有验证数据时**不许编结论**。

    这一条是反的：看起来「有结论」比「没结论」更像好产物，
    所以没有数据时编一段才是最容易犯的错。

    判据是**不得出现结论表格**。第一版我断言「已交叉验证 0 条」这句汇总在，
    而实现在没有结论条目时走的是早返回分支、**根本不出汇总** ——
    于是判据红了而代码是对的。**别去断言一句措辞，断言「不该有的东西没出现」。**
    """
    html = _html(verification=None)
    body = html.split('id="conclusion"', 1)[1].split("</h2>", 1)[-1]
    body = body.split('<h2 ', 1)[0]            # 只取结论这一节，别串到下一节
    text = re.sub(r"<[^>]+>", " ", body)
    assert "<table" not in body, (
        "没有 verification 却给出了结论表 —— 那是在编。%s" % body.strip()[:200])
    assert ("没有产出" in text or "未做交叉验证" in text
            or "没有结论" in text), (
        "没有验证数据时应当明说「没有结论」，实得：%s" % text.strip()[:200])


def test_appendix_section_exists_even_without_a_ledger():
    """附录**固定存在** —— 结构忽有忽没有比空着更难读。

    v6.96 之前 `_html_v6_appendix(None)` 直接返回 ''，于是没有账本时
    报告里**根本没有附录**。
    """
    html = _html(ledger=None)
    assert '<h2 id="appendix">10. 附录</h2>' in html, (
        "没有账本时附录整节消失了 —— 读者会以为漏印")


def test_appendix_keeps_the_dangling_appendix_d_suffix_gone():
    """「附录 D」是 v6.0 留下的**悬空编号** —— 报告里从来没有附录 A/B/C。

    它孤零零挂着一个 D。现在它就是本节，那个后缀必须消失。
    """
    import ledger as lg
    root = Path(tempfile.mkdtemp(prefix="v696_led_")) / "ledger"
    L = lg.ResearchLedger(str(root)).init()
    cid = L.add_claim("一条需要分级的结论", "t", "verified", "general", 0.9)["id"]
    L.add_source(cid, "https://arxiv.org/abs/2401.00001", title="A", tier=1)
    L.add_source(cid, "https://news.y.com/b", title="B", tier=4)
    html = _html(ledger=L)
    assert "附录 D" not in html, (
        "「附录 D」这个悬空编号还在 —— 报告里没有附录 A/B/C，它凭什么叫 D")
    assert "来源 Tier 分布" in html, "有账本时附录应列出来源 Tier 分布"


# ======================================================================
# 三、骨架那条路径：别把它弄丢
# ======================================================================
def _skeleton_md() -> str:
    import ledger as lg
    import skeleton as sk
    root = Path(tempfile.mkdtemp(prefix="v696_skel_")) / "ledger"
    L = lg.ResearchLedger(str(root)).init()
    c1 = L.add_claim("检索增强生成在 RAG 系统里显著降低幻觉（已验证）",
                     "rag", "verified", "general", 0.85)["id"]
    c2 = L.add_claim("单源结论：某库默认关闭重排", "rag", "pending", "general", 0.4)["id"]
    L.add_source(c1, "https://arxiv.org/abs/2401.00001", title="A paper", tier=1)
    L.add_source(c1, "https://news.y.com/b", title="B notes", tier=3)
    L.add_source(c2, "https://news.y.com/b", title="B notes", tier=3)
    return sk.build_skeleton(str(root), title="RAG 调研")


def test_skeleton_path_still_emits_n_citations():
    """骨架路径的 `[N]` 是 `validate_report.py` 解析的东西 —— 丢了它整条审计链断掉。

    这条门与上面的 HTML 门**互补而不是重复**：HTML 那边的红它看不见，
    这边的红 HTML 那边的门也看不见。**两条渲染路径必须各钉各的。**
    """
    md = _skeleton_md()
    cites = re.findall(r"\[(\d+)\]", md)
    assert cites, "骨架 Markdown 没有 [N] 引用 —— validate_report 会认为零引用"
    assert len(set(cites)) >= 2, f"[N] 全指向同一个编号？{sorted(set(cites))}"


def test_skeleton_path_keeps_source_registry_and_unverified_marks():
    md = _skeleton_md()
    assert "| 编号 | Tier | 标题 | URL |" in md, "来源登记表表头没了"
    assert "⚠️" in md and "pending" in md, "未验证 claim 的 ⚠️ 与原因标注没了"


def test_the_two_renderers_are_both_alive():
    """**别把其中一条改死**：两条都在，且产出格式不同。

    这条看起来像废话，但 v6.95 就是在「以为只有一条」上栽的 ——
    我在 HTML 上量出「没有 [N] 引用、没有结论」，而那两件事在骨架路径上
    **一直都好好的**。写死这个事实，下次就不会再拿错尺子。
    """
    import skeleton as sk
    md = _skeleton_md()
    html = _html()
    assert md.lstrip().startswith("#"), "骨架路径不再产出 Markdown 了"
    assert html.lstrip().lower().startswith("<!doctype html"), (
        "HTML 路径不再产出 HTML 了")
    assert '[class="mermaid"' not in md and "class=\"mermaid\"" in html, (
        "Mermaid 图表现在在 Markdown 里、或者不在 HTML 里 —— 换渲染器了？")