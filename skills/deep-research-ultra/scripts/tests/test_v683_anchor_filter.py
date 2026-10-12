"""v6.83：用 211 条带标注的样本，把"能不能改相关性过滤"从"不敢动"变成有数据的结论。

## 这一版的由来

v6.81 我拒绝了改评分公式，理由是"手上只有 29 条里 3 条标注过的噪声，调权重就是猜"。
那个判断本身没错——**但它停在"不敢动"这种含糊状态，等于把问题挂着**。
这一版建了 211 条带人工标注的样本（五类查询，跨学术/工程/中文），用数据把话说死。

## 数据说了什么

| 规则 | precision | recall |
|---|---|---|
| 现状（relevance >= 50） | 78.8% | 92.0% |
| 只调阈值 relevance >= 55 | 85.3% | 79.2% |
| 只调阈值 relevance >= 65 | 98.8% | 62.4% |
| **relevance >= 50 + 主题锚词命中标题** | **95.3%** | **91.0%** |

调阈值能把 precision 顶上去，但 **recall 崩一半**（92% → 62%）——它杀掉的正是那些
标题不含泛词的好论文。而只加锚词这一道：precision +16.5，recall 只掉 1.0。
滤掉的 20 条里 17 条是真噪声，误杀 1 条（`alibaba/zvec`，标题里没有 "vector"）。

按分项算区分度（AUC，0.5 = 抛硬币）：

- 标题领域词命中数 **0.931**
- relevance 0.872
- total 0.765
- 标题长度 0.674
- authority **0.422** / accuracy **0.431** ← 比抛硬币还差

`authority` / `accuracy` 在当前语料上**根本不携带切题信息**，所以"调权重"是往
没信号的分项上加权。这就是不调权重的理由——不是保守，是有数据。

## 所以做了什么

`score.py` 加 `topic_anchor_hits()`，`research.py` 加 `--strict-anchor`
（**默认关闭**）。默认只报数不动行为，因为锚词是字面命中、有实测天花板：
`Review of: "GeAR: Generation Augmented Retrieval"`（书评、无实质内容）三个锚词全中
仍是噪声。要它动行为得显式开——与本项目「提示不是门」一致。

## 标注本身也被数据推翻了 8 条

跑候选修法时列了「漏网之鱼」，里面有 8 条**我标错了**
（`learnk8s/kubernetes-production-best-practices` 等明确切题的 K8s 仓库，
我按"不在手写白名单里即噪声"判成噪声）。根因是把**举例当全集**。
已更正并保留 `manual_label_v1` / `label_fix` 留痕。详见 fix_labels_round2 那段的说明。

**这本身是本文件最值得记的一条**：标注不是一次过就对的，它需要交叉检查，
而交叉检查要有具体机制——「把候选判据代进去跑一遍，看它和人工标注在哪冲突」
就是这个机制。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

from score import CraapScorer          # noqa: E402
from research import _report_anchor_hits  # noqa: E402

FIXTURE = S / "tests" / "fixtures" / "relevance_samples.json"


def _rows():
    return [r for r in json.loads(FIXTURE.read_text(encoding="utf-8"))
            if r.get("manual_label")]


def _stats(rows, keep):
    """(precision, recall) —— 边缘条目不进任何一侧的计数。"""
    scorable = [r for r in rows if r["manual_label"] != "border"]
    tp = sum(1 for r in scorable if r["manual_label"] == "on" and keep(r))
    fp = sum(1 for r in scorable if r["manual_label"] == "off" and keep(r))
    on = sum(1 for r in scorable if r["manual_label"] == "on")
    return (tp / (tp + fp) * 100 if (tp + fp) else 100.0,
            tp / on * 100 if on else 100.0)


# ---------------------------------------------------------------------------
# 一、样本集本身要可信
# ---------------------------------------------------------------------------

def test_fixture_is_big_enough_to_mean_something():
    """v6.81 拒绝改公式的理由就是"样本太少"。样本量本身得钉住。"""
    rows = _rows()
    assert len(rows) >= 200, f'标注样本 {len(rows)} 条，比 v6.81 时的 29 条没长进'
    for lab in ("on", "off", "border"):
        n = sum(1 for r in rows if r["manual_label"] == lab)
        assert n >= 20, f'{lab} 只有 {n} 条，该类样本不足以支撑统计'
    groups = {r["groups"][0] for r in rows}
    assert len(groups) >= 5, f'只覆盖 {len(groups)} 类查询，跨域结论会不成立'


def test_every_row_has_the_scores_we_reason_about():
    """每条都要带 relevance，否则统计口径和打分管线对不上。"""
    for r in _rows():
        s = r.get("scores") or {}
        assert isinstance(s.get("relevance"), (int, float)), \
            f'缺 relevance：{r["title"][:60]}'
        assert "total" in s, f'缺 total：{r["title"][:60]}'


def test_label_corrections_are_kept_not_silently_overwritten():
    """被更正过的标注必须留痕。

    这条是本文件存在意义的一部分：第一轮有 8 条被我按"不在手写白名单里即噪声"
    判成噪声，实际全是切题的 K8s 仓库。如果更正只覆盖不留痕，后人会以为
    标注一次就对过——而它不是。
    """
    fixed = [r for r in _rows() if r.get("manual_label_fix")]
    assert len(fixed) >= 8, f'只留了 {len(fixed)} 条更正痕迹'
    for r in fixed:
        assert r.get("manual_label_v1") == "off", '更正痕迹里要有原始标注'
        assert '举例当全集' in r.get("manual_label_fix", ""), \
            '更正理由要写明根因，否则后人只看到"改了"不知道改对没有'


# ---------------------------------------------------------------------------
# 二、锚词的判别力（这是"不调权重"的依据）
# ---------------------------------------------------------------------------

def test_anchor_beats_relevance_on_discrimination():
    """标题领域词命中数的区分度必须高于 relevance。

    反向用例：某天把锚词表删了、或改成查摘要（实测 precision 会从 95.3 掉到 90.4），
    这条会立刻报出来。
    """
    rows = [r for r in _rows() if r["manual_label"] in ("on", "off")]

    def auc(fn):
        pos = [fn(r) for r in rows if r["manual_label"] == "on"]
        neg = [fn(r) for r in rows if r["manual_label"] == "off"]
        pos = [x for x in pos if x is not None]
        neg = [x for x in neg if x is not None]
        wins = ties = 0
        for p in pos:
            for n in neg:
                if p > n:
                    wins += 1
                elif p == n:
                    ties += 1
        return (wins + ties / 2) / (len(pos) * len(neg))

    a_anchor = auc(lambda r: len(CraapScorer.topic_anchor_hits(r["title"])))
    a_rel = auc(lambda r: r["scores"]["relevance"])
    assert a_anchor > a_rel, (
        f'锚词 AUC {a_anchor:.3f} 未超过 relevance {a_rel:.3f}——'
        '那就没有理由加锚词而不是调 relevance 的权重')
    assert a_anchor > 0.85, f'锚词 AUC 只有 {a_anchor:.3f}，达不到"明显有判别力"'


def test_authority_and_accuracy_carry_no_topic_signal():
    """authority / accuracy 的 AUC < 0.5 —— 它们没在测切题性。

    这条是**"不调权重"的直接依据**：往没有判别力的分项上加权只会让 total
    更偏离"这条讲的是不是这件事"。哪天这两个分项的 AUC 上来了（换了语料或
    改了算法），这条会红，那才是重新调权重的时候。
    """
    rows = [r for r in _rows() if r["manual_label"] in ("on", "off")]

    def auc(fn):
        pos = [fn(r) for r in rows if r["manual_label"] == "on"]
        neg = [fn(r) for r in rows if r["manual_label"] == "off"]
        wins = ties = 0
        for p in pos:
            for n in neg:
                if p > n:
                    wins += 1
                elif p == n:
                    ties += 1
        return (wins + ties / 2) / (len(pos) * len(neg))

    for field in ("authority", "accuracy"):
        a = auc(lambda r, f=field: r["scores"].get(f))
        assert a < 0.55, (
            f'{field} 的 AUC {a:.3f} 已接近或超过随机——'
            '要么语料变了要么算法变了，该重新评估调权重这条路了')


# ---------------------------------------------------------------------------
# 三、加锚词 vs 只调阈值：必须赢
# ---------------------------------------------------------------------------

def test_anchor_beats_threshold_tuning_on_the_tradeoff():
    """判据是**性价比**：涨的比掉的多。

    ⚠️ 第一版这条断言写错了：我写成"precision 增益必须大于调阈值"，而实测
    调阈值（>=65）precision 增益确实更大（+14.6 vs 锚词的 +11 左右）。
    **那条断言在要求一个假结论**——它等于说"锚词不该存在"，可锚词是实测出来的
    唯一不掉 recall 的做法。真正该比的是「每牺牲 1 点 recall 换回几点 precision」：

        调阈值 >= 65 : +14.6 precision / -30.1 recall  ≈ 0.49 : 1
        锚词         : +11.1 precision / -1.5  recall  ≈ 7.4  : 1

    所以判据改成 dP / |dR| 的比值。这与 v6.81 那句"少报几条不等于报得准"同源：
    只看单边指标会选出一个看起来更好、实际把三分之一切题证据扔掉的方案。
    """
    rows = _rows()

    base = _stats(rows, lambda r: r["scores"]["relevance"] >= 50)
    strict = _stats(rows, lambda r: r["scores"]["relevance"] >= 65)
    anchor = _stats(rows, lambda r: (r["scores"]["relevance"] >= 50
                                     and bool(CraapScorer.topic_anchor_hits(r["title"]))))

    d_p_threshold = strict[0] - base[0]
    d_r_threshold = abs(strict[1] - base[1])
    d_p_anchor = anchor[0] - base[0]
    d_r_anchor = abs(anchor[1] - base[1])

    assert d_r_threshold > 1, (
        f'调阈值的 recall 代价只有 {d_r_threshold:.1f}——'
        '若内容检索变了，本条的取舍依据要重新评估')
    assert d_r_anchor < d_r_threshold / 5, (
        f'锚词的 recall 代价 {d_r_anchor:.1f} 相对调阈值 {d_r_threshold:.1f} '
        '还不够小——性价比没拉开')
    ratio_anchor = d_p_anchor / max(d_r_anchor, 0.01)
    ratio_threshold = d_p_threshold / max(d_r_threshold, 0.01)
    assert ratio_anchor > ratio_threshold * 3, (
        f'性价比 {ratio_anchor:.1f} : {ratio_threshold:.1f} 差距不到 3 倍')

    # 具体量级也别退化。⚠️ 这两个数换过两次，每次都因为发现"之前算的不是真实行为"：
    # ① 第一轮 +16.5 / -1.0 —— 建立在 8 条错标上（明确切题的 K8s 仓库被判噪声）
    # ② 第二轮 +11.1 / -0.8 —— 分析脚本**自己写了一份更大的锚词表**，
    #    而真实生效的是 score.py 那份。两份表看起来都合理，直到把同一个测试
    #    同时挂在两份表上对比才暴露（真实只有 +5.3，因为 score.py 的表里
    #    误收了 'benchmark'——而 benchmark 正是问题本身）。
    # ③ 现在 +11.0 / -2.3：表统一了，'benchmark'/'dataset'/'evaluation'
    #    从锚词表里移除（它们是泛词，留在表里等于给 EEG/珊瑚礁/降水数据集开绿灯）。
    # 三次都往下走了，而结论一次比一次站得住——**降了仍成立**才是可靠的意思。
    assert d_p_anchor > 8, f'锚词 precision 只涨了 {d_p_anchor:.1f}，实测约 +11'
    assert d_r_anchor < 3, f'锚词 recall 掉了 {d_r_anchor:.1f}，实测约 -2.3'


def test_threshold_tuning_alone_is_a_trap():
    """反向钉子：只调阈值会把 recall 打到一半以下。

    留着这条是因为"把阈值调高一点"看起来永远像个安全的好主意。
    实测 relevance >= 65 的 precision 确实能到 98.8%——但 recall 掉到 62.4%，
    也就是**每三条切题的论文里就有两条被扔掉**，而它们的标题只是不含泛词。
    """
    rows = _rows()
    p, r = _stats(rows, lambda x: x["scores"]["relevance"] >= 65)
    assert p > 95, '调阈值的 precision 确实很高——所以这条才需要钉住它的代价'
    assert r < 70, (
        f'relevance >= 65 的 recall 是 {r:.1f}%——'
        '若已明显改善，说明内容检索变了，本条的判断依据要重新评估')


# ---------------------------------------------------------------------------
# 四、默认不过滤（提示不是门）
# ---------------------------------------------------------------------------

def test_strict_anchor_is_opt_in():
    """锚词**默认不过滤**，因为它在样本里同时有两种失效。

    这两条不是构造的用例，是标注样本里真实存在的条目——所以改判据时它们会跟着动：

    - **噪声却命中锚词**（15 条）：`Review of: "GeAR: Generation Augmented Retrieval"`
      三个锚词全中，它是书评、无实质内容；另有 9 条被 `benchmark` 命中
      （EEG 冥想数据集、珊瑚礁视频分割、降水预报数据集…）
    - **切题却没命中锚词**（4 条）：`alibaba/zvec`（16099 star 的真·向量数据库，
      标题里没有 "vector"）、`isrealei/eks-production-infra`（EKS 就是托管 K8s）

    两种失效同时存在，就说明它只配当辅助信号——按本项目惯例默认只报数。
    """
    rows = _rows()
    leak = [r for r in rows if r["manual_label"] == "off"
            and CraapScorer.topic_anchor_hits(r["title"])]
    kill = [r for r in rows if r["manual_label"] == "on"
            and not CraapScorer.topic_anchor_hits(r["title"])]
    assert len(leak) >= 5, f'噪声中命中锚词的只有 {len(leak)} 条，天花板论据变弱了'
    assert len(kill) >= 2, f'切题中未命中锚词的只有 {len(kill)} 条，误杀论据变弱了'
    # 两种失效**同时**存在才是"不能当门"的理由；哪天一边清零了，
    # 就该重新考虑把它升为默认。
    assert leak and kill, (
        '锚词现在只在一侧失效，说明情况变了——该重新评估「默认只报数」这个决定')


def test_default_keeps_unanchored_items(capsys):
    """默认路径：未命中锚词的条目**留在结果里**，只是被报出来。"""
    rows = [r for r in _rows() if not CraapScorer.topic_anchor_hits(r['title'])]
    assert rows, '样本里应该有未命中锚词的条目'

    class _R:
        def __init__(self, t):
            self.title = t

    _report_anchor_hits([_R(r['title']) for r in rows], strict=False)
    out = capsys.readouterr().err
    assert '主题锚词' in out
    assert '仅提示，未过滤' in out
    assert '不命中不等于不相关' in out, (
        '必须说清「未命中 ≠ 不相关」——否则读的人会把这条当过滤结论')


def test_strict_anchor_filter_drops_them():
    """显式开了就真滤——否则 `--strict-anchor` 是个没接上的开关。

    用**样本里真实的那几条**（D 组实跑滤掉的正是它们），不用编造的标题：
    `Site Reliability Engineering…`、`Meta-Engineering Harnesses…`、
    `Deployment Decision Reliability…` 三条都被 `reliability`/`production`
    泛词捞进来，而标题里没有任何 K8s 锚词。
    """
    import research

    class _R:
        def __init__(self, t, rel):
            self.title = t
            self.craap_score = {'relevance': rel}

    results = [
        _R('Kubernetes Deployment Options for On-Prem Clusters', 67.5),
        _R('SAGE -- A Tool for Optimal Deployments in Kubernetes Clusters', 60.0),
        _R('Site Reliability Engineering: Application of Item Response Theory', 61.5),
        _R('Meta-Engineering Harnesses for AI-Native Software Production', 54.0),
        _R('Deployment Decision Reliability: A Generalizability-Theory Framework', 54.0),
    ]
    kept, dropped, _ = research.filter_by_relevance(results, 50, 5, strict_anchor=True)
    titles = [r.title for r in kept]
    assert len(titles) == 2, f'应留 2 条 K8s 的，实留 {len(titles)}：{titles}'
    assert all('Kubernetes' in t for t in titles), f'留下的不是该留的：{titles}'
    assert dropped == 3, f'丢弃数 {dropped}，应为 3'

    # 默认（strict=False）时三条必须留着——这是"提示不是门"的落点
    kept2, dropped2, _ = research.filter_by_relevance(results, 50, 5)
    assert len(kept2) == 5, f'默认把 {5 - len(kept2)} 条误滤了'
    assert dropped2 == 0


def test_short_anchors_use_word_boundary():
    """短锚词必须按词边界判。

    实测：`'rag' in 'Data Storage Engine'` 是 True（sto**rag**e），
    同理 fragment / paragraph / gradient / average 全会误命中——
    一半无关标题会被算成"命中锚词"，这条过滤就成了摆设。
    第一版锚词表没做这层，短词命中的是子串，测试才发现。
    """
    assert not CraapScorer.topic_anchor_hits('Data Storage Engine'), \
        'Storage 里的 rag 被当成了锚词命中'
    assert not CraapScorer.topic_anchor_hits('Fragment Reassembly Algorithm'), \
        'Fragment 里的 rag 被当成了锚词命中'
    assert CraapScorer.topic_anchor_hits('A RAG Evaluation Benchmark'), \
        '真正的 RAG 反而没命中'
