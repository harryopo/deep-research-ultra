"""v6.86：用留出集给 `--strict-anchor` 的默认值定案，并否决一个替代方案。

## 为什么必须有这一版

v6.83 靠 211 条训练样本把 `--strict-anchor` 定成「默认关闭，只报数」，
理由是样本里两种失效并存。但那是**我自己用来调锚词表的样本**——
在它上面量出来的任何数字都是乐观估计，而"两种失效并存"这个观察
也完全可能只是技术域特有的现象。所以默认值一直悬着。

这一版采了**留出集**：207 条，锚词表定稿之后才采的，其中三个领域
**锚词表完全没覆盖**（金融 / 医学 / 法律）。那才是真正的风险 ——
表里全是 RAG / K8s / 向量库的技术词，用户查别的领域时它会做什么？

## 结论一：固定锚词表在它不知道的领域是灾难

| 组 | n | 锚词命中 | relevance>=50 |
|---|---|---|---|
| F-金融（可转债定价） | 52 | **0/52 (0%)** | 36 |
| G-医学（肺癌 CT 筛查） | 52 | **0/52 (0%)** | 50 |
| H-法律（法条解释） | 51 | **0/51 (0%)** | 34 |
| I-RAG对照 | 52 | 50/52 (96%) | 41 |

训练集技术域 81.5% vs 留出集非技术域 **0.0%（0/155）**。

逐条看了非技术域 relevance>=50 的前 14 条 ×3 组：**全部明显切题**
（`Pricing Convertible Bonds…` rel=100、`Early Detection of Lung Cancer…`
rel=100、`Statutory Interpretation…` rel=100），锚词命中 0。

所以若 `--strict-anchor` 默认开启，用户查金融/医学/法律会**全军覆没**：
噪声是多了几条错材料，全军覆没是**一份报告都产不出**。

**这不是"表不够大、该补词"**：金融/医学/法律各自有几百个专业术语，
补不完，而任何用户主题都可能落在表外。问题在设计——
拿一张固定的技术词表当全局过滤器，判据的适用域比它要解决的问题窄得多。

## 结论二：替代方案（锚词从查询词导出）被判据否掉了

思路：既然 `--source-query` 已经把「这次真要用的词」显式交给引擎了，
那"结果里有没有这个词"就是天然随查询变化的判据，不用维护表。
覆盖率上它很漂亮——非技术域从 0% 变成 86~96%。

但按 v6.83 定下的口径（precision 与 recall 一起看、只比性价比、
逐条看滤掉的是什么），它在训练集上**性价比只有 0.8:1，
远不如固定表的 4.9:1**：

| 判据 | P | R | 性价比 |
|---|---|---|---|
| 现状 relevance>=50 | 84.2% | 92.5% | — |
| + 固定锚词表 | 95.2% | 90.2% | **4.9 : 1** |
| + 查询词锚词 >=0.25 | 87.4% | 88.7% | 0.8 : 1 |

误杀的 5 条里 **4 条是向量数据库产品名**：`milvus-io/milvus`、
`weaviate/weaviate`、`alibaba/zvec`、`codediodeio/rektor-db`。
查询是 `vector database`，而仓库名里没有 "vector"，`weaviate/weaviate`
连 "database" 都没有。

## 两者缺陷互补，没有一方单独够用

- 固定表：**在它知道的领域强（4.9:1），在不知道的领域是灾难（0%）**
- 查询词锚词：**在任何领域都安全（86~96%），但判别力弱（0.8:1）**

所以这一版的处置**不是**把默认值改成"开"或"关"，而是：

1. `--strict-anchor` 保持**默认关闭** —— 现在有了留出集的证据，
   而不是只有"样本里有两种失效"这种含糊理由
2. 输出里**明说它在哪些领域不适用**：命中率过低时提示
   "锚词表可能不覆盖你这个主题，别把未命中当成不相关"
   ——这条从 v6.83 就有，现在有了数据支撑，且必须显眼
3. 记录查询词锚词这个**已实测否决的替代方案**，含否决理由，
   避免下一个 agent 重做一遍

**没做的**：没有把两张表并起来当一张。它们的缺陷来源不同
（一个是覆盖不全、一个是判别力弱），并起来既解决不了覆盖问题，
又会削弱判别力——那属于拍脑袋，没有实测支撑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

from score import CraapScorer as CS  # noqa: E402

TRAIN = S / "tests" / "fixtures" / "relevance_samples.json"
HOLDOUT = S / "tests" / "fixtures" / "relevance_holdout.json"

TRAIN_GROUPS = ("A-泛词堆", "B-领域词明确", "C-中文主题配英文库",
                "D-工程实践", "E-中文工程")
NONTECH_GROUPS = ("F-金融", "G-医学", "H-法律")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _rate(rows):
    if not rows:
        return 0.0
    return sum(1 for r in rows if CS.topic_anchor_hits(r["title"])) / len(rows)


# ---------------------------------------------------------------------------
# 一、留出集：固定表在非技术域是灾难
# ---------------------------------------------------------------------------

def test_holdout_fixtures_exist_and_cover_nontech():
    """留出集必须含锚词表**没覆盖**的领域，否则测不出真正的风险。

    判据是**组名**而不是"看起来像别的领域"：那三个组是刻意选的
    金融 / 医学 / 法律，各自有几百个专业术语，补不完，
    而任何用户主题都可能落在表外。
    """
    hold = _load(HOLDOUT)
    for g in NONTECH_GROUPS + ("I-RAG对照",):
        sel = [r for r in hold if g in r["groups"]]
        assert len(sel) >= 30, f'{g} 只有 {len(sel)} 条，留出集该有 50 条上下'
    assert len(hold) >= 150, f'留出集 {len(hold)} 条，太少'


def test_anchor_table_misses_every_nontech_result():
    """锚词表在非技术域命中率必须是 0 —— 这是本版的核心事实。

    逐条人工核过：F/G/H 三组 relevance>=50 的前 14 条全部明显切题
    （`Pricing Convertible Bonds…` rel=100、`Early Detection of Lung
    Cancer…` rel=100、`Statutory Interpretation…` rel=100）。
    它们全被判"未命中"，只是因为表里全是技术词。

    这条钉住的是**设计缺陷的量化**，不是行为。若哪天有人把锚词表扩到
    覆盖金融/医学/法律，这条会红——那时该重新评估是不是还有别的领域
    没覆盖（一定有），而不是以为问题解决了。
    """
    hold = _load(HOLDOUT)
    nontech = [r for r in hold if any(g in r["groups"] for g in NONTECH_GROUPS)]
    rate = _rate(nontech)
    assert len(nontech) >= 100, f'非技术域样本 {len(nontech)} 条太少'
    assert rate < 0.05, (
        f'非技术域命中率 {rate * 100:.1f}%——锚词表被扩了？'
        '请重新评估：扩表只是把问题推到下一个未覆盖的领域，'
        '本条的判据就是提醒这一点')


def test_anchor_table_works_on_tech_domain():
    """反向对照：同一张表在它知道的领域必须仍然有效。

    没有这条，只看"非技术域 0%"会误以为锚词表整体没用。
    """
    train = _load(TRAIN)
    tech = [r for r in train if any(g in r["groups"] for g in TRAIN_GROUPS)]
    assert _rate(tech) > 0.6, f'技术域命中率 {_rate(tech) * 100:.1f}%，判别力塌了'


def test_rag_control_group_confirms_the_table_itself_works():
    """I 组是 RAG 对照：同一批新查询，表在 RAG 上仍然命中 96%。

    这条把「表坏了」和「表不覆盖那个领域」区分开——
    I 组是**新采的**（留出集里），不是训练集里的旧数据。
    """
    hold = _load(HOLDOUT)
    rag = [r for r in hold if "I-RAG对照" in r["groups"]]
    assert _rate(rag) > 0.8, (
        f'RAG 对照组命中 {_rate(rag) * 100:.1f}%——表本身失效了，'
        '那与非技术域 0% 是两个不同的问题')


# ---------------------------------------------------------------------------
# 二、默认值：维持关闭，但理由从"样本里有两种失效"升级为留出集证据
# ---------------------------------------------------------------------------

def test_strict_anchor_still_defaults_off():
    """`--strict-anchor` 必须保持 **store_true（默认关闭）**。

    v6.83 的理由是"训练样本里两种失效并存"——那是**我自己用来调表的样本**，
    属于乐观估计。本版换成了更强的理由：留出集里非技术域命中率精确为 0，
    默认开启会让那些领域的调研**全军覆没**。

    一份产不出来的报告，比一份多了几条错材料的报告严重得多。
    """
    src = (S / "research.py").read_text(encoding="utf-8")
    assert "'--strict-anchor', action='store_true'" in src, \
        '--strict-anchor 不能有默认值；默认开启会在未覆盖领域全军覆没'
    assert "strict_anchor: bool = False" in src, \
        'filter_by_relevance 的 strict_anchor 参数默认值必须是 False'


def test_low_anchor_hit_rate_warns_that_the_table_may_not_apply():
    """命中率过低时必须显眼地提示「表可能不覆盖你这个主题」。

    这是本版真正新增的**行为**。锚词表在非技术域是 0%，
    而 v6.83 那句「不命中不等于不相关」太温和了——
    用户看到「52 条里 0 条命中」需要立刻知道**不是结果有问题，是判据不适用**，
    否则会以为检索没跑出东西。

    判据要求：提示里必须同时出现"不命中不等于不相关"和"表可能不覆盖"
    两层意思，只说前者不够。
    """
    import io
    from contextlib import redirect_stderr

    from research import _report_anchor_hits

    class _R:
        def __init__(self, t):
            self.title = t

    # 模拟非技术域：全部未命中
    buf = io.StringIO()
    with redirect_stderr(buf):
        _report_anchor_hits([_R(f"Paper {i} About Something Else") for i in range(20)])
    out = buf.getvalue()
    assert '不命中不等于不相关' in out, (
        f'低命中时原有那句「不命中不等于不相关」也要在——新警告是**叠加**，'
        f'不是替换。实测输出：{out}')
    assert '可能不覆盖' in out or '不适用' in out, (
        f'命中率极低时必须说清「表可能不覆盖这个主题」，实测输出：{out}')
    # 「给出下一步动作」的可测代理是**明确劝阻**：文案里的建议是别开
    # --strict-anchor。只检查泛泛的祈使词（「别当成」）会被改写文案轻易绕过。
    assert '--strict-anchor' in out and ('别' in out or '不要' in out), (
        f'必须给出明确的下一步动作，而不只是陈述。实测输出：{out}')


def test_moderate_hit_rate_does_not_emit_the_scare_warning():
    """反向测试：命中率正常时**不得**出现「表不覆盖你这个主题」。

    没有这条，低命中警告很容易被写成无条件打印——那样每次检索都在喊
    「警告」，等于没警告。判据用真实锚词词，让命中率落在 25%~75% 区间。
    """
    import io
    from contextlib import redirect_stderr

    from research import _report_anchor_hits

    class _R:
        def __init__(self, t):
            self.title = t

    # 一半命中 'retrieval'（锚词表里的真词），一半不含任何锚词
    rows = [_R(f"retrieval paper {i}") if i % 2 == 0
            else _R(f"Paper {i} About Something Else")
            for i in range(20)]
    buf = io.StringIO()
    with redirect_stderr(buf):
        _report_anchor_hits(rows)
    out = buf.getvalue()
    assert '不覆盖' not in out and '不适用' not in out, (
        f'命中率 50% 时不该报「表不覆盖主题」——警告不能无条件触发。'
        f'实测输出：{out}')
    # 但原有的未命中说明要在
    assert '不命中不等于不相关' in out, f'部分命中时仍需原说明，实测输出：{out}'


def test_high_hit_rate_emits_neither_warning():
    """全命中时不报未命中说明，也不报覆盖警告。"""
    import io
    from contextlib import redirect_stderr

    from research import _report_anchor_hits

    class _R:
        def __init__(self, t):
            self.title = t

    rows = [_R(f"retrieval augmented generation {i}") for i in range(20)]
    buf = io.StringIO()
    with redirect_stderr(buf):
        _report_anchor_hits(rows)
    out = buf.getvalue()
    assert '未命中的' not in out, f'全命中时不该报未命中，实测输出：{out}'
    assert '不覆盖' not in out, f'全命中时不该报覆盖警告，实测输出：{out}'


# ---------------------------------------------------------------------------
# 三、v6.86 的数字必须真的可复算（这版差点重犯 v6.84 的错）
# ---------------------------------------------------------------------------

def test_holdout_numbers_are_reproducible_from_a_versioned_script():
    """CHANGELOG 里那些留出集数字，必须有一支受版本控制的脚本能重跑。

    **这正是 v6.84 批过的毛病，而 v6.86 第一版又犯了一次**：
    CHANGELOG 写了「非技术域 0/155」「RAG 对照 96%」「性价比 0.8:1」，
    产出它们的脚本却全在 gitignore 的 `.research/` 里 —— 数字只有一半可复算。
    `relevance.py` 入库就是为了消掉这个毛病；v6.86 必须同样处理。
    """
    import subprocess

    import analysis.holdout as H

    p = S / "analysis" / "holdout.py"
    assert p.exists(), "留出集分析链必须入库，否则 v6.86 的结论不可复算"
    changelog = S.parents[2] / "CHANGELOG.md"
    assert "实测" in changelog.read_text(encoding="utf-8"), \
        "CHANGELOG 应记录这些实测数字"

    r = subprocess.run([sys.executable, str(p), "--check"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(S))
    assert r.returncode == 0, f'holdout.py --check 没过：\n{r.stdout}\n{r.stderr}'

    # 实算值必须与 CHANGELOG 对得上，不只是脚本存在
    got = H.compute()
    assert got["nontech_hit_pct"] == 0.0, \
        f'非技术域命中率应精确为 0，实算 {got["nontech_hit_pct"]}'
    assert got["nontech_n"] == 155, f'非技术域样本应为 155，实算 {got["nontech_n"]}'
    assert got["rag_ctrl_hit_pct"] > 90, \
        f'对照组应 >90%（证明表本身没坏），实算 {got["rag_ctrl_hit_pct"]}'


def test_rejected_alternative_stays_in_the_repo_with_its_reason():
    """已否决的替代方案要连**代码**一起留，不只留结论。

    只留结论的话，下一个 agent 很可能 independently 想到同一个办法
    （它确实更优雅：不用维护表、随查询变），而它的覆盖率数字漂亮得
    足以骗过人 —— 实测非技术域覆盖 0%→86~96%，看着像是解决了大问题。
    只有留下代码 + 否决理由，才不会再做一遍。
    """
    import analysis.holdout as H

    assert hasattr(H, "qanchor_hit"), "查询词锚词的实现要留在库里"
    src = (S / "analysis" / "holdout.py").read_text(encoding="utf-8")
    assert "否决" in src, "留代码必须同时留否决理由，否则下一个人会当成候选方案"
    for token in ("milvus", "weaviate"):
        assert token in src, (
            f'否决理由里要点名 {token} —— "覆盖率好但误杀产品名"是抽象的，'
            f'具体仓库名才拦得住下一个人')


def test_provenance_gate_discovers_unregistered_measured_versions():
    """`prov` 必须**扫** CHANGELOG，不能只查已登记的那几项。

    漏洞就在这儿：v6.86 第一版的 `PROVENANCE` 是硬编码的，只认 v6.83.0。
    我在 CHANGELOG 里新写了一整节实测数字，它一声不响，检查照样全绿——
    而"没人提醒要登记"正是这个项目反复吃的那种亏。
    """
    from preflight import _sections_with_measured

    fake = """
