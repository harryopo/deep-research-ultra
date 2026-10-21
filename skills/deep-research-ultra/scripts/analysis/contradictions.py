# -*- coding: utf-8 -*-
"""contradictions —— 矛盾检测与报告结论章的复算入口（v6.106）。

## 为什么要有这个文件

v6.106 实测到两个真缺陷，两个都在「**该报警的时候没报警**」这一侧：

1. **对立结论被合组吞掉**：`verify()` 先按相似度把结论合并，
   再在**合并后的**列表上找对立词。于是同一个工具的两条方向相反的结论
   （"LangChain 生态好" vs "LangChain 性能差"）被判成「同一条结论」→
   合并成一条 → 对立词检测只剩一条陈述，**矛盾检测不到**。
   v6.4 已经为**数值**矛盾修过同款缺陷（加第二个检测器），对立词这一支没跟上。
2. **报告结论章读不懂 claim 的形状**：它只认账本 claim（`text` + `sources`），
   而 research.py 传进去的是 `verify.Claim`（`statement` + `evidence`）→
   正文读成空、来源数读成 0 → **每条结论都被标成「单源待确认」**，
   v6.95 加的「已交叉验证 / 单源待确认」分档等于没生效。

这两个缺陷的共同点：**它们让报告看起来「有矛盾、有分档」，实际是空的。**

## 本脚本量什么

| 量 | 期望 |
|---|---|
| 4 对现实对立结论（用工具词表里的词） | 旧路径 0 条 → 新路径 3 条 |
| 3 对同立场结论 | 两条路径都是 0 条（不许乱报） |
| 2 对子串陷阱（两条都说「不安全」/都说「稳定」） | 两条路径都是 0 条 |
| 报告结论章：2 个来源的 verify.Claim | 「已交叉验证」+ 结论正文（非空） |
| 报告结论章：1 个来源的 verify.Claim | 「单源待确认」+ 结论正文（非空） |

第 4 对对立结论**检不出**是已知边界：它的两条结论共享的核心 token 不足 2 个
（"LangChain 生态好" vs "LangChain 性能坏"），工具**认不出它们在说同一个主体**
——那是合组阈值的问题，不是矛盾检测的问题，本版没动。

## 用法

    python scripts/analysis/contradictions.py            # 打印报告
    python scripts/analysis/contradictions.py --check    # 断言与 CHANGELOG v6.106 一致
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from similarity import group_by_similarity          # noqa: E402
from verify import Claim, CrossVerifier, Evidence, VerificationResult  # noqa: E402

# 对立结论：用工具词表里**有的**词（好/坏、快/慢、稳定/不稳定、推荐/不推荐）
OPPOSITE_PAIRS = [
    ('LangChain 生态好，工具丰富', 'LangChain 性能坏，抽象层笨重'),
    ('vLLM 速度快，吞吐高', 'vLLM 速度慢，显存占用高'),
    ('Milvus 稳定，扩展性强', 'Milvus 不稳定，运维成本高'),
    ('推荐用 DeepResearch 做调研', '不推荐用 DeepResearch 做调研'),
]

# 同立场：不该被报成矛盾
SAME_STANCE = [
    ('LangChain 生态好，工具丰富', 'LangChain 生态好，文档齐全'),
    ('vLLM 速度快，吞吐高', 'vLLM 性能好，吞吐很高'),
    ('Milvus 稳定，扩展性强', 'Milvus 稳定性好，扩展性也强'),
]

# 子串陷阱：'不安全' 含 '安全'、'不推荐' 含 '推荐'
SUBSTRING_TRAPS = [
    ('系统不安全，防护弱', '系统不安全，风险高'),
    ('服务稳定可用', '服务稳定可靠'),
]


def _claims(pairs):
    out = []
    for i, (a, b) in enumerate(pairs):
        out.append(Claim(id='ca%d' % i, statement=a))
        out.append(Claim(id='cb%d' % i, statement=b))
    return out


def _old_path(v: CrossVerifier, claims):
    """v6.106 之前的路径：先合并，再在合并后的列表上找对立。"""
    groups = group_by_similarity([c.statement for c in claims])
    merged = [v._merge_claims([claims[i] for i in g]) for g in groups]
    return len(v._detect_contradictions(merged))


def _new_path(v: CrossVerifier, claims):
    return len(v.verify([], claims=claims).contradictions)


def _report_labels():
    """报告结论章：verify.Claim 的两种来源数各被标成什么。"""
    import report as rp
    from plan import ResearchPlan
    from engines.base import SearchResult
    plan = ResearchPlan(topic='t')
    res = [SearchResult(title='T', url='https://a.example/p', content='c',
                        source='web', score=0.5)]

    def _verdict(n_sources):
        c = Claim(id='c1', statement='有结论正文')
        for i in range(n_sources):
            c.add_evidence(Evidence(source_url='https://x%d.example/p' % i,
                                    source_domain='x%d.example' % i))
        v = VerificationResult(query='q', verified_claims=[c],
                               single_source_claims=[], contradictions=[],
                               total_results=n_sources, total_claims=1,
                               verification_rate=1.0)
        html = rp.generate_report(plan, res, verification=v, format='html')
        return ('已交叉验证' in html, '单源待确认' in html,
                '有结论正文' in html)

    return _verdict(2), _verdict(1)


def compute():
    v = CrossVerifier()
    opp = _claims(OPPOSITE_PAIRS)
    same = _claims(SAME_STANCE)
    trap = _claims(SUBSTRING_TRAPS)
    v2, v1 = _report_labels()
    return {
        "opposite_old": _old_path(v, opp),
        "opposite_new": _new_path(v, opp),
        "same_new": _new_path(v, same),
        "trap_new": _new_path(v, trap),
        "report_two_sources_verified": v2[0],
        "report_two_sources_text": v2[2],
        "report_one_source_single": v1[1],
        "report_one_source_text": v1[2],
    }


# 与 CHANGELOG v6.106 对账用。
EXPECTED = {
    "opposite_old": 0,
    "opposite_new": 3,
    "same_new": 0,
    "trap_new": 0,
    "report_two_sources_verified": True,
    "report_two_sources_text": True,
    "report_one_source_single": True,
    "report_one_source_text": True,
}
TOLERANCE = 0.15


def report(got):
    print("=" * 76)
    print("矛盾检测与报告结论章：v6.106 之前 vs 之后")
    print("=" * 76)
    print(f"  对立结论 4 对      旧路径 {got['opposite_old']} 条 → "
          f"新路径 {got['opposite_new']} 条"
          f"（第 4 对检不出：工具认不出那两条在说同一个主体）")
    print(f"  同立场 3 对        新路径 {got['same_new']} 条（应 0，不许乱报）")
    print(f"  子串陷阱 2 对      新路径 {got['trap_new']} 条（应 0："
          f"「不安全」含「安全」）")
    print()
    print(f"  报告结论章：2 个来源 → 「已交叉验证」={got['report_two_sources_verified']}，"
          f"结论正文非空={got['report_two_sources_text']}")
    print(f"  报告结论章：1 个来源 → 「单源待确认」={got['report_one_source_single']}，"
          f"结论正文非空={got['report_one_source_text']}")
    print()
    print("  修复前：2 个来源的结论被标成「单源待确认」且正文空着 —— "
          "「已交叉验证 / 单源待确认」这个分档等于没生效。")


def check(got):
    bad = []
    for k, want in EXPECTED.items():
        have = got[k]
        if isinstance(want, bool):
            ok = bool(have) == want
        else:
            ok = abs(float(have) - float(want)) <= TOLERANCE
        if not ok:
            bad.append(f"{k}: CHANGELOG 记 {want}，实算 {have}")
    if bad:
        print("❌ 与 CHANGELOG 对不上：")
        for b in bad:
            print("   " + b)
        print("\n   数字变了可能是三件事之一，**别直接改 CHANGELOG**：")
        print("   ① verify.py 的合组/对立逻辑变了 → 那是行为改动，要重新看三组量")
        print("   ② 报告结论章读的 claim 字段变了 → 同样要重看")
        print("   ③ 本脚本的语料变了 → 先看上面三组常量有没有被动过")
        return 1
    print(f"✅ {len(EXPECTED)} 个关键数字与 CHANGELOG v6.106 一致"
          f"（容差 ±{TOLERANCE}，只容忍浮点，不容忍结论退化）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="矛盾检测与报告结论章的复算")
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
