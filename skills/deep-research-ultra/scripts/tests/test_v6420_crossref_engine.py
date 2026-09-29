"""v6.42.0 新增 Crossref 引擎：解析照今天真接口返回的形状来，缺的字段不许编。

夹具来源（取证方式与时间）：2026-09-29 本机直发
`https://api.crossref.org/works?query.bibliographic=...&rows=1..4`（HTTP 200，
`message-version` 1.0.0、`indexed.version` 4.0.1/4.1.0）取回的**逐字**条目，
只删掉了 `reference`（参考文献数组，本引擎不读，留着会把测试文件撑到几千行）：
  · `_ITEM_JOURNAL`  期刊论文：有 abstract（JATS 标签 + `&lt;` 实体）、license 两条（vor/tdm）、
                     ORCID、`issued` 精确到日、`resource.primary.URL` 指向出版方页
  · `_ITEM_PROCEEDINGS` 会议论文：无 abstract、无 license、`issued.date-parts` 只有年份 `[2020]`、
                     有 `page`、affiliation 是空数组
另外单独记一条**实测到的实体转义**：同批返回里 Optuna 那条的 container-title 是
`... Knowledge Discovery &amp; Data Mining`——不解实体会把 `&amp;` 原样带进报告。

为什么两条都要留：日期"只有年份"与"精确到日"必须都走通，否则会把 `2020` 补成
`2020-01-01`（凭空造出月日）；缺 abstract/缺 license 的那条专门用来盯"缺项不许印成 0/空串冒充有"。

写这个引擎时还撞过一次真实教训：第一版把响应里的总数读成 `message.totalResults`，
接口给的是 `message.total-results`——读错键不会报错，只会静默变成"0 条"。
所以第 `test_total_results_key_is_hyphenated` 一条把键名钉死。
"""

import json
import re
import urllib.parse

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engines.academic_engines as ae  # noqa: E402


_ITEM_JOURNAL = {
    "indexed": {"date-parts": [[2026, 9, 21]], "date-time": "2026-09-21T22:58:26Z",
                "timestamp": 1790031506369, "version": "4.0.1"},
    "reference-count": 23,
    "publisher": "Wiley",
    "license": [
        {"start": {"date-parts": [[2026, 7, 15]], "date-time": "2026-07-15T00:00:00Z",
                   "timestamp": 1784073600000},
         "content-version": "vor", "delay-in-days": 0,
         "URL": "http://onlinelibrary.wiley.com/termsAndConditions#vor"},
        {"start": {"date-parts": [[2026, 7, 15]]}, "content-version": "tdm",
         "delay-in-days": 0, "URL": "http://doi.wiley.com/10.1002/tdm_license_1.1"},
    ],
    "content-domain": {"domain": ["onlinelibrary.wiley.com"], "crossmark-restriction": True},
    "short-container-title": ["Clinical Anatomy"],
    "abstract": ("<jats:title>ABSTRACT</jats:title>\n                  <jats:p>\n"
                 "                    Large language models (LLMs) are increasingly used in "
                 "medical education. Citation content consistency differed significantly among "
                 "the models (\n                    <jats:italic>p</jats:italic>\n"
                 "                     &lt; 0.001), with ChatGPT 5.2 demonstrating the lowest "
                 "hallucination rate (23.2%).\n                  </jats:p>"),
    "DOI": "10.1002/ca.70187",
    "type": "journal-article",
    "created": {"date-parts": [[2026, 7, 15]], "date-time": "2026-07-15T09:00:57Z"},
    "update-policy": "https://doi.org/10.1002/crossmark_policy",
    "source": "Crossref",
    "is-referenced-by-count": 3,
    "title": ["Reference Hallucination, Citation Reliability, and Readability of Large "
              "Language Models in Anatomy‐Related Question Answering"],
    "prefix": "10.1002",
    "author": [
        {"ORCID": "https://orcid.org/0000-0001-5615-8913", "authenticated-orcid": False,
         "given": "Mehmet", "family": "Ülkir", "sequence": "first",
         "affiliation": [{"name": "Department of Anatomy, Hacettepe University"}],
         "role": [{"vocabulary": "crossref", "role": "author"}]},
        {"ORCID": "https://orcid.org/0000-0002-4354-3238", "authenticated-orcid": False,
         "given": "Bahattin", "family": "Paslı", "sequence": "additional",
         "affiliation": [{"name": "Department of Anatomy, Hacettepe University"}],
         "role": [{"vocabulary": "crossref", "role": "author"}]},
    ],
    "member": "311",
    "published-online": {"date-parts": [[2026, 7, 15]]},
    "container-title": ["Clinical Anatomy"],
    "language": "en",
    "link": [{"URL": "https://onlinelibrary.wiley.com/doi/pdf/10.1002/ca.70187",
              "content-type": "application/pdf", "content-version": "vor",
              "intended-application": "text-mining"}],
    "deposited": {"date-parts": [[2026, 7, 15]], "date-time": "2026-07-15T09:00:58Z"},
    "score": 37.657585,
    "resource": {"primary": {"URL": "https://onlinelibrary.wiley.com/doi/10.1002/ca.70187"}},
    "issued": {"date-parts": [[2026, 7, 15]]},
    "references-count": 23,
    "alternative-id": ["10.1002/ca.70187"],
    "URL": "https://doi.org/10.1002/ca.70187",
    "archive": ["Portico"],
    "ISSN": ["0897-3806", "1098-2353"],
    "issn-type": [{"value": "0897-3806", "type": "print"},
                  {"value": "1098-2353", "type": "electronic"}],
    "published": {"date-parts": [[2026, 7, 15]]},
    "article-number": "ca.70187",
}