## v6.90.0（2026-10-13）— 新的一版

实测命中率 12.5%，对照组 88.0%。

## v6.89.0（2026-10-13）— 没有实测也没有小数

就是改了个说法。
"""
    found = _sections_with_measured(fake)
    assert "v6.90.0" in found, f'带实测数字的新版本段必须被扫出来，实得 {found}'
    assert "v6.89.0" not in found, (
        f'没有实测、没有小数的版本段不该被扫进来（否则会误报），实得 {found}')


def test_provenance_baseline_is_a_constant_not_the_current_version():
    """BASELINE 必须是写死的常量，不能是"当前版本"。

    否则每升一版就等于又豁免了一版，那道门会随版本号一起失效——
    而且失效得很安静。这条钉的是**规则本身**，不是当前行为。
    """
    import preflight

    assert preflight.BASELINE == (6, 84, 0), (
        f'BASELINE 被改成了 {preflight.BASELINE}——过程门是从 v6.84.0 起生效的，'
        f'改它等于追溯豁免一整段历史')
    # 豁免项必须都带理由，否则「忘记登记」与「有理由豁免」分不开
    for ver, why in preflight.EXEMPT.items():
        assert why and len(why) > 8, f'{ver} 的豁免没写理由'


def test_v686_is_actually_registered_not_merely_exempted():
    """v6.86.0 必须真的登记了复算脚本，而不是被豁免掉。

    豁免是合法出口，但**这一版有分析脚本可交**，用豁免就等于把门关上了。
    这条是防「为了让检查变绿而选最省事的出口」——
    检查变绿有很多种方式，其中一种是让检查不再问。
    """
    import preflight

    assert "v6.86.0" in preflight.PROVENANCE, (
        'v6.86.0 有实测结论（留出集数字），必须有复算脚本；'
        'EXEMPT 只给「不需要脚本」的情形用')
    assert "v6.86.0" not in preflight.EXEMPT, \
        'v6.86.0 不该出现在豁免表里——它的产出脚本已入库 analysis/holdout.py'
