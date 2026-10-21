# -*- coding: utf-8 -*-
"""v6.104：跨语言相关性判定 —— **量清楚问题，并证明四种候选修法都不该进生产路径**。

## 起因

v6.63 起就登记在案的 P1 遗留：「相关性跨语言判准未解决，需单独一轮」。

实测（`analysis/crosslang.py`）：中文查询 × 英文语料时，判定器
**100% 的配对被判 unrated**，与 oracle（同语种判定器）的一致性
AUC = **0.500** —— 抛硬币。不是判得不准，是**根本没判**：
中文 2-gram 在英文标题里恒零命中，于是每条分数都一样（都是 0）。

## 这一版做的是「量」，不是「修」

四种候选修法（术语表换词 + 三种门槛）都量过了，**没有一种过得了门槛**：
在人工标注口径上看着都好（precision 90~94%），但换成**表没覆盖到的查询**
（留出集）就崩到 19% —— 一个泛词（agent / model / retrieval）就足以把
不相关语料判成切题。

所以**不改 `score.py`**：把「看起来很像的修法」留在报告里，
让它带着数字留在仓库里，别让下一手重做一遍（v6.86 就是这么干的：
候选表、覆盖率、样本量、落盘路径都留下，只留结论）。

## 这份测试盯住什么

1. **现状不许悄悄变**：中文查询 × 英文语料仍然是 unrated、relevance 0。
   哪天要真修它，得先改这份测试并在 CHANGELOG 写明理由 ——
   不能让「跨语言判定忽然有分」变成一件没人注意到的事。
2. **量法本身可复算**：`analysis/crosslang.py --check` 必须绿。
3. **尺子自己是 sane 的**：同语种路径在人工标注上 precision ≈ 90%，
   否则「跨语言 19%」这个结论就没有对照。
4. **候选修法不在生产路径上**：`score.py` 里不该有那张术语表。
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

import pytest                                    # noqa: E402

from score import CraapScorer as CS              # noqa: E402

_analysis = importlib.import_module("analysis.crosslang")

EN_CORPUS = ("Deep Research Tool: A Survey of Agentic Search Pipelines",
             "We present a survey of deep research agents that combine "
             "retrieval, tool use and synthesis over large corpora.")


# ============================================================ 现状：钉住它


def test_cross_language_is_still_unrated():
    """中文查询 × 英文语料 → 仍然 unrated（现状就是「判不出来」）。

    这条不是「期望它坏」，是**钉住现状**：跨语言判定要真修，
    得先改这里并在 CHANGELOG 写明理由。
    """
    out = CS().score({'title': EN_CORPUS[0], 'url': '', 'content': EN_CORPUS[1]},
                     query='深度调研工具')
    assert out['relevance_capped'] is True
    assert out['relevance'] == 0.0
    assert out['grade'] == 'unrated'


def test_same_language_is_unaffected():
    """同语种（中文查询 × 中文语料）照旧能判 —— 现状这条是好的，别碰坏。"""
    out = CS().score({'title': '深度调研工具综述',
                       'url': '', 'content': '本文梳理深度调研智能体的检索与综合。'},
                     query='深度调研工具')
    assert out['relevance_capped'] is False
    assert out['relevance'] > 0


def test_score_py_has_no_alias_table():
    """候选修法的术语表**不许**进 `score.py`。

    它没过门槛（见 docs/dev/v6.104-跨语言相关性判据.md）。
    表留在 `analysis/crosslang.py` 里当**候选**——留给下一手看，
    不是留在生产路径上误导人。
    """
    assert not hasattr(CS, 'CROSS_LANG_ALIASES'), \
        "score.py 里出现了跨语言术语表 —— 那张表没过门槛，别偷偷上线"
    src = (S / 'score.py').read_text(encoding='utf-8')
    assert 'CROSS_LANG_ALIASES' not in src
    assert '_cross_alias_words' not in src


# ============================================================ 量法本身


def test_crosslang_check_passes():
    """复算入口必须能跑通（它是 v6.104 数字的复算路径）。"""
    r = subprocess.run(
        [sys.executable, str(S / 'analysis' / 'crosslang.py'), '--check'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=1800)
    assert r.returncode == 0, "crosslang --check 没过：\n%s\n%s" % (
        r.stdout[-800:], r.stderr[-400:])
    assert '与 CHANGELOG v6.104 一致' in (r.stdout or '')


def test_current_arm_reproduces_the_status_quo():
    """量法里的「现状」那一臂必须真的是现状（不是复刻走样了）。"""
    got = _analysis.compute_all()
    assert got['current_unrated_pct'] == 100.0, \
        "现状不再是 100%% unrated：%r" % got['current_unrated_pct']
    assert got['current_auc'] == 0.5
    assert got['current_recall'] == 0.0, \
        "现状的 recall 应当是 0（它从来没判过任何一条）"


def test_the_ruler_is_sane():
    """尺子（同语种路径）自己得是 sane 的。

    否则「跨语言 19%」这个结论没有对照 —— 参照物坏了，比数坏更糟。
    """
    got = _analysis.compute_all()
    assert got['human_same_lang_precision'] >= 80.0, \
        "同语种路径在人工标注上只有 %r —— 尺子坏了" % got['human_same_lang_precision']
    assert got['human_same_lang_recall'] >= 80.0


def test_no_candidate_fix_clears_the_holdout_bar():
    """**四种候选修法都得在留出集上被量一遍**，且门槛写在测试里。

    「听得懂就判」（修法 B）在人工标注口径上是 90%/89%，
    看着比尺子还好 —— 但留出集上 precision 掉到 19%：
    一个泛词就能把不相关语料判成切题。
    这条测试的作用是：**哪天有人想上线其中一种修法，
    必须先看见这两个数字**。
    """
    got = _analysis.compute_all()
    assert got['holdout_understood_precision'] < 50.0, (
        "修法 B 在留出集上的 precision 变成了 %r —— 要么量法变了，"
        "要么它真的过关了（那要重新看结论并写 CHANGELOG）"
        % got['holdout_understood_precision'])
    # 现状在所有量法里 recall 都是 0
    assert got['holdout_current_recall'] == 0.0
    assert got['human_current_recall'] == 0.0


def test_three_measurement_modes_exist():
    """三套量法都要在（只报一套会把偏袒方向藏起来）。"""
    assert len(_analysis.QUERIES) >= 10, "调参集"
    assert len(_analysis.HOLDOUT_QUERIES) >= 5, "留出集"
    assert len(_analysis.HUMAN_QUERIES) >= 5, "人工标注口径的译文集"
    # 留出集里的查询**不能**与调参集重合（重合 = 留出失效）
    tune = {zh for zh, _ in _analysis.QUERIES}
    hold = {zh for zh, _ in _analysis.HOLDOUT_QUERIES}
    assert not (tune & hold), "留出集与调参集重了：%s" % (tune & hold)


def test_alias_prototype_handles_overlapping_terms():
    """候选表的匹配逻辑：长词优先，被长词包住的短词不重复计数。"""
    assert _analysis.alias_words('大语言模型') == ['large', 'language', 'model']
    assert _analysis.alias_words('模型') == ['model']
    assert _analysis.alias_words('向量数据库') == ['database', 'vector']
