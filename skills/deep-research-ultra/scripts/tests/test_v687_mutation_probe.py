"""v6.87：变异测试找出的两个真缺口，各钉一条。

## 怎么来的

不是读代码读出来的，是**改坏代码看测试会不会红**量出来的。
9 个语义变异里 8 个是真变异（另一个是等价变异，见下），测试抓到 6 个 = **75%**。

漏掉的两个都是真行为差异，都已在此钉死。

## 为什么"等价变异"也要记

第 5 个变异（删掉空标题的早退）**存活**了，但它是**等价变异**：
空标题走 for 循环时每个非空锚词 `a in ''` 都是 False，结果照样是 `[]`。

我给它的 `expect` 标了"该抓到"，于是校准组报 4/5，看着像尺子不准。
实际上**是我的预期错了** —— 我把一段没有行为差异的代码当成了变异点。
尺子是准的，是我在校准时挑错了样本。

这条记下来是因为：**存活 ≠ 缺口**。把等价变异当缺口报，会让人补一堆
没用的测试；补完发现行为没变，下一次就不信这个工具了。误报比漏报贵。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

from score import CraapScorer as CS  # noqa: E402
import verify_quotes as vq  # noqa: E402

# 探针要 `git archive HEAD` 才能造副本，所以它的自测**需要 git 检出**。
# 而变异副本（探针的实跑环境）不是 git 仓库 —— 在那里这三个测试既跑不动
# （每个都要 copytree 一遍全仓，三个套起来 20 分钟）也**没有意义**：
# 变异测的是被改坏的业务代码，探针自己不是被测对象。
IN_GIT_CHECKOUT = (S.parents[2] / ".git").exists()
needs_git = pytest.mark.skipif(
    not IN_GIT_CHECKOUT,
    reason="需要 git 检出（探针靠 git archive 造副本）；变异副本里没有 .git，"
           "且那里探针不是被测对象")


def _copy(tmp_path):
    """造一份副本。抽出来是为了让三处共用同一句跳过理由。"""
    import probe_mutation as pm
    return pm.make_copy(tmp_path / "repo")


class _R:
    """够评分器用的最小结果对象。"""

    def __init__(self, title, url, content, date="2026-01-15"):
        self.title, self.url, self.content = title, url, content
        self.published_date, self.author, self.source = date, "A. Author", "J"
        self.snippet, self.summary = content[:300], content[:200]


# ---------------------------------------------------------------------------
# 缺口一：total 会超过 100
# ---------------------------------------------------------------------------

def test_tier_bonus_cannot_push_total_above_100():
    """Tier 1 域给 +0.1 惩罚（即**加分** +10），total 必须仍夹在 0~100。

    实测去掉 `min(100.0, ...)` 之后，这个输入的 total 是 **101.0** ——
    百分制打出 101 分。而**没有任何测试发现它**。

    为什么值得钉：CRAAP 分数会进证据账本、会被读成"98.7 / 100"这类精确值，
    出现 101 会让人怀疑整个评分口径。夹取的另一半 `max(0.0, ...)` 同理
    （Tier 4 是 -0.15，能把 total 压成负数）。
    """
    sc = CS()
    q = "retrieval augmented generation long context conflict"
    out = sc.score(_R(
        "Retrieval Augmented Generation with Long Context Conflict",
        "https://arxiv.org/abs/2402.00001",
        "retrieval augmented generation " * 30 + " long context conflict " * 20),
        query=q, enable_llm=False)

    assert out["tier"] == 1, f'这个样本要落在 Tier 1 才测得到加分，实得 {out["tier"]}'
    assert 0.0 <= out["total"] <= 100.0, (
        f'total 越界了：{out["total"]}。'
        f'Tier 1 的 +0.1 是**加分**，夹取丢了就会冲出 100。')


def test_tier_penalty_cannot_push_total_below_zero():
    """反向那一侧：Tier 4 是 -0.15（减 15 分），total 不得变成负数。"""
    sc = CS()
    out = sc.score(_R(
        "Low quality listicle about retrieval augmented generation",
        "https://some-spam-listicle-site.example/popular/100-best-rag",
        "retrieval " * 20), query="retrieval augmented generation",
        enable_llm=False)
    assert 0.0 <= out["total"] <= 100.0, f'total 越界：{out["total"]}'


# ---------------------------------------------------------------------------
# 缺口二：单字引号被当成逐字引用
# ---------------------------------------------------------------------------

def test_single_character_quotes_are_not_verbatim_spans():
    """`「字」` 不能被当成逐字引用片段。

    引用核验是这套东西的硬门：抽出来的片段会去语料里逐字比对，查不到就报错。
    若单字也算，那报告里每一个「文」「字」「气」都会变成一条假警报，
    而假警报多了，真警报就没人看了（这正是 v6.40 起的教训）。

    实测把默认 `floor` 从 2 改成 1，`「字」` 就从 0 个片段变成 1 个。
    """
    for text, why in [("「字」", "单字"), ("「气」", "单字"),
                      ("「文」", "单字")]:
        spans = list(vq.quoted_spans(text))
        assert len(spans) == 0, (
            f'{why}引号 {text!r} 被当成了 {len(spans)} 个逐字引用片段：'
            f'{spans} —— 会去语料里逐字比对并报假警报')

    # 两个字仍然要抽出来：不能矫枉过正
    assert len(list(vq.quoted_spans("「引用」"))) == 1, \
        "两个字以上的引号必须照常抽取，别为了躲单字把下限一起抬了"


def test_quoted_spans_default_floor_stays_at_two():
    """钉住默认值本身，而不只是结果。

    上一条钉的是"单字不算"，那条在 `floor` 被改成别的值时可能仍然过
    （比如有人改成 3，那两个字也不算了，但上一条只查单字）。
    """
    import inspect

    sig = inspect.signature(vq.quoted_spans)
    assert sig.parameters["floor"].default == 2, (
        f'quoted_spans 的 floor 默认值变成了 '
        f'{sig.parameters["floor"].default}。改动前先想清楚：'
        f'调低会引入假警报，调高会漏掉真引用')


# ---------------------------------------------------------------------------
# 探针本身的可信度 —— 这一节比上面两条更要紧
# ---------------------------------------------------------------------------
# 上面两个缺口是探针找出来的。**但如果探针会骗人，那它找出的任何结论都作数不得。**
#
# 四次「造完就信」被抓：
#   v6.83  标注规则把「我举的例子」当全集      → 8 条标错
#   v6.86  prov 扫描的正则永远返回空          → 「空」恰好等于「没发现问题」
#   v6.86  空测试扫描器只认裸 assert          → 漏掉全部 unittest 风格（误报 10/10）
#   v6.87  变异探针自己读了陈旧 .pyc          → 给出一个正常的数字，描述的却是没改过的代码
#
# 第四条最隐蔽。而这一节底下每一条测试，钉的就是"别再让它悄悄发生"。
#
# 另有一条靠观察发现的：前一版探针直接改真源码、靠 `finally` 还原，
# 跑着跑着进程被掐断，`verify_quotes.py` **被留在变异状态**（floor=1 留在工作区）。
# `finally` 挡得住异常，**挡不住 SIGKILL** —— 所以改成只在副本上写。


def test_probe_disables_bytecode_cache_for_every_subprocess():
    """子进程一律不带字节码缓存 —— 等长改动的头号克星。"""
    import probe_mutation as pm

    assert pm.ENV.get("PYTHONDONTWRITEBYTECODE") == "1", (
        "变异子进程必须设 PYTHONDONTWRITEBYTECODE=1。"
        "否则同长度的替换会复用陈旧 .pyc，"
        "让探针读到没变的代码却不报错。")
    assert pm.ENV.get("PYTHONIOENCODING") == "utf-8", \
        "中文输出必须钉住编码，否则报错信息本身会乱码"


def test_probe_paths_point_at_the_right_levels():
    """`S` 与 `REPO` 必须各推对一层 —— 这个坑踩过不止一次。"""
    import probe_mutation as pm

    assert (pm.S / "score.py").exists(), f'S 推错层了：{pm.S}'
    assert (pm.S / "verify_quotes.py").exists(), f'S 推错层了：{pm.S}'
    assert (pm.REPO / "CHANGELOG.md").exists(), f'REPO 推错层了：{pm.REPO}'


@needs_git
def test_probe_only_writes_inside_the_copy():
    """**真目录结构上不可能被碰** —— 这一版最重要的性质。

    前一版直接改真源码、靠 `finally` 还原。实测进程被硬杀（服务器重启）时
    还原没跑，`verify_quotes.py` 被留在 `floor=1`。`finally` 挡得住异常，
    挡不住 SIGKILL —— 那就别靠纪律，靠结构。

    **判据是行为，不是文本。** 第一版这里写的是「扫源码里的 `write_text`
    看它有没有走副本」—— 那验证不了数据流：`p = scr / m.file` 之后
    `p.write_text(...)` 在文本上根本看不出 `p` 指向哪。自己踩了一次
    「算的不是真实行为」，那就换掉。

    改成：真文件哈希跑前跑后必须一致。
    """
    import hashlib
    import tempfile

    import probe_mutation as pm

    def h(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    watched = [pm.S / m.file for m in pm.MUTATIONS]
    before = {p: h(p) for p in watched if p.exists()}

    with tempfile.TemporaryDirectory() as td:
        scr = pm.make_copy(Path(td) / "repo")
        # 在副本上真的改一轮（不跑套件，那太慢）
        for m in pm.MUTATIONS:
            cp = scr / m.file
            src = cp.read_text(encoding="utf-8")
            if m.find in src:
                cp.write_text(src.replace(m.find, m.rep, 1), encoding="utf-8")
        # 副本里应当真的变了，否则这条测试什么都没验到
        changed = sum(1 for m in pm.MUTATIONS
                      if m.find in (pm.S / m.file).read_text(encoding="utf-8")
                      and m.rep in (scr / m.file).read_text(encoding="utf-8"))
        assert changed > 0, "副本里一个变异都没装上，这条测试等于空跑"

    after = {p: h(p) for p in watched if p.exists()}
    dirty = [p.name for p in before if before[p] != after.get(p)]
    assert not dirty, (
        f'探针动了真目录里的文件：{dirty}。'
        f'所有写入必须发生在 make_copy() 导出的副本里 —— '
        f'进程被硬杀时 finally 跑不了，靠不住。')


def test_probe_validates_copy_before_measuring():
    """副本自洽性必须先验 —— 否则「副本里失败」不能算「变异被抓到」。

    副本里有些测试读仓库相对路径的文件（README / CHANGELOG / index.html）。
    副本要是缺了什么，每个变异都会「被抓到」，而那全是假的 ——
    检测率会虚报到 100%，比没有门更坏。

    判据用**语义**（要求基线是 `green`）而不是变量名：
    第一版断言 `src.index("base_red")`，我把它改名成 `base` 测试就红了 ——
    变量名不是要求本身，钉它只会让人为了过测试而保留一个无意义的旧名。
    """
    import inspect

    import probe_mutation as pm

    src = inspect.getsource(pm.report)
    assert '!= "green"' in src, \
        "report() 必须先跑一遍未变异的基线并要求它是 green"
    assert "BASELINE_TIMEOUT" in src, "基线全量要显式给超时预算"
    assert src.index('!= "green"') < src.index("for i, m in enumerate(MUTATIONS"), \
        "基线校验必须排在变异循环之前"


@needs_git
def test_probe_verifies_the_mutation_actually_took_effect():
    """**不信任「装上了」** —— 变异没生效时必须中止整个测量。

    这是探针最重要的性质。「以为装上了」是这类工具最常见的失败模式：
    不报错、给出一个正常的数字、而那个数字描述的是没被改过的代码。

    用一个**故意装不上去**的变异（目标串压根不在文件里）验证它会喊。
    """
    import tempfile

    import probe_mutation as pm

    with tempfile.TemporaryDirectory() as td:
        scr = _copy(Path(td))
        m = pm.Mut("score.py", "这段串不可能出现在 score.py 里",
                   "REPLACEMENT_NEVER_APPLIES", "故意装不上", "any")
        raised = False
        try:
            pm.assert_mutation_took(scr, m)
        except RuntimeError as e:
            raised = True
            assert "没真正装上" in str(e), f'报错要说清是变异没装上：{e}'
        assert raised, (
            "变异压根没装上去，探针却没报错 —— 那它给出的检测率"
            "描述的是没被改过的代码，整个测量作废。")


def test_probe_clears_pycache_before_running_suites():
    """跑套件前必须清 `__pycache__`（第二道防线）。"""
    import tempfile

    import probe_mutation as pm

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "__pycache__"
        d.mkdir()
        (d / "stale_marker.pyc").write_bytes(b"stale")
        pm.clear_pycache(Path(td))
        assert not (d / "stale_marker.pyc").exists(), \
            "clear_pycache 没清掉 __pycache__ 里的文件"


def test_probe_anchors_still_match_current_code():
    """记录在案的检测率，只对锚点仍与当前代码吻合时成立。

    有人改了 `score.py` 那几行，锚点就没了，那个百分比就不再描述当前代码。
    所以锚点体检必须**秒级**、能随手跑 —— 慢到没人跑的门等于没有。
    """
    import probe_mutation as pm

    assert pm.anchors_ok() == 0, (
        "有变异锚点已失效，记录的检测率不再适用。"
        "要么重跑 --report，要么把失效的变异删掉并说明为什么。")


@needs_git
def test_probe_narrows_tests_by_transitive_closure():
    """收窄必须用**传递**闭包，不能只看直接 import。

    v6.81 那个 bug 就藏在「看起来无关」的路径上（缓存命中会提前 return）。
    只看直接依赖等于把那个错误再犯一遍。
    """
    import tempfile

    import probe_mutation as pm

    with tempfile.TemporaryDirectory() as td:
        scr = _copy(Path(td))
        assert pm._rev_graph(scr), "反向依赖图是空的，说明 import 解析没工作"

        direct = {f for f in pm.tests_touching(scr, "verify_quotes")
                  if "verify_quotes" in pm._imports(f)}
        allhits = set(pm.tests_touching(scr, "verify_quotes"))
        assert allhits, "收窄结果为空 —— 那会让变异跑到 0 个测试，必然假存活"
        assert len(allhits) >= len(direct), "传递闭包不该比直接依赖还少"


def test_probe_equivalence_is_not_reported_as_a_gap():
    """等价变异必须标出来，不能当缺口报。

    第 5 个变异（删掉空标题早退）**存活**了，但它是等价的：空串对每个
    非空锚词都判不中，结果照样是 `[]`。

    我最初给它标了"该抓到"，校准组因此报 4/5，看着像尺子不准 ——
    其实是我的预期错了。把等价变异当缺口报，会让人补一堆没用的测试；
    补完发现行为没变，下一次就不信这个工具了。**误报比漏报贵。**
    """
    import probe_mutation as pm

    assert any(m.expect == "equivalent" for m in pm.MUTATIONS), \
        "清单里应保留至少一个等价变异样本 —— 全是「该抓到」的变异，" \
        "尺子就失去了分辨等价/不等价的能力"
    assert CS.topic_anchor_hits("") == [], \
        "topic_anchor_hits('') 必须返回 []，否则「删掉空标题早退」就不是等价变异"