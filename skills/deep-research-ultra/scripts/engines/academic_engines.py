"""
Deep Research Ultra v4.0 — Layer 1: 学术直连引擎层

三个学术文献直连引擎（直接调用官方 API，无需 MCP 中转）：
- OpenAlexEngine: 开放学术元数据（474M+ 作品，含引用分析与概念标签）
- SemanticScholarEngine: AI2 语义学术（200M+ 论文，含 TLDR 与 influential citations）
- PubmedEngine: NCBI PubMed 医学文献（36M+ 医学文献，含 MeSH 词表）

设计说明：
- 这些引擎直接调用各大学术 API 的官方 HTTP 端点
- 无需 API Key（可选 Key 提高速率/进入 polite pool）
- 国内均可直连访问
- HTTP 请求统一走 fallback.py 的 _http_get（含 curl_cffi TLS 指纹伪装）
- 优先级数字小于 Layer 4 降级引擎，确保学术查询优先走专业源
"""

import json
import os
import urllib.parse
from typing import Dict, List, Optional

from .base import SearchEngine, SearchResult, EngineMetadata
from .fallback import _http_get


# ============================================================
# 工具函数
# ============================================================

def _decode_bytes(raw: bytes) -> str:
    """将 bytes 解码为字符串（优先 utf-8）"""
    if not raw:
        return ''
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        for encoding in ('latin-1', 'gbk', 'gb2312'):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', errors='ignore')


def _restore_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """
    将 OpenAlex 的 abstract_inverted_index 还原为完整摘要文本

    OpenAlex 的摘要以倒排索引形式存储：
        {"word1": [0, 5], "word2": [1, 3], ...}
    需要按位置还原为原始顺序的文本。

    Args:
        inverted_index: 倒排索引字典

    Returns:
        还原后的摘要文本，无摘要返回空字符串
    """
    if not inverted_index or not isinstance(inverted_index, dict):
        return ''
    # 构建 (position, word) 列表
    pos_word: List[tuple] = []
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int):
                pos_word.append((pos, word))
    if not pos_word:
        return ''
    # 按位置排序后拼接
    pos_word.sort(key=lambda x: x[0])
    return ' '.join(word for _, word in pos_word)


def _json_loads(raw: bytes) -> Optional[Dict]:
    """安全解析 JSON，失败返回 None"""
    try:
        return json.loads(_decode_bytes(raw))
    except (json.JSONDecodeError, ValueError):
        return None


# ============================================================
# 1. OpenAlex 引擎
# ============================================================

