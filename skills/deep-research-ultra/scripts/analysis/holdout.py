"""留出集的复算入口 —— v6.86 的数字从此可被别人重跑。

## 为什么需要这个文件

v6.84 的教训：**数字只有一半可复算**是"高可复现性配低效度"的典型形态。
样本夹具进了版本控制，但产出结论的分析脚本躺在 gitignore 里，
别人拿到夹具也得自己重写分析，而"重写"未必一致。

v6.86 差点重犯同一个错：CHANGELOG 里写了「非技术域 0/155（0%）」「RAG 对照 96%」
「技术域 81.5%」「查询词锚词性价比 0.8:1」，可产出这些数字的脚本全在 `.research/` 里。
而 `preflight.py` 的 `prov` 检查当时只认 v6.83 —— 硬编码的版本表，
**发现不了新写的实测数字**。这个文件就是把 v6.86 的数字真正钉进去。

## 与 relevance.py 的分工

| 文件 | 回答什么 |
|---|---|
| `analysis/relevance.py` | 在**训练集**上调相关性过滤，锚词增益多少（v6.83） |
| `analysis/holdout.py`  | 锚词表**换到没见过的领域**会怎样，替代方案够不够格（v6.86） |

两者读同一批夹具但问不同问题，所以是两个文件而不是一个 ——
`preflight.py` 的 `single-source` 检查要求同一件事只在一处定义。

## 用法

    python scripts/analysis/holdout.py            # 打印全部数字
    python scripts/analysis/holdout.py --check    # 断言与 CHANGELOG v6.86 一致
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from score import CraapScorer as CS  # noqa: E402

TRAIN = SCRIPTS / "tests" / "fixtures" / "relevance_samples.json"
HOLDOUT = SCRIPTS / "tests" / "fixtures" / "relevance_holdout.json"

TRAIN_GROUPS = ("A-泛词堆", "B-领域词明确", "C-中文主题配英文库",
                "D-工程实践", "E-中文工程")
NONTECH = ("F-金融", "G-医学", "H-法律")
RAG_CTRL = "I-RAG对照"

# 与 CHANGELOG v6.86 对账用。改动这些数字时 CHANGELOG 必须同步改并说明理由。
EXPECTED = {
    "nontech_hit_pct": 0.0,      # 非技术域命中率（0/155）
    "nontech_n": 155,
    "rag_ctrl_hit_pct": 96.2,    # 对照组，证明表本身没坏
    "tech_hit_pct": 81.5,        # 训练集技术域
    "qanchor_p": 87.4,           # 查询词锚词 ≥0.25 的 precision
    "qanchor_r": 88.7,           # 同上的 recall
    "qanchor_ratio": 0.8,        # 性价比，远不如固定表的 4.8
}
TOLERANCE = 0.15

STOP = {'the', 'a', 'an', 'of', 'for', 'and', 'with', 'to', 'in', 'on',
        'using', 'based', 'via', 'is', 'are', 'be', 'by', 'from', 'as',
        'at', 'that', 'this', 'its', 'their', 'new', 'toward', 'towards'}


# ---------------------------------------------------------------------------
# 数据

def load():
    """两个夹具都必须存在 —— 少一个就没法回答"换领域会怎样"。"""
    miss = [p.name for p in (TRAIN, HOLDOUT) if not p.exists()]
    if miss:
        raise SystemExit(f"夹具缺失: {miss}")
    return (json.loads(TRAIN.read_text(encoding="utf-8")),
            json.loads(HOLDOUT.read_text(encoding="utf-8")))


def _rel(r):
    return (r.get("scores") or {}).get("relevance") or 0


def hit_rate(rows):
    """标题命中锚词的比例。"""
    if not rows:
        return 0.0
    return sum(1 for r in rows if CS.topic_anchor_hits(r["title"])) / len(rows)


def group(rows, *names):
    return [r for r in rows if any(n in r.get("groups", []) for n in names)]


# ---------------------------------------------------------------------------
# 已实测否决的替代方案：锚词从查询词导出
# ---------------------------------------------------------------------------
# 保留在库里是因为**否决理由比结论更重要**：下一个 agent 很可能 independently
# 想到同一个办法（它确实更优雅 —— 不用维护表、随查询变），而它的覆盖率数字
# 漂亮得足以骗过人。只留结论不留代码，就会有人重做一遍。

def q_words(query):
    """从查询里取实词：英文按词、中文按 2-gram。"""
    q = (query or "").lower()
    w = [x for x in re.findall(r"[a-z]{2,}", q) if x not in STOP]
    cn = re.findall(r"[\u4e00-\u9fff]", query or "")
    for i in range(len(cn) - 1):
        w.append(cn[i] + cn[i + 1])
    return set(w)


def qanchor_hit(r, thr=0.25):
    words = q_words(r.get("query", ""))
    if not words:
        return False
    t = (r["title"] or "").lower()
    return sum(1 for w in words if w in t) / len(words) >= thr


def _stats(rows, keep):
    """precision / recall。与 relevance.py 同口径。

    `border` 不计入两侧计数：它既不是确定切题也不是确定噪声，
    算进去会把两个指标同时污染。
    """
    sc = [r for r in rows if r.get("manual_label") != "border"]
    tp = sum(1 for r in sc if r["manual_label"] == "on" and keep(r))
    fp = sum(1 for r in sc if r["manual_label"] == "off" and keep(r))
    on = sum(1 for r in sc if r["manual_label"] == "on")
    p = tp / (tp + fp) * 100 if (tp + fp) else 100.0
    rc = tp / on * 100 if on else 100.0
    return p, rc


# ---------------------------------------------------------------------------

def compute():
    train, hold = load()
    train_tech = group(train, *TRAIN_GROUPS)
    nontech = group(hold, *NONTECH)
    rag = group(hold, RAG_CTRL)
    labeled = [r for r in train if r.get("manual_label")]

    p, rc = _stats(labeled, lambda r: _rel(r) >= 50)
    qp, qrc = _stats(labeled,
                     lambda r: _rel(r) >= 50 and qanchor_hit(r, 0.25))

    return {
        "nontech_hit_pct": round(hit_rate(nontech) * 100, 1),
        "nontech_n": len(nontech),
        "rag_ctrl_hit_pct": round(hit_rate(rag) * 100, 1),
        "tech_hit_pct": round(hit_rate(train_tech) * 100, 1),
        "qanchor_p": round(qp, 1),
        "qanchor_r": round(qrc, 1),
        # 性价比 = ΔP / |ΔR|，与 v6.83 用的是同一个口径
        "qanchor_ratio": round((qp - p) / max(abs(qrc - rc), 0.01), 1),
    }


def report(got):
    print("=" * 74)
    print("锚词表换到没见过的领域会怎样（v6.86）")
    print("=" * 74)
    print()
    print(f"  非技术域（金融/医学/法律）  {got['nontech_hit_pct']:>5.1f}%  "
          f"n={got['nontech_n']}")
    print(f"  RAG 对照组                 {got['rag_ctrl_hit_pct']:>5.1f}%")
    print(f"  训练集技术域               {got['tech_hit_pct']:>5.1f}%")
    print()
    print("  对照组高、非技术域 0 —— 表本身没坏，是它不覆盖那些领域。")
    print("  所以非技术主题下开 --strict-anchor 会全军覆没。")
    print()
    print("=" * 74)
    print("已否决的替代方案：锚词从查询词导出")
    print("=" * 74)
    print()
    print(f"  precision {got['qanchor_p']:>5.1f}%   recall {got['qanchor_r']:>5.1f}%"
          f"   性价比 {got['qanchor_ratio']}:1")
    print("  覆盖率漂亮（非技术域 0% → 86~96%），但判别力弱：")
    print("  误杀的 5 条里 4 条是向量数据库产品名 —— 查询是 vector database，")
    print("  而 milvus-io/milvus、weaviate/weaviate 里根本没有这些词。")


def check(got):
    bad = []
    for k, want in EXPECTED.items():
        have = float(got[k])
        if abs(have - float(want)) > TOLERANCE:
            bad.append(f"{k}: CHANGELOG 记 {want}，实算 {have:.3f}")
    if bad:
        print("❌ 与 CHANGELOG 对不上：")
        for b in bad:
            print(f"   {b}")
        print("\n   数字变了可能是三件事之一，**别直接改 CHANGELOG**：")
        print("   ①夹具被换了（那 0/155 这个结论就不成立了）")
        print("   ②锚词表 score.py 变了（那 0% 可能是表坏了，不是设计缺陷）")
        print("   ③判定逻辑变了（先确认是哪个，再改 CHANGELOG 并说明理由）")
        return 1
    print(f"✅ {len(EXPECTED)} 个关键数字与 CHANGELOG v6.86 一致"
          f"（容差 ±{TOLERANCE}，只容忍浮点，不容忍结论退化）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="复算 v6.86 的留出集结论（锚词表的跨领域表现 + 已否决的替代方案）")
    ap.add_argument("--check", action="store_true",
                    help="断言与 CHANGELOG v6.86 记录的数字一致（供测试/过程门调用）")
    a = ap.parse_args(argv)
    got = compute()
    if a.check:
        return check(got)
    report(got)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())