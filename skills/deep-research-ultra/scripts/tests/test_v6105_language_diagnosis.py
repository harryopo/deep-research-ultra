# -*- coding: utf-8 -*-
"""v6.105：语言不匹配的诊断 —— 中文查询打外文语料时，**说清楚为什么、怎么救**。

## 为什么要有这个

v6.104 量出来的事实：中文查询 × 英文语料时，相关性判定器 **100% 判 unrated**
（AUC 0.500、recall 0%）。后果不是「结果少」，是**证据集里没有先后**：
所有条目的 relevance 都是 0，Lead 读到的证据集与「这批全是噪声」长得一模一样。

而**修法不是工具能做的**：`references/playbooks.md` §1.6 已经把三条
「让工具自动取词」的路子实测否决（词典翻译 / 引文扩引 / 取主题词，
后两条 precision 0/10），结论是**检索词的判断留给 Lead**。

所以工具该做的是把这件事**说出来**，并给出 Lead 能直接抄的命令形式：
`--source-query "<引擎名>=<一句英文机制描述>"`。

## 这份测试盯住什么

1. 外文语料 + 中文查询 + 判定失效 → 必须报「语言不匹配」并给出命令形式；
2. 中文语料 + 中文查询 + 判定失效 → 报「查询词太窄」，**不**报语言不匹配；
3. 英文查询 → 一句都不报（那条路径判定是有效的）；
4. 语种**看标题不看正文** —— 市场类引擎的正文是我们自己拼的
   （"[Market] skills.sh（Agent Skill 市场）"），里面永远有中文；
   第一版看正文，把每个市场结果都误判成「中文语料」。
"""
from __future__ import annotations

import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

import research                                 # noqa: E402
from score import CraapScorer as CS             # noqa: E402


class _R:
    """最小结果对象（只要 title/content/engine/craap_score）。"""

    def __init__(self, title, content, engine, capped):
        self.title = title
        self.content = content
        self.engine = engine
        self.craap_score = {'relevance': 0.0 if capped else 40.0,
                            'relevance_capped': capped}


def _unrated_latin():
    return _R('rag-agent-builder（skills.sh）',
              '[Market] skills.sh（Agent Skill 市场）；来源仓库 github.com/x/y',
              'skill-market', True)


def _unrated_cjk():
    return _R('向量数据库选型实践',
              '本文介绍向量数据库的选型方法。', 'baidu-serp', True)


def _judged_latin():
    return _R('Vector database comparison',
              'A survey of vector databases.', 'openalex', False)


# ============================================================ 报不报


def test_foreign_corpus_with_cjk_query_triggers_language_hint(capsys):
    """外文语料 + 中文查询 + 判定失效 → 报语言不匹配，并给出命令形式。"""
    out = research._report_language_mismatch([_unrated_latin()], '向量数据库选型')
    err = capsys.readouterr().err
    assert out['triggered'] is True
    assert out['unrated'] == 1
    assert out['foreign_corpus'] == [('skill-market', 1)]
    assert '语言不匹配' in err
    assert '--source-query' in err, "没给出可执行的命令形式"
    assert 'skill-market' in err, "没点名是哪个引擎"


def test_cjk_corpus_reports_narrow_query_not_language_mismatch(capsys):
    """中文语料 + 中文查询 + 判定失效 → 报「查询词太窄」，不是语言不匹配。"""
    out = research._report_language_mismatch([_unrated_cjk()], '向量数据库选型')
    err = capsys.readouterr().err
    assert out['same_script_corpus'] == [('baidu-serp', 1)]
    assert out['foreign_corpus'] == []
    assert '查询词太窄' in err
    assert '语言不匹配' not in err


def test_english_query_never_triggers(capsys):
    """英文查询 → 一句都不报（同语种判定是有效的，报了就是噪音）。"""
    out = research._report_language_mismatch([_unrated_latin()], 'vector database')
    err = capsys.readouterr().err
    assert out['triggered'] is False
    assert out['unrated'] == 0
    assert err.strip() == ''


def test_judged_results_do_not_trigger(capsys):
    """判定没失效 → 不报（没有「判不了」这回事）。"""
    out = research._report_language_mismatch([_judged_latin()], '向量数据库选型')
    err = capsys.readouterr().err
    assert out['triggered'] is False
    assert err.strip() == ''


def test_empty_results_do_not_trigger(capsys):
    out = research._report_language_mismatch([], '向量数据库选型')
    assert out['triggered'] is False
    assert capsys.readouterr().err.strip() == ''


# ============================================================ 语种看标题，不看正文


def test_corpus_script_looks_at_title_not_our_own_content():
    """市场类结果：标题外文、正文含我们的中文样板 → 判「外文」。

    第一版看正文 → 每个市场结果都被误判成中文语料，
    于是「语言不匹配」永远不触发（「查询词太窄」倒是天天触发）。
    """
    assert research._corpus_script(_unrated_latin()) == 'latin'
    assert research._corpus_script(_unrated_cjk()) == 'cjk'


def test_market_result_is_classified_as_foreign():
    """回归：第一版把 skill-market 归进「中文语料」那一组。"""
    out = research._report_language_mismatch([_unrated_latin()], '向量数据库选型')
    assert out['foreign_corpus'] == [('skill-market', 1)]
    assert out['same_script_corpus'] == []


def test_dict_shaped_results_work_too(capsys):
    """缓存命中那条路径给的是 dict —— 两种形状都得认。"""
    r = {'title': 'Vector database survey', 'content': 'A survey.',
         'engine': 'openalex',
         'craap_score': {'relevance': 0.0, 'relevance_capped': True}}
    out = research._report_language_mismatch([r], '向量数据库选型')
    err = capsys.readouterr().err
    assert out['foreign_corpus'] == [('openalex', 1)]
    assert '语言不匹配' in err


# ============================================================ 判定失效的口径没被改动


def test_unrated_semantics_unchanged():
    """诊断**只报告**「判定失效」，不改变它的含义（v6.63：不可判定 ≠ 不相关）。"""
    out = CS().score({'title': 'Vector database survey',
                       'url': '', 'content': 'A survey.'},
                      query='向量数据库选型')
    assert out['relevance_capped'] is True
    assert out['relevance'] == 0.0
    assert out['grade'] == 'unrated'