class OpenAlexEngine(SearchEngine):
    """
    OpenAlex 学术元数据搜索引擎

    能力：search, academic
    数据量：474M+ 作品
    API Key：无需（可选邮箱参数用于 polite pool）
    国内可用：✅
    功能：元数据搜索 + 引用分析 + 概念标签

    API 文档：https://docs.openalex.org/
    """

    # OpenAlex Works 搜索端点
    SEARCH_URL = "https://api.openalex.org/works"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="openalex",
            layer=1,
            description="OpenAlex 开放学术元数据（474M+ 作品，含引用分析与概念标签）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=45,
            capabilities=["search", "academic"],
        )

    def is_available(self) -> bool:
        """
        检查 OpenAlex API 是否可达

        OpenAlex 无需 API Key，仅检测 API 端点连通性。
        为避免每次都发请求，仅在轻量端点做一次连通性测试。
        """
        try:
            # 用极小的查询测试连通性
            params = urllib.parse.urlencode({'search': 'test', 'per-page': 1})
            url = f"{self.SEARCH_URL}?{params}"
            raw = _http_get(url, timeout=10, max_retries=1)
            return raw is not None
        except Exception:
            return False

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        OpenAlex 元数据搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数（per-page，上限 200）
            **kwargs:
                mailto: 邮箱（进入 polite pool，提升速率）
                proxy: 代理地址
                filter: OpenAlex 过滤器（如 'from_publication_date:2020-01-01'）

        Returns:
            SearchResult 列表，失败返回 None
        """
        # 限制 per-page 上限
        per_page = max(1, min(int(max_results), 200))
        params_dict: Dict[str, str] = {
            'search': query,
            'per-page': str(per_page),
        }
        # 可选邮箱（polite pool）
        mailto = kwargs.get('mailto') or os.environ.get('OPENALEX_MAILTO', '')
        if mailto:
            params_dict['mailto'] = mailto
        # 可选过滤器
        if kwargs.get('filter'):
            params_dict['filter'] = str(kwargs['filter'])

        params = urllib.parse.urlencode(params_dict)
        url = f"{self.SEARCH_URL}?{params}"

        raw = _http_get(url, timeout=20, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        data = _json_loads(raw)
        if not data or 'results' not in data:
            return None

        results: List[SearchResult] = []
        for item in data.get('results', [])[:per_page]:
            # 标题
            title = item.get('display_name') or item.get('title') or ''
            # URL（优先 landing_page_url，回退到 id）
            url_str = item.get('primary_location', {}).get('landing_page_url') or \
                      item.get('doi_url') or item.get('id', '')
            # 作者列表
            authorships = item.get('authorships', []) or []
            author_names = []
            for a in authorships:
                author_obj = a.get('author') or {}
                name = author_obj.get('display_name') or ''
                if name:
                    author_names.append(name)
            author_str = '; '.join(author_names[:10])
            if len(author_names) > 10:
                author_str += f' et al. ({len(author_names)} authors)'
            # 摘要（倒排索引还原）
            abstract = _restore_abstract(item.get('abstract_inverted_index'))
            # 概念标签（取 score 最高的前 5 个）
            concepts = item.get('concepts', []) or []
            concept_names = []
            for c in concepts[:5]:
                cname = c.get('display_name') or ''
                if cname:
                    concept_names.append(cname)
            # 引用数
            cited_by_count = item.get('cited_by_count', 0) or 0
            # 发布日期
            pub_date = item.get('publication_date', '') or ''

            # 构建内容片段：摘要 + 概念标签 + 引用数
            content_parts = []
            if abstract:
                content_parts.append(abstract)
            if concept_names:
                content_parts.append(f"[Concepts] {', '.join(concept_names)}")
            if cited_by_count:
                content_parts.append(f"[Cited by {cited_by_count}]")
            content = '\n'.join(content_parts)

            # 评分：用 cited_by_count 作为权威性参考（归一化到 0-1）
            score = min(float(cited_by_count) / 100.0, 1.0) if cited_by_count else 0.0

            results.append(SearchResult(
                title=title,
                url=url_str,
                content=content,
                source='openalex',
                score=score,
                published_date=pub_date,
                author=author_str,
                engine='openalex',
                raw=item,
            ))

        return results if results else None


# ============================================================
# 2. Semantic Scholar 引擎
# ============================================================

class SemanticScholarEngine(SearchEngine):
    """
    Semantic Scholar 学术搜索引擎（Allen AI）

    能力：search, academic
    数据量：200M+ 论文
    API Key：可选（S2_API_KEY，无 Key 时限 100 次/5分钟）
    国内可用：✅
    功能：AI 引用上下文 + TLDR + influential citations

    API 文档：https://api.semanticscholar.org/api-docs/
    """

    # Semantic Scholar Paper Search 端点
    SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    # 请求字段
    FIELDS = "title,url,abstract,year,authors,citationCount,influentialCitationCount,tldr"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="semantic-scholar",
            layer=1,
            description="Semantic Scholar 学术搜索（200M+ 论文，含 TLDR 与 influential citations）",
            requires_config=False,
            config_keys=["S2_API_KEY"],
            is_async_supported=False,
            is_china_friendly=True,
            priority=46,
            capabilities=["search", "academic"],
        )

    def is_available(self) -> bool:
        """
        检查 Semantic Scholar API 是否可达

        无需 API Key 也可调用（仅速率受限），检测连通性即可。
        """
        try:
            params = urllib.parse.urlencode({
                'query': 'test',
                'limit': 1,
                'fields': 'title',
            })
            url = f"{self.SEARCH_URL}?{params}"
            # 不带 API Key 测试
            raw = _http_get(url, timeout=10, max_retries=1)
            return raw is not None
        except Exception:
            return False

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        Semantic Scholar 论文搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数（limit，上限 100）
            **kwargs:
                api_key: S2 API Key（默认读 S2_API_KEY 环境变量）
                proxy: 代理地址
                year: 年份过滤（如 '2020-2024'）
                fields_of_study: 学科过滤（如 'Computer Science'）

        Returns:
            SearchResult 列表，失败返回 None
        """
        # 限制 limit 上限
        limit = max(1, min(int(max_results), 100))
        params_dict: Dict[str, str] = {
            'query': query,
            'limit': str(limit),
            'fields': self.FIELDS,
        }
        # 可选过滤参数
        if kwargs.get('year'):
            params_dict['year'] = str(kwargs['year'])
        if kwargs.get('fields_of_study'):
            params_dict['fieldsOfStudy'] = str(kwargs['fields_of_study'])

        params = urllib.parse.urlencode(params_dict)
        url = f"{self.SEARCH_URL}?{params}"

        # 可选 API Key
        api_key = kwargs.get('api_key') or os.environ.get('S2_API_KEY', '')
        headers: Dict[str, str] = {}
        if api_key:
            headers['x-api-key'] = api_key

        raw = _http_get(url, headers=headers, timeout=20, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        data = _json_loads(raw)
        if not data or 'data' not in data:
            return None

        results: List[SearchResult] = []
        for item in data.get('data', [])[:limit]:
            # 标题
            title = item.get('title', '') or ''
            # URL
            url_str = item.get('url', '') or ''
            # 摘要
            abstract = item.get('abstract', '') or ''
            # TLDR（AI 生成的一句话摘要）
            tldr_obj = item.get('tldr')
            tldr_text = ''
            if isinstance(tldr_obj, dict):
                tldr_text = tldr_obj.get('text', '') or ''
            # 作者
            authors = item.get('authors', []) or []
            author_names = []
            for a in authors:
                name = a.get('name', '') or ''
                if name:
                    author_names.append(name)
            author_str = '; '.join(author_names[:10])
            if len(author_names) > 10:
                author_str += f' et al. ({len(author_names)} authors)'
            # 引用数
            citation_count = item.get('citationCount', 0) or 0
            influential_count = item.get('influentialCitationCount', 0) or 0
            # 年份
            year = item.get('year')
            pub_date = str(year) if year else ''

            # 构建内容片段
            content_parts = []
            if tldr_text:
                content_parts.append(f"[TLDR] {tldr_text}")
            if abstract:
                content_parts.append(abstract)
            if influential_count:
                content_parts.append(f"[Influential citations: {influential_count}]")
            if citation_count:
                content_parts.append(f"[Cited by {citation_count}]")
            content = '\n'.join(content_parts)

            # 评分：综合 citationCount 与 influentialCitationCount
            score = min(
                (float(citation_count) / 50.0 + float(influential_count) / 10.0) / 2.0,
                1.0,
            ) if (citation_count or influential_count) else 0.0

            results.append(SearchResult(
                title=title,
                url=url_str,
                content=content,
                source='semantic-scholar',
                score=score,
                published_date=pub_date,
                author=author_str,
                engine='semantic-scholar',
                raw=item,
            ))

        return results if results else None


# ============================================================
# 3. PubMed 引擎
# ============================================================

class PubmedEngine(SearchEngine):
    """
    PubMed 医学文献搜索引擎（NCBI E-utilities）

    能力：search, academic
    数据量：36M+ 医学文献
    API Key：无需（可选 NCBI_API_KEY 提高速率）
    国内可用：✅
    功能：医学文献搜索 + MeSH 词表

    API 文档：https://www.ncbi.nlm.nih.gov/books/NBK25501/
    """

    # E-utilities 端点
    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="pubmed",
            layer=1,
            description="PubMed 医学文献搜索（36M+ 医学文献，含 MeSH 词表）",
            requires_config=False,
            config_keys=["NCBI_API_KEY"],
            is_async_supported=False,
            is_china_friendly=True,
            priority=47,
            capabilities=["search", "academic"],
        )

    def is_available(self) -> bool:
        """
        检查 NCBI E-utilities 是否可达

        无需 API Key，仅检测 esearch 端点连通性。
        """
        try:
            params = urllib.parse.urlencode({
                'db': 'pubmed',
                'term': 'test',
                'retmax': 1,
                'retmode': 'json',
            })
            url = f"{self.ESEARCH_URL}?{params}"
            raw = _http_get(url, timeout=10, max_retries=1)
            return raw is not None
        except Exception:
            return False

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        PubMed 医学文献搜索（两步：esearch 取 ID → esummary 取详情）

        Args:
            query: 搜索关键词（支持 PubMed 查询语法，如 'cancer[MeSH]'）
            max_results: 最大结果数（retmax，上限 200）
            **kwargs:
                api_key: NCBI API Key（默认读 NCBI_API_KEY 环境变量）
                proxy: 代理地址
                sort: 排序方式（如 'relevance', 'pub_date'）

        Returns:
            SearchResult 列表，失败返回 None
        """
        # 限制 retmax 上限
        retmax = max(1, min(int(max_results), 200))
        api_key = kwargs.get('api_key') or os.environ.get('NCBI_API_KEY', '')
        proxy = kwargs.get('proxy')

        # ---------- 第一步：esearch 获取 PMID 列表 ----------
        esearch_params: Dict[str, str] = {
            'db': 'pubmed',
            'term': query,
            'retmax': str(retmax),
            'retmode': 'json',
        }
        if api_key:
            esearch_params['api_key'] = api_key
        if kwargs.get('sort'):
            esearch_params['sort'] = str(kwargs['sort'])

        esearch_url = f"{self.ESEARCH_URL}?{urllib.parse.urlencode(esearch_params)}"
        raw = _http_get(esearch_url, timeout=20, proxy=proxy)
        if not raw:
            return None

        esearch_data = _json_loads(raw)
        if not esearch_data:
            return None

        # 解析 ID 列表（路径：esearchresult.idlist）
        esearch_result = esearch_data.get('esearchresult', {}) or {}
        id_list = esearch_result.get('idlist', []) or []
        if not id_list:
            return None

        # ---------- 第二步：esummary 获取详情 ----------
        ids_str = ','.join(str(pid) for pid in id_list[:retmax])
        esummary_params: Dict[str, str] = {
            'db': 'pubmed',
            'id': ids_str,
            'retmode': 'json',
        }
        if api_key:
            esummary_params['api_key'] = api_key

        esummary_url = f"{self.ESUMMARY_URL}?{urllib.parse.urlencode(esummary_params)}"
        raw = _http_get(esummary_url, timeout=20, proxy=proxy)
        if not raw:
            return None

        esummary_data = _json_loads(raw)
        if not esummary_data:
            return None

        # 解析详情（路径：result.{pmid}）
        result_obj = esummary_data.get('result', {}) or {}
        uids = result_obj.get('uids', []) or []

        results: List[SearchResult] = []
        for uid in uids:
            item = result_obj.get(str(uid)) or {}
            if not item:
                continue
            # 标题
            title = item.get('title', '') or ''
            # URL（构造 PubMed 永久链接）
            url_str = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
            # 作者
            authors = item.get('authors', []) or []
            author_names = []
            for a in authors:
                name = a.get('name', '') or ''
                if name:
                    author_names.append(name)
            author_str = '; '.join(author_names[:10])
            if len(author_names) > 10:
                author_str += f' et al. ({len(author_names)} authors)'
            # 摘要（esummary 不返回 abstract，用摘要构建片段）
            # esummary 的摘要信息在 'abstract' 字段（部分论文有）
            abstract = item.get('abstract', '') or ''
            # MeSH 词表
            mesh_terms = item.get('meshheadinglist', []) or []
            mesh_names = []
            for m in mesh_terms:
                name = m.get('name', '') or ''
                if name:
                    mesh_names.append(name)
            # 期刊
            journal = item.get('fulljournalname', '') or item.get('source', '') or ''
            # 发布日期
            pub_date = item.get('pubdate', '') or ''
            # DOI
            articleids = item.get('articleids', []) or []
            doi = ''
            for aid in articleids:
                if aid.get('idtype') == 'doi':
                    doi = aid.get('value', '') or ''
                    break

            # 构建内容片段
            content_parts = []
            if abstract:
                content_parts.append(abstract)
            if mesh_names:
                content_parts.append(f"[MeSH] {', '.join(mesh_names[:8])}")
            if journal:
                content_parts.append(f"[Journal] {journal}")
            if doi:
                content_parts.append(f"[DOI] {doi}")
            content = '\n'.join(content_parts)

            # 评分：PubMed 无明确评分，用有无 MeSH/DOI 作为质量参考
            score = 0.0
            if mesh_names:
                score += 0.3
            if doi:
                score += 0.2
            if abstract:
                score += 0.2
            score = min(score, 1.0)

            results.append(SearchResult(
                title=title,
                url=url_str,
                content=content,
                source='pubmed',
                score=score,
                published_date=pub_date,
                author=author_str,
                engine='pubmed',
                raw=item,
            ))

        return results if results else None
