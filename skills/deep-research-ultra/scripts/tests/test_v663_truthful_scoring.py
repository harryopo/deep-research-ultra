"""v6.63.0：说真话的两处——相关性不可判定时不装懂，单源放宽必须留痕。

体检报告初稿把这两条写错了（已在报告 §更正），真读代码后才发现真问题：

**P1-5 更正**。初稿说「CRAAP 不含相关性维度」。实测相反：relevance 权重 0.35，
是五维里最高的。真正的问题是**判别力**——

    查询「RAG 评测基准与检索质量度量」
      切题（MultiHop-RAG 基准）      relevance=27.3  total=63.5  medium
      跑题（日本法律诉讼 RAG）        relevance=21.3  total=61.4  medium
      完全无关（胰腺炎抗氧化）        relevance=20.0  total=61.0  medium

三者几乎不区分。根因：`_score_relevance` 把中文查询切成 2-gram（评测/验基/基准/
索质/量度…）再拿去匹配英文标题，汉字对英文恒零命中，只有 "RAG" 这种拉丁词能碰上。
而 arxiv.org 的 authority=95 会把总分托到 61 分——**完全无关的论文和切题的论文
在报告里长得一样**。

判定器没听懂，不等于它判定为不相关。这两种 0 含义差着一个量级，而旧实现只返回
前者，还把它当成结论用。所以 v6.62 起：不可判定就标出来、封顶、降到"线索"，
不给 high/medium——假精确比不精确更坏。

**P1-4 更正**。初稿说「默认阈值 1 与铁律 6 冲突」。实测相反：判定写的是
`n_indep < max(2, min_sources_per_claim)`，门限本来就是 2，且是硬失败。真问题是
**旋钮拧不动**：help 里写着 `--min-sources 1`，用户传了以为放宽了，实际仍按 2 拦。
看似可调、实则无效，比没有旋钮更糟——人会以为已经放弃交叉验证了。
现在放宽必须走 `--allow-single-source`，且写进 warnings、stats 与防伪戳。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import ResearchLedger  # noqa: E402
from score import CraapScorer  # noqa: E402
from validate_report import _main, validate_report  # noqa: E402

CN_QUERY = 'RAG 评测基准与检索质量度量'

ON_TOPIC = {
    'title': 'MultiHop-RAG: Benchmarking Retrieval-Augmented Generation for Multi-Hop Queries',
    'url': 'https://arxiv.org/abs/2401.15391v1',
    'content': 'We develop MultiHop-RAG, a benchmarking dataset for multi-hop queries '
               'and compare embedding models and LLMs for retrieving evidence.',
}
OFF_TOPIC = {
    'title': 'RAG System for Supporting Japanese Litigation Procedures: Faithful Response',
    'url': 'https://arxiv.org/abs/2511.22858v1',
    'content': 'A RAG-based LLM system for Japanese medical litigation procedures '
               'complying with legal norms; expert commissioners support judges.',
}
UNRELATED = {
    'title': 'Antioxidant Therapy, N-acetyl-L-cysteine, Effects on Pancreatitis',
    'url': 'https://pubmed.ncbi.nlm.nih.gov/12345/',
    'content': 'Antioxidant therapy in acute pancreatitis, oxidative stress markers '
               'and mortality in patients.',
}


# ---------------------------------------------------------------------------
# 相关性：不可判定就说不可判定
# ---------------------------------------------------------------------------

def test_chinese_query_against_english_corpus_is_flagged_unreliable():
    s = CraapScorer()
    for case in (ON_TOPIC, OFF_TOPIC, UNRELATED):
        sc = s.score(case, query=CN_QUERY)
        assert not sc['relevance_reliable'], (
            f'中文查询 × 英文语料必须判为不可靠：{case["title"][:40]}')
        assert sc['relevance_capped'], sc


def test_unreliable_relevance_caps_total_below_medium():
    """封顶要真的压住——权威性再高也不能把总分托回 medium。"""
    s = CraapScorer()
    sc = s.score(ON_TOPIC, query=CN_QUERY)      # arxiv.org → authority 95
    assert sc['authority'] >= 90, sc
    assert sc['total'] <= CraapScorer.UNRATED_TOTAL_CAP, (
        f'Tier 加权把封顶值又抬上去了：total={sc["total"]} '
        f'（封顶应发生在 Tier 加权之后）')
    assert sc['grade'] == 'unrated', sc
    assert CraapScorer.grade_to_chinese('unrated') == '相关性未判定·仅作线索'


def test_same_language_queries_are_not_collateral_damage():
    """同语种下词法匹配是有效的，不能一起降级。"""
    s = CraapScorer()
    sc = s.score(ON_TOPIC, query='MultiHop RAG benchmarking dataset retrieval')
    assert sc['relevance_reliable'], sc
    assert sc['grade'] != 'unrated', sc
    assert sc['total'] > CraapScorer.UNRATED_TOTAL_CAP, sc


def test_the_old_behaviour_is_what_we_are_fixing():
    """钉住体检时的实测：旧实现把三档结果压成 61 分上下、全部 medium。

    这条不是为了纪念旧 bug——是提醒"相关性判别力不足"这件事至今仍在
    （本版只做到"不可判定时别装懂"，没做到"跨语言能判准"）。"""
    s = CraapScorer()
    rels = [s.score(c, query=CN_QUERY)['relevance'] for c in (ON_TOPIC, OFF_TOPIC, UNRELATED)]
    assert max(rels) - min(rels) < 15, (
        f'相关性分本该区分不出三档（体检实测 20.0/21.3/27.3），现在却拉开了：{rels}'
        f'——若将来补上跨语言匹配，把这个断言一起放宽')


# ---------------------------------------------------------------------------
# 交叉验证：旋钮不许是假的
# ---------------------------------------------------------------------------

# 单源场景的报告：只能引 [1]，引了账本里没有的 [2] 会被引用反查先拦下
REPORT_SINGLE = '''# 选型报告

## 一页拍板
选 A 方案 [1]。风险：迁移成本未验证。

## 执行摘要
A 方案有一个来源支持 [1]。

## 调研范围与方法
检索一个来源。

## 结论与建议
1. 采用 A 方案 [1]。

## 来源
[1] 唯一来源 https://arxiv.org/abs/1
'''

# 多源场景：两个独立来源
REPORT = '''# 选型报告

## 一页拍板
选 A 方案 [1][2]。风险：迁移成本未验证。

## 执行摘要
A 方案在两个独立来源上均被证实 [1][2]。

## 调研范围与方法
检索两个来源。

## 结论与建议
1. 采用 A 方案 [1][2]。

## 来源
[1] 来源甲 https://arxiv.org/abs/1
[2] 来源乙 https://example.org/b
'''


def _single_source_ledger(tmp_path):
    led = ResearchLedger(str(tmp_path / 'ledger')).init()
    c = led.add_claim('A 方案可行', '选型', 'verified', 'general', 0.9)
    led.add_source(c['id'], 'https://arxiv.org/abs/1', tier=1)   # 只有一条
    return str(tmp_path / 'ledger')


def test_single_source_claim_is_a_hard_failure(tmp_path):
    r = validate_report(REPORT_SINGLE, ledger_dir=_single_source_ledger(tmp_path))
    assert not r.passed, '单源 verified claim 必须硬失败（铁律 6）'
    assert any('独立来源不足' in i for i in r.issues), r.issues


def test_min_sources_one_cannot_widen_the_gate(tmp_path):
    """旋钮是假的：传 1 不生效，门槛仍是 2。"""
    r = validate_report(REPORT_SINGLE, ledger_dir=_single_source_ledger(tmp_path),
                        min_sources_per_claim=1)
    assert not r.passed, '--min-sources 1 竟把门放宽了——help 里写着它，用户会以为已放宽'


def test_min_sources_can_still_be_tightened(tmp_path):
    led_dir = tmp_path / 'ledger'
    led = ResearchLedger(str(led_dir)).init()
    c = led.add_claim('A 方案可行', '选型', 'verified', 'general', 0.9)
    led.add_source(c['id'], 'https://arxiv.org/abs/1', tier=1)
    led.add_source(c['id'], 'https://arxiv.org/abs/2', tier=1)
    relaxed = validate_report(REPORT, ledger_dir=str(led_dir),
                              min_sources_per_claim=2)
    stricter = validate_report(REPORT, ledger_dir=str(led_dir),
                               min_sources_per_claim=3)
    assert not any('独立来源不足' in i for i in relaxed.issues), relaxed.issues
    assert any('独立来源不足' in i for i in stricter.issues), stricter.issues


def test_allow_single_source_widens_but_leaves_a_trail(tmp_path):
    led_dir = _single_source_ledger(tmp_path)
    r = validate_report(REPORT_SINGLE, ledger_dir=led_dir, allow_single_source=True)
    assert r.passed, '显式放宽后应当过门'
    assert r.stats['weak_allowed'] == 1, r.stats
    assert any('--allow-single-source' in w for w in r.warnings), r.warnings


def test_weak_allowed_travels_with_the_stamp(tmp_path):
    """放宽这件事必须跟着交付物走——交接的人要看得见。"""
    led_dir = _single_source_ledger(tmp_path)
    report = tmp_path / 'report.md'
    report.write_text(REPORT_SINGLE, encoding='utf-8')
    assert _main(['--report', str(report), '--ledger', led_dir,
                  '--allow-single-source', '--stamp']) == 0
    assert 'weak_allowed=' in report.read_text(encoding='utf-8')
