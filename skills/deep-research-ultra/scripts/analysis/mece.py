# -*- coding: utf-8 -*-
"""mece —— MECE 校验的两个分数与计划读回，复算入口（v6.107）。

## 为什么要有这个文件

给 dr-012 / dr-023 写判据时量出两个真缺陷，都是「**输出看起来有、实际是空的/坏的**」：

1. **overlap_score 是写死的 0.0** —— 它**永远**说「无重叠」，
   而同一个输出里的 `issues` 却在报真实重叠：
   `子问题 '性能对比' 和 '性能基准' 关键词重叠: {'性能', '吞吐'}` + `overlap_score: 0.00`
   —— **同一份输出自相矛盾**。
2. **coverage_score 名不副实** —— 它叫「覆盖度」，算的却是「叶子有没有假设」，
   而 `suggestions` 说的又是另一件事（子问题数量 3-7）。
   规格（dr-023）写的是「覆盖不全时 coverage_score < 1.0 并给出 suggestions」，
   旧实现里这两者**互不相干**。

顺带撞出第三个：**`ResearchPlan.load()` 读回来的计划是坏的** ——
`from_dict` 只还原顶层，嵌套的 `children` 仍是 dict，
任何遍历（`get_all_questions` / `validate_mece` / `to_mermaid`）都会
`AttributeError: 'dict' object has no attribute 'children'`。
旧测试只断言 `loaded.topic`，没碰树，所以一直没露头。

## 本脚本量什么

| 量 | 旧 | 新 |
|---|---|---|
| 有重叠的树 → overlap_score | 0.00（说「无重叠」） | 0.50（与 issues 一致） |
| 有重叠的树 → issues 报重叠 | 有 | 有 |
| 2 个子问题的树 → coverage_score | 1.00（与 suggestions 无关） | 0.00（与 suggestions 一致） |
| 干净树 → overlap / coverage / is_mece | 0.00 / 1.00 / True | 0.00 / 1.00 / True |
| 计划存 JSON 再读回后遍历 | AttributeError | 3 个节点，正常 |
| 读回后子问题的类型 | dict | SubQuestion |

## 用法

    python scripts/analysis/mece.py            # 打印报告
    python scripts/analysis/mece.py --check    # 断言与 CHANGELOG v6.107 一致
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from plan import IssueTree, ResearchPlan  # noqa: E402


def _overlapping_tree():
    """两个子问题关键词重叠（同主体、不同表述）。"""
    t = IssueTree()
    root = t.add_root('向量数据库选型', hypothesis='H0', data_sources=['arxiv'])
    t.add_child(root, '性能对比', hypothesis='H1', data_sources=['arxiv'],
                keywords=['性能', '吞吐', '延迟'])
    t.add_child(root, '性能基准', hypothesis='H2', data_sources=['arxiv'],
                keywords=['性能', '吞吐', 'qps'])
    return t


def _narrow_tree():
    """只有 2 个子问题（规格说 3-7）→ 覆盖不全 + 给出 suggestion。"""
    t = IssueTree()
    root = t.add_root('根', hypothesis='H0', data_sources=['arxiv'])
    t.add_child(root, '甲', hypothesis='H1', data_sources=['arxiv'],
                keywords=['a', 'b', 'c'])
    t.add_child(root, '乙', hypothesis='H2', data_sources=['arxiv'],
                keywords=['d', 'e', 'f'])
    return t


def _clean_tree():
    """3 个互不重叠的子问题，假设与数据源齐备。"""
    t = IssueTree()
    root = t.add_root('根', hypothesis='H0', data_sources=['arxiv'])
    for i, kw in enumerate([['a', 'b', 'c'], ['d', 'e', 'f'], ['g', 'h', 'i']]):
        t.add_child(root, '子%d' % i, hypothesis='H%d' % i,
                    data_sources=['github'], keywords=kw)
    return t


def _plan_roundtrip():
    """计划存 JSON 再读回，然后**遍历**它（旧实现在这里就崩）。"""
    t = IssueTree()
    root = t.add_root('主题', hypothesis='H0', data_sources=['arxiv'])
    mid = t.add_child(root, '子问题', hypothesis='H1', data_sources=['github'])
    t.add_child(mid, '孙问题', hypothesis='H2', data_sources=['arxiv'])
    p = ResearchPlan(topic='主题', issue_tree=[root])
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / 'research_plan.json')
        p.save(path)
        back = ResearchPlan.load(path)
        try:
            n = len(back.get_all_questions())
            kind = type(back.issue_tree[0].children[0]).__name__
            return n, kind, ''
        except Exception as exc:                       # noqa: BLE001
            return 0, '?', '%s: %s' % (exc.__class__.__name__, exc)


def compute():
    ov = _overlapping_tree().validate_mece()
    nar = _narrow_tree().validate_mece()
    cln = _clean_tree().validate_mece()
    n, kind, err = _plan_roundtrip()
    return {
        "overlap_score": round(ov['overlap_score'], 3),
        "overlap_issue_reported": any('关键词重叠' in i for i in ov['issues']),
        "narrow_coverage": round(nar['coverage_score'], 3),
        "narrow_suggestions": len(nar['suggestions']),
        "clean_overlap": round(cln['overlap_score'], 3),
        "clean_coverage": round(cln['coverage_score'], 3),
        "clean_is_mece": bool(cln['is_mece']),
        "roundtrip_nodes": n,
        "roundtrip_child_type": kind,
        "roundtrip_error": err,
    }


# 与 CHANGELOG v6.107 对账用。
EXPECTED = {
    "overlap_score": 0.5,
    "overlap_issue_reported": True,
    "narrow_coverage": 0.0,
    "narrow_suggestions": 1,
    "clean_overlap": 0.0,
    "clean_coverage": 1.0,
    "clean_is_mece": True,
    "roundtrip_nodes": 3,
    "roundtrip_child_type": "SubQuestion",
    "roundtrip_error": "",
}
TOLERANCE = 0.15


def report(got):
    print("=" * 74)
    print("MECE 校验的两个分数 + 计划读回（v6.107）")
    print("=" * 74)
    print(f"  有重叠的树    overlap_score={got['overlap_score']}，"
          f"issues 报了重叠={got['overlap_issue_reported']}"
          f"（修复前 overlap 恒为 0.0，与 issues 自相矛盾）")
    print(f"  只有 2 个子问题 coverage_score={got['narrow_coverage']}，"
          f"suggestions {got['narrow_suggestions']} 条（修复前是 1.00，与 suggestions 无关）")
    print(f"  干净的树      overlap={got['clean_overlap']}、"
          f"coverage={got['clean_coverage']}、is_mece={got['clean_is_mece']}")
    print(f"  计划读回      节点 {got['roundtrip_nodes']} 个，"
          f"子问题类型 {got['roundtrip_child_type']}"
          f"{('，错误：' + got['roundtrip_error']) if got['roundtrip_error'] else ''}")
    print()
    print("  修复前：读回的计划里 children 仍是 dict —— 任何遍历都会 AttributeError。")


def check(got):
    bad = []
    for k, want in EXPECTED.items():
        have = got[k]
        if isinstance(want, bool):
            ok = bool(have) == want
        elif isinstance(want, str):
            ok = str(have) == want
        else:
            ok = abs(float(have) - float(want)) <= TOLERANCE
        if not ok:
            bad.append(f"{k}: CHANGELOG 记 {want}，实算 {have}")
    if bad:
        print("❌ 与 CHANGELOG 对不上：")
        for b in bad:
            print("   " + b)
        print("\n   数字变了可能是三件事之一，**别直接改 CHANGELOG**：")
        print("   ① plan.py 的两个分数算法变了 → 那是行为改动，要重看这三组量")
        print("   ② from_dict 的还原方式变了 → 同上")
        print("   ③ 本脚本的语料变了 → 先看上面三个建树函数有没有被动过")
        return 1
    print(f"✅ {len(EXPECTED)} 个关键数字与 CHANGELOG v6.107 一致"
          f"（容差 ±{TOLERANCE}，只容忍浮点，不容忍结论退化）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="MECE 分数与计划读回的复算")
    ap.add_argument("--check", action="store_true",
                    help="断言与 CHANGELOG 记录的数字一致（供测试/过程门调用）")
    a = ap.parse_args(argv)
    got = compute()
    if a.check:
        return check(got)
    report(got)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