_ITEM_PROCEEDINGS = {
    "indexed": {"date-parts": [[2026, 9, 29]], "date-time": "2026-09-29T13:55:23Z",
                "version": "4.1.0"},
    "publisher-location": "Stroudsburg, PA, USA",
    "reference-count": 0,
    "publisher": "Association for Computational Linguistics",
    "content-domain": {"domain": [], "crossmark-restriction": False},
    "published-print": {"date-parts": [[2020]]},
    "DOI": "10.18653/v1/2020.acl-main.703",
    "type": "proceedings-article",
    "created": {"date-parts": [[2020, 7, 29]], "date-time": "2020-07-29T10:14:43Z"},
    "page": "7871-7880",
    "source": "Crossref",
    "is-referenced-by-count": 4294,
    "title": ["BART: Denoising Sequence-to-Sequence Pre-training for Natural Language "
              "Generation, Translation, and Comprehension"],
    "prefix": "10.18653",
    "author": [
        {"given": "Mike", "family": "Lewis", "sequence": "first", "affiliation": [],
         "role": [{"vocabulary": "crossref", "role": "author"}]},
        {"given": "Yinhan", "family": "Liu", "sequence": "additional", "affiliation": []},
        {"given": "Naman", "family": "Goyal", "sequence": "additional", "affiliation": []},
    ],
    "member": "1643",
    "event": {"name": "Proceedings of the 58th Annual Meeting of the Association for "
                      "Computational Linguistics", "location": "Online",
              "acronym": "ACL 2020"},
    "container-title": ["Proceedings of the 58th Annual Meeting of the Association for "
                        "Computational Linguistics"],
    "deposited": {"date-parts": [[2020, 7, 29]], "date-time": "2020-07-29T10:19:11Z"},
    "score": 4.823691,
    "resource": {"primary": {"URL": "https://www.aclweb.org/anthology/2020.acl-main.703"}},
    "issued": {"date-parts": [[2020]]},
    "references-count": 0,
    "URL": "https://doi.org/10.18653/v1/2020.acl-main.703",
    "published": {"date-parts": [[2020]]},
}


def _payload(*items, total=None):
    return json.dumps({
        "status": "ok", "message-type": "work-list", "message-version": "1.0.0",
        "message": {
            "facets": {}, "total-results": (len(items) if total is None else total),
            "items": list(items), "items-per-page": len(items),
            "query": {"search-terms": "test", "start-index": 0},
        },
    }).encode("utf-8")


@pytest.fixture
def fake_get(monkeypatch):
    calls = []

    def _install(body):
        def fake(url, **kwargs):
            calls.append(url)
            return body
        monkeypatch.setattr(ae, '_http_get', fake)
        return calls
    return _install


