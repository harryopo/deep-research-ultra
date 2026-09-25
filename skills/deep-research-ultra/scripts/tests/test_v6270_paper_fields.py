"""v6.27.0 回归：学术结果的 raw 要带归一化字段，评分器才不是瞎评。

实测来源（本机 2026-09-25，查询词「retrieval augmented generation」，直连四个学术 API）：
`recommend.PaperRecommender.rank_results()` 做的是 `paper_data = result.raw`，而评分器读的键是
`citation_count` / `published_date` / `venue` / `influential_citation_count` / `author_h_index`；
各家 API 的原生键名分别是 `cited_by_count`（OpenAlex）、`citationCount`+`publicationDate`（S2）、
`fulljournalname`+`pubdate`（PubMed）。逐条量下来：

| 引擎 | 评分器要且有值的键 | 引用维实测得分 |
|------|------------------|--------------|
| openalex | 2/11（只有 title、doi） | 0.0 |
| semantic-scholar | 3/11（raw 里明明有 citationCount） | 0.0 |
| pubmed | 1/11（只有 title） | 0.0 |
| arxiv-fulltext | **0/11**（raw 里连 title 都没有） | 0.0 |

后果：《Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks》这种几千引用的论文
被算成"引用维 0 分 → 总分 32 → 等级 Skip"。所以引擎侧要把已经算出来的规范值放进 raw，
评分器侧要分清"这个源不给引用数"与"这篇论文 0 引用"。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import academic_engines as ae          # noqa: E402
from engines.base import paper_meta                  # noqa: E402
from recommend import PaperRecommender               # noqa: E402

QUERY = 'retrieval augmented generation'

OPENALEX_ITEM = {
    'display_name': 'RAG for Knowledge-Intensive NLP',
    'primary_location': {'landing_page_url': 'https://aclanthology.org/X/',
                         'source': {'display_name': 'ACL Anthology'}},
    'doi': 'https://doi.org/10.18653/v1/2020.emnlp-main.123',
    'publication_date': '2020-10-01',
    'cited_by_count': 4200,
    'authorships': [{'author': {'display_name': 'Patrick Lewis'}}],
    'abstract_inverted_index': {'检索增强': [0], '生成': [1]},
}

S2_ITEM = {
    'paperId': 'CorpusID:227244180',
    'title': 'RAG survey',
    'year': 2024,
    'citationCount': 1500,
    'influentialCitationCount': 40,
    'venue': 'Nature Machine Intelligence',
    'externalIds': {'DOI': '10.1038/s42256-024-00567-8'},
    'abstract': 'retrieval augmented generation 综述',
    'authors': [{'name': 'Ye Wang'}],
}

PUBMED_ITEM = {
    'uid': '39000001',
    'title': 'LLM for radiology',
    'fulljournalname': 'Radiology',
    'pubdate': '2026 Jan 15',
    'articleids': [{'idtype': 'doi', 'value': '10.1148/radiol.2026.0001'}],
    'authors': [{'name': 'Zhang L'}],
}


def _patch(monkeypatch, module, payload_key, items):
    """让引擎拿到的响应里带上指定条目；只替换网络，解析与归一都走真实代码。"""
    def _fake(url, **kwargs):
        return json.dumps({payload_key: items}).encode('utf-8')
    monkeypatch.setattr(module, '_http_get', _fake)


def test_openalex_的_raw_带归一字段(monkeypatch):
    _patch(monkeypatch, ae, 'results', [OPENALEX_ITEM])
    r = ae.OpenAlexEngine().search(QUERY, max_results=3)[0]
    assert r.raw['citation_count'] == 4200, r.raw
    assert r.raw['published_date'] == '2020-10-01', r.raw
    assert r.raw['venue'] == 'ACL Anthology', r.raw
    assert r.raw['doi'] == '10.18653/v1/2020.emnlp-main.123', r.raw
    assert r.raw['title'] == 'RAG for Knowledge-Intensive NLP', r.raw
    # 原生键不许丢（档 B 反查、账本字段都靠它们）
    assert r.raw['cited_by_count'] == 4200, r.raw


def test_semantic_scholar_的_raw_带归一字段(monkeypatch):
    _patch(monkeypatch, ae, 'data', [S2_ITEM])
    r = ae.SemanticScholarEngine().search(QUERY, max_results=3)[0]
    assert r.raw['citation_count'] == 1500, r.raw
    assert r.raw['influential_citation_count'] == 40, r.raw
    assert r.raw['venue'] == 'Nature Machine Intelligence', r.raw
    assert r.raw['doi'] == '10.1038/s42256-024-00567-8', r.raw
    assert str(r.raw['published_date']).startswith('2024'), r.raw


def test_pubmed_的_raw_带归一字段但不编造引用数(monkeypatch):
    """PubMed 确实没有引用数：那就不写 citation_count，交给评分器按"缺项"处理。"""
    def _fake(url, **kwargs):
        # PubMed 是两步取数：esearch 给 idlist，esummary 给详情
        if 'esearch' in url:
            return json.dumps({'esearchresult': {'idlist': ['39000001']}}).encode('utf-8')
        return json.dumps({'result': {'uids': ['39000001'],
                                      '39000001': PUBMED_ITEM}}).encode('utf-8')
    monkeypatch.setattr(ae, '_http_get', _fake)
    r = ae.PubmedEngine().search(QUERY, max_results=3)[0]
    assert r.raw['venue'] == 'Radiology', r.raw
    assert r.raw['published_date'].startswith('2026'), r.raw
    assert r.raw['doi'] == '10.1148/radiol.2026.0001', r.raw
    assert 'citation_count' not in r.raw, r.raw


def test_评分器现在能给高引用论文非零引用分(monkeypatch):
    _patch(monkeypatch, ae, 'results', [OPENALEX_ITEM])
    r = ae.OpenAlexEngine().search(QUERY, max_results=3)[0]
    rec = PaperRecommender().score(r.raw, QUERY)
    assert rec.dimensions['citation_impact'] > 60, rec.dimensions
    assert rec.total_score > 50, rec.total_score


def test_取不到引用数要说明不许当作零引用():
    """PubMed 这类源没有引用数：按 0 评会写成"0 引用"，得说清是"该源不提供"。"""
    rec = PaperRecommender().score({'title': 'LLM for radiology', 'venue': 'Radiology',
                                    'published_date': '2026-01-15'}, 'radiology LLM')
    assert rec.dimensions['citation_impact'] == 0          # 分数仍按缺项计（机械口径不变）
    assert '未提供' in rec.recommendation_reason or '无引用数据' in rec.recommendation_reason, \
        rec.recommendation_reason


@pytest.mark.parametrize('bad', [None, {}, 'not-a-dict', [1, 2]])
def test_paper_meta_对异常输入不炸(bad):
    out = paper_meta(bad, title='T')
    assert out['title'] == 'T', out
