"""v6.16.5 回归：能力声明要对得上端点的真实状态。

实测（2026-09-23，本机直连）：
  unpaywall.search('retrieval augmented generation') -> None，HTTP 410
      响应体：{"error":"gone","message":"Unpaywall title search was retired on 2026-09-1x",
               "docs":"https://help.openalex.org/access/unpaywall/…"}
  unpaywall.search_by_doi('10.1038/nature12373')     -> dict（DOI→OA 通道正常）
  s2-citation-graph.search(...)                      -> None，HTTP 429 rate limited
      （端点活着只是被限流，能力声明是真的——但它压根不在 PROBE_QUERIES 里，
        闸门从来没测过它）

所以两件事分开处理，手法沿用 v6.16.0 收缩 ModelScope 的先例：
  1. 端点已下线的，撤掉 search 能力声明，别让路由把关键词检索派给一个恒 410 的源；
     DOI→OA 的本职保留（search_by_doi 实测可用）。
  2. 端点活着、只是没进探针名单的，登记进 PROBE_QUERIES，让闸门真去测。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import probe  # noqa: E402
from research import build_registry  # noqa: E402


# ------------------------------------------------------------
# 1) unpaywall：标题搜索端点已下线，撤掉 search 能力
# ------------------------------------------------------------

class TestUnpaywallIsLookupOnly:

    def test_no_longer_claims_search_capability(self):
        from engines.academic_fulltext import UnpaywallEngine
        caps = UnpaywallEngine().metadata.capabilities
        assert 'search' not in caps, \
            f'标题搜索端点已 410 下线，还在声明 search 会让路由白派一路：{caps}'

    def test_still_declares_its_real_channels(self):
        from engines.academic_fulltext import UnpaywallEngine
        caps = UnpaywallEngine().metadata.capabilities
        assert 'oa' in caps and 'fulltext' in caps, caps

    def test_doi_lookup_entry_point_survives(self):
        from engines.academic_fulltext import UnpaywallEngine
        assert callable(getattr(UnpaywallEngine(), 'search_by_doi', None)), \
            '收缩能力声明不能顺手把真正可用的 DOI 通道删掉'

    def test_router_will_not_offer_it_for_keyword_search(self):
        names = {e.get_name() for e in
                 build_registry().get_by_capability('search', only_available=False)}
        assert 'unpaywall' not in names
        # 反向保护：收缩不能把别的学术源一起带没
        for n in ('openalex', 'pubmed', 'arxiv-fulltext', 'semantic-scholar'):
            assert n in names, f'{n} 被误伤了'


# ------------------------------------------------------------
# 2) s2-citation-graph：活着但没进探针名单
# ------------------------------------------------------------

class TestCitationGraphIsProbed:

    def test_registered_in_probe_queries(self):
        assert 's2-citation-graph' in probe.PROBE_QUERIES, \
            '它有 search 能力（委托 S2）却不在探针名单里，闸门永远测不到它'

    def test_probe_range_actually_includes_it(self):
        reg = build_registry()
        eng = reg.get('s2-citation-graph')
        assert eng.get_name() in {e.get_name() for e in probe.probeable_engines(
            reg.get_all())}

    def test_probe_query_is_not_the_generic_fallback(self):
        """引用图谱用通用词 'python' 会假阴性，得给学术查询词。"""
        eng = build_registry().get('s2-citation-graph')
        q = probe.resolve_probe_query(eng)
        assert q and q != probe.DEFAULT_PROBE_QUERY, q


# ------------------------------------------------------------
# 3) 清单口径不动：收缩能力不改变源总数与配置判据
# ------------------------------------------------------------

class TestInventoryUnchanged:

    def test_total_sources_and_config_split_are_untouched(self):
        reg = build_registry()
        assert len(reg.get_all()) == 32
        assert len(reg.get_configured()) == 27
        assert 'unpaywall' in {e.get_name() for e in reg.get_configured()}, \
            'unpaywall 有占位 email 兜底，DOI 通道实测可用，不该被算成需配置'