def _engine():
    return ae.CrossrefEngine()


# ------------------------------------------------------------------ 元数据与接线

def test_metadata_says_no_config_is_required():
    """mailto 只是进 polite pool 的加分项，缺了照样能查——不许写成阻塞配置。"""
    meta = _engine().metadata
    assert meta.name == 'crossref'
    assert meta.layer == 1
    assert meta.requires_config is False
    assert 'search' in meta.capabilities and 'academic' in meta.capabilities


def test_engine_is_registered_and_probeable():
    from research import build_registry
    from probe import PROBE_QUERIES
    assert build_registry().get('crossref') is not None
    assert 'crossref' in PROBE_QUERIES, '未登记探针＝闸门看不见这个源今天出不导出数据'


def test_total_results_key_is_hyphenated(fake_get):
    """接口给的是 message.total-results，写成 totalResults 不会报错、只会静默 0 条。"""
    body = _payload(_ITEM_JOURNAL, total=259784)
    fake_get(body)
    assert len(_engine().search("hallucination")) == 1
    data = json.loads(body.decode('utf-8'))
    assert 'totalResults' not in data['message']
    assert data['message']['total-results'] == 259784


# ------------------------------------------------------------------ 解析真件

def test_journal_item_parses_title_date_and_doi_url(fake_get):
    calls = fake_get(_payload(_ITEM_JOURNAL))
    r = _engine().search("citation hallucination")[0]
    assert r.title.startswith("Reference Hallucination, Citation Reliability")
    assert r.url == "https://doi.org/10.1002/ca.70187"      # 用接口给的 URL，不自己拼
    assert r.source == 'crossref' and r.engine == 'crossref'
    assert r.published_date == "2026-07-15"
    assert r.author == "Mehmet Ülkir; Bahattin Paslı"
    assert len(calls) == 1


def test_normalized_raw_keys_for_the_journal_item(fake_get):
    """评分器与档 B 反查读规范键：venue/citation_count/doi/publisher_url/license_url。"""
    fake_get(_payload(_ITEM_JOURNAL))
    raw = _engine().search("x")[0].raw
    assert raw['venue'] == "Clinical Anatomy"
    assert raw['citation_count'] == 3
    assert raw['doi'] == "10.1002/ca.70187"                  # 裸 DOI
    assert raw['publisher_url'] == "https://onlinelibrary.wiley.com/doi/10.1002/ca.70187"
    assert raw['license_url'] == "http://onlinelibrary.wiley.com/termsAndConditions#vor"
    assert raw['issn'] == "0897-3806"
    assert raw['work_type'] == "journal-article"
    assert raw['publisher'] == "Wiley"
    assert raw['indexed_version'] == "4.0.1"                 # 接口版本留痕，便于日后契约变更定位


def test_year_only_date_is_not_inflated_into_a_full_date(fake_get):
    """会议条目 issued 只有 [2020]：必须回 '2020'，补成 2020-01-01 就是凭空造月日。"""
    fake_get(_payload(_ITEM_PROCEEDINGS))
    r = _engine().search("bart")[0]
    assert r.published_date == "2020"
    assert r.raw['page'] == "7871-7880"
    assert r.raw['citation_count'] == 4294
    assert r.raw['publisher_url'] == "https://www.aclweb.org/anthology/2020.acl-main.703"


def test_absent_license_and_abstract_are_not_fabricated(fake_get):
    """缺的就是缺：不写 license_url、不编 abstract。"""
    fake_get(_payload(_ITEM_PROCEEDINGS))
    raw = _engine().search("bart")[0].raw
    assert not raw.get('license_url')
    assert not raw.get('abstract')


def test_abstract_tags_stripped_and_entities_resolved(fake_get):
    """真件里既有字面 `<jats:p>` 标签，又有 `&lt;` 转义的小于号（`p < 0.001`）。

    顺序必须是"先删标签再解实体"，反过来的话 `&lt;` 解出来的 `<` 会被当标签尾巴吃掉。
    """
    fake_get(_payload(_ITEM_JOURNAL))
    content = _engine().search("hallucination")[0].content
    assert '<jats:' not in content and '</jats:p>' not in content
    assert 'Large language models (LLMs) are increasingly used' in content
    # 真件里 p 与 < 之间是窄空格 U+2009（会被空白折叠成普通空格），
    # 所以断言不能把那个不可见字符写进字面量——按形态匹配。
    assert re.search(r'p\s*<\s*0\.001', content), content
    assert 'ABSTRACT' in content


