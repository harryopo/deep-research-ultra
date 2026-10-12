"""relevance — 从标注样本算相关性过滤的 precision / recall / AUC。

## 为什么这个脚本要进版本控制（v6.84）

CHANGELOG 里那些数字（precision 84.2%→95.2%、recall 92.5%→90.2%、
AUC 0.937）在写下来的那一刻是**不可复算的**：样本夹具进了版本控制，
而产出它们的脚本躺在 gitignore 的 `.research/` 里。别人拿到夹具也得自己
重写一遍分析，而"重写"的结果未必一致。

这正是 `docs/dev/v6.84-过程门与文献依据.md` 里记的状态：**高可复现性
（我记得那些数字）配低有效度（没人能重跑）**。对应 "Reliability without
Validity"（2606.19544）描述的一致性–偏置悖论。

文献给的出路是 addressability —— 把断言挂在一个**可复算的外部物件**上。
这个脚本就是那个物件：`python relevance.py` 应当吐出与 CHANGELOG 一致的数字。

## 用法

    python scripts/analysis/relevance.py            # 打印报告
    python scripts/analysis/relevance.py --check    # 断言与 CHANGELOG 一致（供测试）

数据来自 `tests/fixtures/relevance_samples.json`（211 条，人工标注）。

## 标注的性质

`manual_label` 是**我做的判断**，不是客观真值。它的价值在于判断被固定下来、
可复算、可被别人复核——每条都带 query / engine / title / snippet / 全部分项分数，
不同意某条就能改，改完重跑即可。样本里有 8 条 `manual_label_fix` 留痕：
第一轮我把 8 个明确切题的 K8s 仓库判成了噪声（"不在我手写白名单里即噪声"
= 把举例当全集），是跑候选修法时它们命中领域词却判噪声的冲突暴露出来的。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from score import CraapScorer as CS  # noqa: E402

FIXTURE = SCRIPTS / "tests" / "fixtures" / "relevance_samples.json"

# 与 CHANGELOG v6.83 对账用。改动这些数字时，CHANGELOG 必须同步改并说明理由。
EXPECTED = {
    "baseline_precision": 84.2,
    "baseline_recall": 92.5,
    "anchor_precision": 95.2,
    "anchor_recall": 90.2,
    "threshold65_precision": 98.8,
    "threshold65_recall": 62.4,
    "auc_anchor": 0.937,
    "auc_relevance": 0.872,
    "n_total": 211,
}
TOLERANCE = 0.15          # 只容忍浮点与四舍五入，不容忍结论退化


def load():
    return [r for r in json.loads(FIXTURE.read_text(encoding="utf-8"))
            if r.get("manual_label")]


def _rel(r):
    v = r["scores"]["relevance"]
    return v if isinstance(v, (int, float)) else 0.0


def stats(rows, keep):
    """(precision, recall)。`border` 不进任何一侧的计数——塞进任一侧都会让数字好看。"""
    sc = [r for r in rows if r["manual_label"] != "border"]
    tp = sum(1 for r in sc if r["manual_label"] == "on" and keep(r))
    fp = sum(1 for r in sc if r["manual_label"] == "off" and keep(r))
    on = sum(1 for r in sc if r["manual_label"] == "on")
    return (tp / (tp + fp) * 100 if (tp + fp) else 100.0,
            tp / on * 100 if on else 100.0)


def auc(rows, fn):
    """随机取一条噪声与一条切题，fn 给切题更高分的概率。0.5 = 抛硬币。"""
    pos = [fn(r) for r in rows if r["manual_label"] == "on"]
    neg = [fn(r) for r in rows if r["manual_label"] == "off"]
    pos = [x for x in pos if x is not None]
    neg = [x for x in neg if x is not None]
    if not pos or not neg:
        return 0.5
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return (wins + ties / 2) / (len(pos) * len(neg))


def compute(rows):
    base = stats(rows, lambda r: _rel(r) >= 50)
    thr65 = stats(rows, lambda r: _rel(r) >= 65)
    anchor = stats(rows, lambda r: _rel(r) >= 50
                   and bool(CS.topic_anchor_hits(r["title"])))
    scorable = [r for r in rows if r["manual_label"] in ("on", "off")]
    return {
        "baseline_precision": base[0], "baseline_recall": base[1],
        "threshold65_precision": thr65[0], "threshold65_recall": thr65[1],
        "anchor_precision": anchor[0], "anchor_recall": anchor[1],
        "auc_anchor": auc(scorable, lambda r: len(CS.topic_anchor_hits(r["title"]))),
        "auc_relevance": auc(scorable, lambda r: r["scores"]["relevance"]),
        "auc_authority": auc(scorable, lambda r: r["scores"].get("authority")),
        "auc_accuracy": auc(scorable, lambda r: r["scores"].get("accuracy")),
        "n_total": len(rows),
    }


def report(rows, got):
    print("=" * 78)
    print(f"相关性过滤实测（{got['n_total']} 条人工标注样本，来源 "
          f"tests/fixtures/relevance_samples.json）")
    print("=" * 78)
    print(f"  {'规则':<34} {'precision':>10} {'recall':>8}")
    print("  " + "-" * 56)
    print(f"  {'现状 relevance>=50':<34} {got['baseline_precision']:>9.1f}% "
          f"{got['baseline_recall']:>7.1f}%")
    print(f"  {'只调阈值 relevance>=65':<34} {got['threshold65_precision']:>9.1f}% "
          f"{got['threshold65_recall']:>7.1f}%")
    print(f"  {'+ 主题锚词命中标题 (=--strict-anchor)':<34} "
          f"{got['anchor_precision']:>9.1f}% {got['anchor_recall']:>7.1f}%")

    dpt = got["threshold65_precision"] - got["baseline_precision"]
    drt = got["baseline_recall"] - got["threshold65_recall"]
    dpa = got["anchor_precision"] - got["baseline_precision"]
    dra = got["baseline_recall"] - got["anchor_recall"]
    print()
    print(f"  调阈值  : precision {dpt:+.1f} / recall {-drt:+.1f}  "
          f"性价比 {dpt / max(drt, .01):.2f} : 1")
    print(f"  加锚词  : precision {dpa:+.1f} / recall {-dra:+.1f}  "
          f"性价比 {dpa / max(dra, .01):.2f} : 1")
    print("  （调阈值把 precision 顶上去，但 recall 掉一半——"
          "它杀掉的是标题不含泛词的好论文）")

    print()
    print("=" * 78)
    print("各分项的判别力（AUC，0.5 = 抛硬币）")
    print("=" * 78)
    print(f"  标题锚词命中数   {got['auc_anchor']:.3f}")
    print(f"  relevance        {got['auc_relevance']:.3f}")
    print(f"  authority        {got['auc_authority']:.3f}"
          + ("   ← 低于随机，不携带切题信息" if got["auc_authority"] < 0.5 else ""))
    print(f"  accuracy         {got['auc_accuracy']:.3f}"
          + ("   ← 低于随机，不携带切题信息" if got["auc_accuracy"] < 0.5 else ""))
    print()
    print("  authority / accuracy 低于随机，是「不调权重」的直接依据："
          "往没有判别力的分项上加权只会让 total 更偏离「这条讲的是不是这件事」。")

    labels = {}
    for r in rows:
        labels[r["manual_label"]] = labels.get(r["manual_label"], 0) + 1
    leak = sum(1 for r in rows if r["manual_label"] == "off"
               and CS.topic_anchor_hits(r["title"]))
    kill = sum(1 for r in rows if r["manual_label"] == "on"
               and not CS.topic_anchor_hits(r["title"]))
    print()
    print("=" * 78)
    print("锚词为什么默认只报数不过滤")
    print("=" * 78)
    print(f"  标注分布: {labels}")
    print(f"  噪声却命中锚词（滤不掉）: {leak} 条")
    print(f"  切题却没命中锚词（会误杀）: {kill} 条")
    print("  两边同时存在 → 它只能当辅助信号，要它动行为得显式 --strict-anchor。")


def check(rows, got):
    bad = []
    for k, want in EXPECTED.items():
        have = got[k]
        if abs(float(have) - float(want)) > TOLERANCE:
            bad.append(f"{k}: CHANGELOG 记 {want}，实算 {have:.3f}")
    if bad:
        print("❌ 与 CHANGELOG 对不上：")
        for b in bad:
            print("   " + b)
        print("\n   数字变了可能是三件事之一，**别直接改 CHANGELOG**：")
        print("   ① 样本或标注变了 → 先看 manual_label_fix 有没有新增留痕")
        print("   ② score.py 的锚词表变了 → 那是行为改动，需要单独的判断与说明")
        print("   ③ 分析口径变了 → 在本文件里写明为什么")
        return 1
    print(f"✅ {len(EXPECTED)} 个关键数字与 CHANGELOG v6.83 一致"
          f"（容差 ±{TOLERANCE}，只容忍浮点，不容忍结论退化）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="相关性过滤的 precision/recall/AUC 实测")
    ap.add_argument("--check", action="store_true",
                    help="断言与 CHANGELOG v6.83 记录的数字一致（供测试调用）")
    a = ap.parse_args(argv)
    rows = load()
    got = compute(rows)
    if a.check:
        return check(rows, got)
    report(rows, got)
    return 0


if __name__ == "__main__":
    sys.exit(main())