def test_container_title_entities_resolved_on_proceedings_item(fake_get):
    """同批真件里 Optuna 的会议名带 `&amp;`，直接入库会在报告里露出实体码。"""
    item = dict(_ITEM_PROCEEDINGS)
    item['container-title'] = ["Proceedings of the 25th ACM SIGKDD International Conference "
                               "on Knowledge Discovery &amp; Data Mining"]
    fake_get(_payload(item))
    raw = _engine().search("optuna")[0].raw
    assert raw['venue'] == ("Proceedings of the 25th ACM SIGKDD International Conference "
                            "on Knowledge Discovery & Data Mining")


def test_result_records_the_query_actually_sent(fake_get):
    fake_get(_payload(_ITEM_JOURNAL))
    r = _engine().search("citation hallucination rate", max_results=3)[0]
    assert r.query == "citation hallucination rate"


def test_items_without_doi_or_title_are_dropped_not_half_parsed(fake_get):
    """点不回原文的条目不进账本（归属型 claim 至少要有能打开的绝对 URL）。"""
    junk = {"DOI": "", "title": ["没有 DOI 的条目"], "type": "component", "member": "1"}
    fake_get(_payload(_ITEM_JOURNAL, junk))
    out = _engine().search("hallucination")
    assert len(out) == 1
    assert out[0].raw['doi'] == "10.1002/ca.70187"


# ------------------------------------------------------------------ 请求构造

def test_request_uses_query_bibliographic_and_rows(fake_get):
    calls = fake_get(_payload())
    _engine().search("retrieval augmented generation", max_results=12)
    parsed = urllib.parse.urlparse(calls[0])
    q = urllib.parse.parse_qs(parsed.query)
    assert parsed.scheme == 'https' and parsed.netloc == 'api.crossref.org'
    assert parsed.path == '/works'
    assert q['query.bibliographic'] == ['retrieval augmented generation']
    assert q['rows'] == ['12']


def test_rows_capped_at_api_limit(fake_get):
    """接口 rows 上限 1000，超了会被拒——不能把调用方给的数原样塞进去。"""
    calls = fake_get(_payload())
    _engine().search("test", max_results=99999)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0]).query)
    assert int(q['rows'][0]) <= 1000


def test_mailto_is_sent_when_configured_but_never_required(fake_get, monkeypatch):
    """Crossref 建议带 mailto 进 polite pool；配了才带，没配也能查（实测如此）。"""
    monkeypatch.delenv('CROSSREF_MAILTO', raising=False)
    calls = fake_get(_payload())
    _engine().search("x")
    assert 'mailto' not in urllib.parse.parse_qs(urllib.parse.urlparse(calls[0]).query)
    monkeypatch.setenv('CROSSREF_MAILTO', 'researcher@example.org')
    calls.clear()
    _engine().search("x")
    assert urllib.parse.parse_qs(urllib.parse.urlparse(calls[0]).query)['mailto'] == \
        ['researcher@example.org']


# ------------------------------------------------------------------ 失败与空结果分开

def test_http_failure_returns_none_not_empty_list(fake_get):
    fake_get(None)
    assert _engine().search("hallucination") is None


def test_empty_items_returns_empty_list(fake_get):
    """total-results=0 是「调通了但没命中」；回 None 会把 0 命中报成引擎坏了。"""
    fake_get(_payload())
    assert _engine().search("一个不存在的词组") == []


def test_error_json_body_returns_none(fake_get):
    """实测 Crossref 对坏参数回 HTTP 400 + JSON 错误体；没有 message.items 就是没取到数据。"""
    fake_get(json.dumps({"status": 400, "message": "Bad Request",
                         "error": "Invalid query"}).encode('utf-8'))
    assert _engine().search("hallucination") is None


def test_non_json_body_returns_none(fake_get):
    fake_get(b"<html><body>502 Bad Gateway</body></html>")
    assert _engine().search("hallucination") is None
