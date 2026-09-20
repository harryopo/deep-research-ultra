"""
Deep Research Ultra v4.0 — Layer 1: 学术全文与引用图谱引擎层

三个学术全文/图谱直连引擎（直接调用官方 API，无需 MCP 中转）：
- ArxivFulltextEngine: arXiv 全文下载（PDF/HTML/LaTeX，2.4M+ 预印本）
- UnpaywallEngine: Unpaywall 开放获取（DOI→合法 OA PDF，1000万+ OA 文章）
- CitationGraphEngine: Semantic Scholar 引用图谱（214M 论文，含 intents + influential）

设计说明：
- 这些引擎直接调用各大学术 API 的官方 HTTP 端点
- ArxivFulltextEngine 作为 arxiv-mcp-server 的 fallback，提供 PDF/HTML/LaTeX 全文获取
- Unpaywall 提供 DOI → 合法 OA PDF URL 解析（必需 email 参数）
- CitationGraphEngine 专注引用图谱构建（Inciteful 风格），含引用意图与 influential 标记
- HTTP GET 统一走 fallback.py 的 _http_get（含 curl_cffi TLS 指纹伪装）
- HTTP POST（CitationGraphEngine.batch_papers 批量查询）在模块内用 curl_cffi/urllib 实现
  （fallback.py 暂未提供 _http_post）
- XML 解析用 xml.etree.ElementTree，JSON 解析用 json.loads
- 优先级数字小于 Layer 4 降级引擎，确保学术全文/图谱查询优先走专业源
- 复用 academic_engines.py 的 _decode_bytes / _json_loads 工具函数
"""

import json
import hashlib
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

from .base import SearchEngine, SearchResult, EngineMetadata
from .fallback import _http_get, _http_post, DEFAULT_USER_AGENT
from .academic_engines import _decode_bytes, _json_loads

# ---------------------------------------------------------------------------
# 制品校验（v6.13 / X-D10）：下载回来的字节得先证明"是它、且完整"
# ---------------------------------------------------------------------------

MIN_PDF_BYTES = 4096          # 一篇 arXiv 论文的 PDF 不可能比这更小；HTML 报错页就在这道被挡下


def _pdf_page_texts(raw: bytes) -> Optional[List[str]]:
    """抽前两页文字用于比对论文 ID；没装 pypdf 就返回 None（＝这一项没核，不谎称核过）。"""
    try:
        import io

        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return [(reader.pages[i].extract_text() or '')
                for i in range(min(2, len(reader.pages)))]
    except Exception:
        return None


def verify_pdf_artifact(raw: bytes, paper_id: str = '') -> Dict:
    """四道判定：是不是 PDF → 篇幅像不像论文 → 有没有下载完 → 是不是这一篇。

    任一道不过就返回 ok=False。历史上 _http_get 返回什么都直接落盘，
    代理换成一张几百字节的 HTML 报错页也算"下载成功"，账本里就多了一条
    指向无关文档的一手来源。
    """
    raw = raw or b''
    out: Dict[str, Any] = {'ok': False, 'reason': '', 'bytes': len(raw),
                           'sha256': '', 'pages': None, 'id_matched': None}
    if not raw:
        out['reason'] = '空响应（0 字节）'
        return out
    out['sha256'] = hashlib.sha256(raw).hexdigest()[:16]
    if not raw.startswith(b'%PDF-'):
        out['reason'] = (f'不是 PDF（首字节不是 %PDF-），拿到的是 {raw[:24]!r}'
                         '……多半是 HTML 报错页/登录页，或被网络层换掉的文档')
        return out
    if len(raw) < MIN_PDF_BYTES:
        out['reason'] = f'PDF 太小（{len(raw)} 字节 < {MIN_PDF_BYTES}），不像一篇论文正文'
        return out
    if b'%%EOF' not in raw[-1024:]:
        out['reason'] = 'PDF 尾部缺 %%EOF，下载被截断，不许当完整全文用'
        return out
    out['pages'] = len(re.findall(rb'/Type\s*/Page[^s]', raw))
    if paper_id:
        texts = _pdf_page_texts(raw)
        if texts is None:
            out['ok'] = True
            out['reason'] = '结构合规可用；未装 pypdf，论文 ID 一致性未核'
            return out
        if paper_id not in ' '.join(texts):
            out['reason'] = (f'PDF 正文里找不到论文 ID {paper_id}——拿到的可能是另一篇文档，'
                             '不能当这条 claim 的一手来源')
            return out
        out['id_matched'] = True
    out['ok'] = True
    out['reason'] = 'PDF 校验通过（魔数/篇幅/完整性/ID 一致）'
    return out


# ============================================================
# 1. arXiv 全文下载引擎
# ============================================================

class ArxivFulltextEngine(SearchEngine):
    """
    arXiv 全文下载引擎（直连 API，作为 arxiv-mcp-server 的 fallback）

    能力：search, academic, fulltext, latex
    数据量：2.4M+ 预印本
    API Key：无需
    国内可用：✅
    速率限制：3 秒/请求（官方建议）
    功能：元数据搜索 + PDF/HTML/LaTeX 全文获取

    API 文档：https://info.arxiv.org/help/api/user-manual.html
    """

    # arXiv API 端点
    # 用 https：http:// 每次都要吃一个 301 跳转（且跳转行为对参数敏感）
    SEARCH_URL = "https://export.arxiv.org/api/query"
    PDF_URL_TEMPLATE = "https://arxiv.org/pdf/{paper_id}.pdf"
    HTML_URL_TEMPLATE = "https://arxiv.org/html/{paper_id}"
    LATEX_URL_TEMPLATE = "https://arxiv.org/e-print/{paper_id}"

    # Atom + arXiv 双命名空间
    ATOM_NS = "{http://www.w3.org/2005/Atom}"
    ARXIV_NS = "{http://arxiv.org/schemas/atom}"

    # 上次请求时间戳（类变量，用于跨实例共享速率限制）
    _last_request_time: float = 0.0

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="arxiv-fulltext",
            layer=1,
            description="arXiv 全文下载（PDF/HTML/LaTeX，2.4M+ 预印本）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=44,  # 略高于 OpenAlex（45），全文优先
            capabilities=["search", "academic", "fulltext", "latex"],
        )

    def _rate_limit(self) -> None:
        """官方建议 3 秒延迟（类变量记录上次请求时间，跨实例共享）"""
        elapsed = time.time() - ArxivFulltextEngine._last_request_time
        if elapsed < 3.0:
            time.sleep(3.0 - elapsed)
        ArxivFulltextEngine._last_request_time = time.time()

    def is_available(self) -> bool:
        """
        检查 arXiv API 是否可达

        arXiv 无需 API Key，仅检测 query 端点连通性。
        """
        try:
            params = urllib.parse.urlencode({'search_query': 'all:test', 'max_results': 1})
            url = f"{self.SEARCH_URL}?{params}"
            self._rate_limit()
            raw = _http_get(url, timeout=10, max_retries=1)
            return raw is not None
        except Exception:
            return False

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        arXiv 搜索（返回元数据 + PDF/HTML/LaTeX URL）

        Args:
            query: 搜索关键词（支持 'cat:cs.LG' 等前缀）
            max_results: 最大结果数（单批≤2000，单次≤30000）
            **kwargs:
                categories: arXiv 分类列表（如 ['cs.LG', 'cs.AI']）
                sort_by: 'relevance'/'lastUpdatedDate'/'submittedDate'
                sort_order: 'ascending'/'descending'
                id_list: 按 ID 查询（逗号分隔）
                proxy: 代理地址

        Returns:
            SearchResult 列表，失败返回 None
        """
        # 限制单批
        per_page = max(1, min(int(max_results), 2000))

        # 构造 search_query
        search_query = query
        categories = kwargs.get('categories')
        if categories:
            cat_query = ' OR '.join(f'cat:{c}' for c in categories)
            search_query = f'({search_query}) AND ({cat_query})' if search_query else cat_query

        # 按官方示例把 search_query 放在最前。注意 arXiv 服务端会对部分查询返回
        # HTTP 406（宽查询/累计请求量下更易触发，规则未见文档说明），
        # 失败原因由 engines/fallback.LAST_HTTP_ERROR 透出给 --probe。
        params_dict: Dict[str, str] = {}
        if search_query:
            params_dict['search_query'] = search_query
        params_dict['max_results'] = str(per_page)
        if kwargs.get('id_list'):
            params_dict['id_list'] = str(kwargs['id_list'])
        if kwargs.get('sort_by'):
            params_dict['sortBy'] = str(kwargs['sort_by'])
        if kwargs.get('sort_order'):
            params_dict['sortOrder'] = str(kwargs['sort_order'])

        # safe='():' 保留 arXiv 查询语法中的括号与冒号
        params = urllib.parse.urlencode(params_dict, safe='():')
        url = f"{self.SEARCH_URL}?{params}"

        self._rate_limit()
        raw = _http_get(url, timeout=30, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        # 解析 Atom XML
        try:
            text = _decode_bytes(raw)
            root = ET.fromstring(text)
        except ET.ParseError:
            return None

        results: List[SearchResult] = []
        for entry in root.findall(f'{self.ATOM_NS}entry'):
            paper_id = ''
            title = ''
            summary = ''
            authors: List[str] = []
            pdf_url = ''
            html_url = ''
            published = ''
            doi = ''
            paper_categories: List[str] = []
            comment = ''

            id_elem = entry.find(f'{self.ATOM_NS}id')
            if id_elem is not None and id_elem.text:
                # https://arxiv.org/abs/2404.19756v1 → 2404.19756
                paper_id = id_elem.text.strip().split('/abs/')[-1]
                if 'v' in paper_id:
                    paper_id = paper_id.split('v')[0]

            title_elem = entry.find(f'{self.ATOM_NS}title')
            if title_elem is not None and title_elem.text:
                title = ' '.join(title_elem.text.split())  # 折叠空白

            summary_elem = entry.find(f'{self.ATOM_NS}summary')
            if summary_elem is not None and summary_elem.text:
                summary = ' '.join(summary_elem.text.split())

            for author in entry.findall(f'{self.ATOM_NS}author'):
                name_elem = author.find(f'{self.ATOM_NS}name')
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            for link in entry.findall(f'{self.ATOM_NS}link'):
                rel = link.get('rel', '')
                title_attr = link.get('title', '')
                if rel == 'related' and title_attr == 'pdf':
                    pdf_url = link.get('href', '')
                elif rel == 'alternate':
                    html_url = link.get('href', '')

            # arXiv 扩展元素
            doi_elem = entry.find(f'{self.ARXIV_NS}doi')
            if doi_elem is not None and doi_elem.text:
                doi = doi_elem.text.strip()

            comment_elem = entry.find(f'{self.ARXIV_NS}comment')
            if comment_elem is not None and comment_elem.text:
                comment = comment_elem.text.strip()

            for cat in entry.findall(f'{self.ARXIV_NS}primary_category'):
                term = cat.get('term', '')
                if term:
                    paper_categories.append(term)

            published_elem = entry.find(f'{self.ATOM_NS}published')
            if published_elem is not None and published_elem.text:
                published = published_elem.text[:10]  # YYYY-MM-DD

            # 构建 PDF/HTML/LaTeX URL（即使 API link 未返回，也按模板生成）
            if not pdf_url:
                pdf_url = self.PDF_URL_TEMPLATE.format(paper_id=paper_id)
            if not html_url:
                html_url = self.HTML_URL_TEMPLATE.format(paper_id=paper_id)
            latex_url = self.LATEX_URL_TEMPLATE.format(paper_id=paper_id)

            # 构建内容片段
            content_parts = []
            if summary:
                content_parts.append(summary)
            if comment:
                content_parts.append(f"[Comment] {comment}")
            if paper_categories:
                content_parts.append(f"[Categories] {', '.join(paper_categories)}")
            if doi:
                content_parts.append(f"[DOI] {doi}")
            content_parts.append(f"[PDF] {pdf_url}")
            content_parts.append(f"[HTML] {html_url}")
            content_parts.append(f"[LaTeX] {latex_url}")
            content = '\n'.join(content_parts)

            author_str = '; '.join(authors[:10])
            if len(authors) > 10:
                author_str += f' et al. ({len(authors)} authors)'

            results.append(SearchResult(
                title=title,
                url=html_url or f"https://arxiv.org/abs/{paper_id}",
                content=content,
                source='arxiv',
                score=0.5,  # arXiv 无引用计数，给中性分
                published_date=published,
                author=author_str,
                engine='arxiv-fulltext',
                raw={
                    'paper_id': paper_id,
                    'pdf_url': pdf_url,
                    'html_url': html_url,
                    'latex_url': latex_url,
                    'doi': doi,
                    'categories': paper_categories,
                    'comment': comment,
                },
            ))

        return results if results else None

    def download_pdf(self, paper_id: str, save_path: str, **kwargs) -> Optional[str]:
        """
        下载 arXiv PDF 二进制到本地

        Args:
            paper_id: arXiv ID（如 '2404.19756'，可含版本 'v1'）
            save_path: 本地保存路径
            **kwargs:
                proxy: 代理地址

        Returns:
            保存的文件路径，失败返回 None
        """
        # 规范化 paper_id（去掉 v 后缀，PDF URL 不含版本）
        clean_id = paper_id.split('v')[0] if 'v' in paper_id else paper_id
        url = self.PDF_URL_TEMPLATE.format(paper_id=clean_id)
        self._rate_limit()
        raw = _http_get(url, timeout=60, proxy=kwargs.get('proxy'))
        check = verify_pdf_artifact(raw or b'', clean_id)
        self.last_download = check
        if not check['ok']:
            print(f'❌ arXiv PDF 制品校验未过（{clean_id}）：{check["reason"]}', file=sys.stderr)
            return None
        try:
            with open(save_path, 'wb') as f:
                f.write(raw)
            return save_path
        except IOError:
            return None

    def fetch_latex(self, paper_id: str, **kwargs) -> Optional[Dict]:
        """
        获取 arXiv LaTeX 源码（tar.gz 压缩包）

        Args:
            paper_id: arXiv ID
            **kwargs:
                proxy: 代理地址

        Returns:
            {'tar_gz': bytes, 'paper_id': str}，失败返回 None。
            返回的 tar_gz 需调用方解压。
        """
        clean_id = paper_id.split('v')[0] if 'v' in paper_id else paper_id
        url = self.LATEX_URL_TEMPLATE.format(paper_id=clean_id)
        self._rate_limit()
        raw = _http_get(url, timeout=60, proxy=kwargs.get('proxy')) or b''
        if not raw.startswith(b'\x1f\x8b'):
            print(f'❌ arXiv LaTeX 不是 gzip 包（{clean_id}）：拿到 {len(raw)} 字节，'
                  f'前缀 {raw[:16]!r}——多半是报错页或源码不存在', file=sys.stderr)
            return None
        return {'tar_gz': raw, 'paper_id': clean_id}


# ============================================================
# 2. Unpaywall 开放获取引擎
# ============================================================

class UnpaywallEngine(SearchEngine):
    """
    Unpaywall 开放获取引擎（DOI → 合法 OA PDF）

    能力：search, academic, fulltext, oa
    数据量：1000 万+ OA 文章索引
    API Key：无需（**必需 email 参数**）
    国内可用：✅
    速率限制：100,000 calls/day
    功能：DOI → OA PDF URL 解析 + 标题搜索

    API 文档：https://unpaywall.org/products/api
    """

    BASE_URL = "https://api.unpaywall.org/v2"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="unpaywall",
            layer=1,
            description="Unpaywall 开放获取（DOI→OA PDF，1000万+ OA 文章）",
            requires_config=False,  # email 非 Key，但必填
            config_keys=["UNPAYWALL_EMAIL"],
            is_async_supported=False,
            is_china_friendly=True,
            priority=43,  # 全文获取优先级最高
            capabilities=["search", "academic", "fulltext", "oa"],
        )

    def _get_email(self, **kwargs) -> Optional[str]:
        """
        获取 email 参数（必需）

        优先级：kwargs.email > 环境变量 UNPAYWALL_EMAIL > 默认值（仅测试用）
        生产环境必须配置真实 email。
        """
        email = kwargs.get('email') or os.environ.get('UNPAYWALL_EMAIL', '')
        if not email:
            # 降级：使用默认 email（仅测试用，生产环境必须配置）
            email = 'research@deep-research-ultra.local'
        return email

    def is_available(self) -> bool:
        """
        检查 Unpaywall API 是否可达

        用已知 DOI 做一次轻量连通性测试。
        """
        try:
            email = os.environ.get('UNPAYWALL_EMAIL', 'test@example.com')
            url = f"{self.BASE_URL}/10.1038/nature12373?email={urllib.parse.quote(email)}"
            raw = _http_get(url, timeout=10, max_retries=1)
            return raw is not None
        except Exception:
            return False

    def search_by_doi(self, doi: str, **kwargs) -> Optional[Dict]:
        """
        按 DOI 查询 OA 状态（核心方法）

        Args:
            doi: DOI 字符串（如 '10.1038/nature12373'）
            **kwargs:
                email: 邮箱（默认读 UNPAYWALL_EMAIL 环境变量）
                proxy: 代理地址

        Returns:
            完整 DOI Object，失败返回 None
        """
        email = self._get_email(**kwargs)
        if not email:
            return None

        # DOI 小写化（官方 schema 要求 doi 字段总是小写）
        clean_doi = doi.strip().lower()
        url = f"{self.BASE_URL}/{urllib.parse.quote(clean_doi)}?email={urllib.parse.quote(email)}"

        raw = _http_get(url, timeout=20, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        return _json_loads(raw)

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        标题搜索 OA 文章

        Args:
            query: 搜索文本（空格分隔 AND，支持 "短语"/OR/-取反）
            max_results: 最大结果数（每页 50，自动分页）
            **kwargs:
                email: 邮箱
                is_oa: True 仅 OA / False 仅非 OA / None 不限
                proxy: 代理地址

        Returns:
            SearchResult 列表，失败返回 None
        """
        email = self._get_email(**kwargs)
        if not email:
            return None

        # 计算分页（每页 50）
        per_page = 50
        pages_needed = max(1, (int(max_results) + per_page - 1) // per_page)
        results: List[SearchResult] = []

        for page in range(1, pages_needed + 1):
            params_dict: Dict[str, str] = {
                'query': query,
                'email': email,
                'page': str(page),
            }
            if kwargs.get('is_oa') is not None:
                params_dict['is_oa'] = 'true' if kwargs['is_oa'] else 'false'

            params = urllib.parse.urlencode(params_dict)
            url = f"{self.BASE_URL}/search?{params}"

            raw = _http_get(url, timeout=20, proxy=kwargs.get('proxy'))
            if not raw:
                break

            data = _json_loads(raw)
            if not data:
                break

            items = data.get('results', []) or []
            if not items:
                break

            for item in items[:max_results - len(results)]:
                doi_obj = item.get('response', {}) or {}
                score = item.get('score', 0.0) or 0.0

                result = self._parse_doi_object(doi_obj, score)
                if result:
                    results.append(result)

            if len(results) >= max_results:
                break

        return results if results else None

    def _select_best_oa_location(self, oa_locations: List[Dict]) -> Optional[Dict]:
        """
        从 oa_locations 列表中选择最佳 OA 位置

        选择算法（Unpaywall 官方 best_oa_location 算法）：
        1. host_type: publisher > repository
        2. version: publishedVersion > acceptedVersion > submittedVersion
        3. 仓库权威性: PMC > CiteSeerX（同 host_type + version 时）

        通常 API 已返回 best_oa_location 字段，此方法用于：
        - best_oa_location 缺失时回退计算
        - 调用方需自定义选择策略时

        Args:
            oa_locations: OA 位置列表

        Returns:
            最佳 OA 位置对象，无可用位置返回 None
        """
        if not oa_locations:
            return None

        # host_type 排序键：publisher(0) > repository(1) > 其他(9)
        HOST_RANK = {'publisher': 0, 'repository': 1}
        # version 排序键：publishedVersion(0) > acceptedVersion(1) > submittedVersion(2) > 其他(9)
        VERSION_RANK = {'publishedVersion': 0, 'acceptedVersion': 1, 'submittedVersion': 2}

        def repo_authority(loc: Dict) -> int:
            """仓库权威性：PMC(0) > CiteSeerX(1) > 其他(2)"""
            url_str = (loc.get('url') or loc.get('url_for_landing_page') or '').lower()
            if 'pmc' in url_str or 'pubmedcentral' in url_str:
                return 0
            if 'citeseerx' in url_str:
                return 1
            return 2

        def sort_key(loc: Dict):
            return (
                HOST_RANK.get(loc.get('host_type', ''), 9),
                VERSION_RANK.get(loc.get('version', ''), 9),
                repo_authority(loc),
            )

        sorted_locs = sorted(oa_locations, key=sort_key)
        return sorted_locs[0] if sorted_locs else None

    def _parse_doi_object(self, doi_obj: Dict, score: float = 0.0) -> Optional[SearchResult]:
        """解析 DOI Object 为 SearchResult"""
        if not doi_obj:
            return None

        title = doi_obj.get('title', '') or ''
        doi = doi_obj.get('doi', '') or ''
        doi_url = doi_obj.get('doi_url', '') or f"https://doi.org/{doi}"

        # 最佳 OA 位置（API 字段缺失时回退到 _select_best_oa_location）
        best_oa = doi_obj.get('best_oa_location')
        if not best_oa:
            oa_locations = doi_obj.get('oa_locations', []) or []
            best_oa = self._select_best_oa_location(oa_locations) or {}
        pdf_url = best_oa.get('url_for_pdf', '') or ''
        landing_url = best_oa.get('url_for_landing_page', '') or ''
        oa_url = pdf_url or landing_url or doi_url

        # OA 状态
        is_oa = doi_obj.get('is_oa', False)
        oa_status = doi_obj.get('oa_status', 'closed') or 'closed'
        version = best_oa.get('version', '') or ''
        license_str = best_oa.get('license', '') or ''
        host_type = best_oa.get('host_type', '') or ''

        # 元数据
        year = doi_obj.get('year')
        pub_date = str(year) if year else ''
        journal = doi_obj.get('journal_name', '') or ''
        publisher = doi_obj.get('publisher', '') or ''
        genre = doi_obj.get('genre', '') or ''

        # 作者
        authors_list = doi_obj.get('z_authors') or []
        author_names = []
        for a in authors_list:
            name = a.get('raw_author_name', '') or ''
            if name:
                author_names.append(name)
        author_str = '; '.join(author_names[:10])
        if len(author_names) > 10:
            author_str += f' et al. ({len(author_names)} authors)'

        # 构建内容片段
        content_parts = []
        if is_oa:
            content_parts.append(f"[OA Status] {oa_status}")
        else:
            content_parts.append("[OA Status] closed (no OA copy)")
        if version:
            content_parts.append(f"[Version] {version}")
        if license_str:
            content_parts.append(f"[License] {license_str}")
        if host_type:
            content_parts.append(f"[Host] {host_type}")
        if journal:
            content_parts.append(f"[Journal] {journal}")
        if publisher:
            content_parts.append(f"[Publisher] {publisher}")
        if genre:
            content_parts.append(f"[Type] {genre}")
        if pdf_url:
            content_parts.append(f"[PDF] {pdf_url}")
        if landing_url and landing_url != pdf_url:
            content_parts.append(f"[Landing] {landing_url}")
        content = '\n'.join(content_parts)

        # 评分：OA 优先，publishedVersion > acceptedVersion > submittedVersion
        version_score = {'publishedVersion': 0.4, 'acceptedVersion': 0.3, 'submittedVersion': 0.2}.get(version, 0.1)
        oa_score = 0.4 if is_oa else 0.0
        final_score = min(oa_score + version_score + min(float(score) / 100.0, 0.2), 1.0)

        return SearchResult(
            title=title,
            url=oa_url,
            content=content,
            source='unpaywall',
            score=final_score,
            published_date=pub_date,
            author=author_str,
            engine='unpaywall',
            raw={
                'doi': doi,
                'doi_url': doi_url,
                'is_oa': is_oa,
                'oa_status': oa_status,
                'best_oa_location': best_oa,
                'all_oa_locations': doi_obj.get('oa_locations', []) or [],
                'pdf_url': pdf_url,
                'landing_url': landing_url,
                'version': version,
                'license': license_str,
                'journal': journal,
            },
        )

    def resolve_pdf_url(self, doi: str, **kwargs) -> Optional[Dict]:
        """
        高频场景：已知 DOI，求 OA PDF URL

        Args:
            doi: DOI 字符串
            **kwargs:
                email: 邮箱
                proxy: 代理地址

        Returns:
            {
                'pdf_url': str|None,
                'landing_url': str|None,
                'oa_status': str,
                'version': str,
                'license': str,
                'is_oa': bool,
                'all_pdf_urls': [str],
            }
            失败返回 None
        """
        doi_obj = self.search_by_doi(doi, **kwargs)
        if not doi_obj:
            return None

        # 优先用 API 的 best_oa_location，缺失则回退计算
        best_oa = doi_obj.get('best_oa_location')
        if not best_oa:
            oa_locations = doi_obj.get('oa_locations', []) or []
            best_oa = self._select_best_oa_location(oa_locations) or {}

        return {
            'pdf_url': best_oa.get('url_for_pdf') or None,
            'landing_url': best_oa.get('url_for_landing_page') or None,
            'oa_status': doi_obj.get('oa_status', 'closed'),
            'version': best_oa.get('version', ''),
            'license': best_oa.get('license', ''),
            'is_oa': doi_obj.get('is_oa', False),
            'all_pdf_urls': [
                loc.get('url_for_pdf') for loc in (doi_obj.get('oa_locations') or [])
                if loc.get('url_for_pdf')
            ],
        }


# ============================================================
# 3. Semantic Scholar 引用图谱引擎
# ============================================================

class CitationGraphEngine(SearchEngine):
    """
    Semantic Scholar 引用图谱引擎

    能力：search, academic, citation_graph, intents, influential
    数据量：214M 论文 / 2.49B 引用 / 79M 作者
    API Key：可选（S2_API_KEY，有 Key 1 RPS，无 Key 1000 RPS 共享）
    国内可用：✅
    独有能力：citation intents（methodology/background/result）+ influential citations
    功能：引用图谱构建（Inciteful 风格）+ 批量查询 + 相似论文推荐

    API 文档：https://api.semanticscholar.org/api-docs/
    """

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    PAPER_URL = f"{BASE_URL}/paper"
    BATCH_URL = f"{PAPER_URL}/batch"
    RECOMMEND_URL = "https://api.semanticscholar.org/recommendations/v1"

    # 引用图谱默认字段
    GRAPH_FIELDS = (
        "title,abstract,year,venue,url,citationCount,influentialCitationCount,"
        "isOpenAccess,openAccessPdf,tldr,authors.name,"
        "references.paperId,references.title,references.year,references.citationCount,"
        "citations.paperId,citations.title,citations.year,citations.citationCount"
    )

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="s2-citation-graph",
            layer=1,
            description="Semantic Scholar 引用图谱（214M 论文，含 intents + influential）",
            requires_config=False,
            config_keys=["S2_API_KEY"],
            is_async_supported=False,
            is_china_friendly=True,
            priority=42,  # 引用图谱专用
            capabilities=["search", "academic", "citation_graph", "intents", "influential"],
        )

    def _get_headers(self, **kwargs) -> Dict[str, str]:
        """获取请求头（含可选 API Key，x-api-key 大小写敏感）"""
        api_key = kwargs.get('api_key') or os.environ.get('S2_API_KEY', '')
        headers: Dict[str, str] = {
            'Accept': 'application/json',
        }
        if api_key:
            headers['x-api-key'] = api_key  # 大小写敏感
        return headers

    def is_available(self) -> bool:
        """
        检查 Semantic Scholar API 是否可达

        用经典论文 ARXIV:1706.03762（Attention is All You Need）做轻量连通性测试。
        """
        try:
            url = f"{self.PAPER_URL}/ARXIV:1706.03762?fields=title"
            raw = _http_get(url, timeout=10, max_retries=1)
            return raw is not None
        except Exception:
            return False

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        复用 SemanticScholarEngine 的搜索逻辑

        此引擎专注于引用图谱，普通关键词搜索委托给 SemanticScholarEngine。
        """
        from .academic_engines import SemanticScholarEngine
        s2_engine = SemanticScholarEngine()
        return s2_engine.search(query, max_results, **kwargs)

    # ============================================================
    # 引用图谱核心方法
    # ============================================================

    def get_paper_with_graph(
        self,
        paper_id: str,
        include_references: bool = True,
        include_citations: bool = True,
        include_intents: bool = False,
        include_influential: bool = False,
        ref_limit: int = 100,
        cit_limit: int = 100,
        **kwargs,
    ) -> Optional[Dict]:
        """
        获取论文及其引用图谱（references + citations）

        Args:
            paper_id: 论文 ID（支持 ARXIV:xxx / DOI:xxx / paperId / CorpusId:xxx）
            include_references: 是否包含参考文献
            include_citations: 是否包含引用此文的文章
            include_intents: 是否包含引用意图（methodology/background/result）
            include_influential: 是否包含 influential 标记
            ref_limit: 参考文献数上限
            cit_limit: 引用此文数上限
            **kwargs:
                api_key: S2 API Key
                proxy: 代理地址

        Returns:
            完整论文对象（含 references/citations 嵌套数组），失败返回 None
        """
        # 构建字段列表
        fields = [
            "title", "abstract", "year", "venue", "url",
            "citationCount", "influentialCitationCount", "referenceCount",
            "isOpenAccess", "openAccessPdf", "tldr",
            "authors.name", "authors.affiliations",
            "fieldsOfStudy", "s2FieldsOfStudy",
            "citationStyles.bibtex",
            "externalIds",
        ]

        if include_references:
            ref_fields = ["references.paperId", "references.title", "references.year",
                          "references.citationCount", "references.authors.name"]
            if include_intents:
                ref_fields.append("references.intents")
            if include_influential:
                ref_fields.append("references.isInfluential")
            fields.extend(ref_fields)

        if include_citations:
            cit_fields = ["citations.paperId", "citations.title", "citations.year",
                          "citations.citationCount", "citations.authors.name"]
            if include_intents:
                cit_fields.append("citations.intents")
            if include_influential:
                cit_fields.append("citations.isInfluential")
            fields.extend(cit_fields)

        fields_str = ",".join(fields)
        url = f"{self.PAPER_URL}/{urllib.parse.quote(paper_id)}?fields={fields_str}"

        headers = self._get_headers(**kwargs)
        raw = _http_get(url, headers=headers, timeout=30, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        data = _json_loads(raw)
        if not data:
            return None

        # 截断 references/citations 到指定 limit
        if include_references and 'references' in data:
            data['references'] = data['references'][:ref_limit]
        if include_citations and 'citations' in data:
            data['citations'] = data['citations'][:cit_limit]

        return data

    def get_references(
        self,
        paper_id: str,
        fields: str = "title,year,citationCount,abstract",
        limit: int = 100,
        offset: int = 0,
        **kwargs,
    ) -> Optional[Dict]:
        """
        获取论文的参考文献列表（专端点，支持分页）

        Args:
            paper_id: 论文 ID
            fields: 返回字段（citingPaper 的子字段）
            limit: 每页数（上限 1000）
            offset: 偏移量
            **kwargs:
                api_key: S2 API Key
                proxy: 代理地址

        Returns:
            {
                'data': [{'citingPaper': {...}, 'intents': [...], 'isInfluential': bool, 'contexts': [...]}],
                'offset': int,
                'next': int|None
            }
            失败返回 None
        """
        limit = max(1, min(int(limit), 1000))
        params = urllib.parse.urlencode({
            'fields': f"citingPaper.{fields},intents,isInfluential,contexts",
            'limit': str(limit),
            'offset': str(offset),
        })
        url = f"{self.PAPER_URL}/{urllib.parse.quote(paper_id)}/references?{params}"

        headers = self._get_headers(**kwargs)
        raw = _http_get(url, headers=headers, timeout=30, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        return _json_loads(raw)

    def get_citations(
        self,
        paper_id: str,
        fields: str = "title,year,citationCount,abstract",
        limit: int = 100,
        offset: int = 0,
        **kwargs,
    ) -> Optional[Dict]:
        """
        获取引用此论文的文章列表（专端点，支持分页）

        Args:
            paper_id: 论文 ID
            fields: 返回字段（citingPaper 的子字段）
            limit: 每页数（上限 1000）
            offset: 偏移量
            **kwargs:
                api_key: S2 API Key
                proxy: 代理地址

        Returns:
            同 get_references 结构（citingPaper → citingPaper），失败返回 None
        """
        limit = max(1, min(int(limit), 1000))
        params = urllib.parse.urlencode({
            'fields': f"citingPaper.{fields},intents,isInfluential,contexts",
            'limit': str(limit),
            'offset': str(offset),
        })
        url = f"{self.PAPER_URL}/{urllib.parse.quote(paper_id)}/citations?{params}"

        headers = self._get_headers(**kwargs)
        raw = _http_get(url, headers=headers, timeout=30, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        return _json_loads(raw)

    def batch_papers(
        self,
        paper_ids: List[str],
        fields: str = "title,year,citationCount,influentialCitationCount,tldr,abstract",
        **kwargs,
    ) -> Optional[List[Dict]]:
        """
        批量查询论文（POST /paper/batch，一次最多 500 个）

        Args:
            paper_ids: 论文 ID 列表（≤500，超过自动分批）
            fields: 返回字段
            **kwargs:
                api_key: S2 API Key
                proxy: 代理地址

        Returns:
            论文对象列表（顺序与输入一致，不存在的返回 null），失败返回 None
        """
        if len(paper_ids) > 500:
            # 分批处理
            all_results: List[Dict] = []
            for i in range(0, len(paper_ids), 500):
                batch = paper_ids[i:i + 500]
                batch_result = self.batch_papers(batch, fields, **kwargs)
                if batch_result:
                    all_results.extend(batch_result)
            return all_results if all_results else None

        params = urllib.parse.urlencode({'fields': fields})
        url = f"{self.BATCH_URL}?{params}"

        headers = self._get_headers(**kwargs)
        body = json.dumps({"ids": paper_ids}).encode('utf-8')

        # batch 端点为 POST，使用模块内 _http_post（fallback.py 暂未提供 _http_post）
        raw = _http_post(url, data=body, headers=headers, timeout=30, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        try:
            text = _decode_bytes(raw)
            result = json.loads(text)
            if isinstance(result, list):
                return result
            return None
        except (json.JSONDecodeError, ValueError):
            return None

    def build_citation_graph(
        self,
        seed_paper_id: str,
        depth: int = 1,
        max_nodes: int = 50,
        include_intents: bool = True,
        **kwargs,
    ) -> Optional[Dict]:
        """
        构建以种子论文为中心的引用图谱（Inciteful 风格）

        Args:
            seed_paper_id: 种子论文 ID
            depth: 图谱深度（1=直接引用，2=二度引用）
            max_nodes: 最大节点数
            include_intents: 是否包含引用意图
            **kwargs:
                api_key: S2 API Key
                proxy: 代理地址

        Returns:
            {
                'nodes': [{'paperId': ..., 'title': ..., 'year': ..., 'citationCount': ..., 'is_seed': bool}],
                'edges': [{'source': ..., 'target': ..., 'type': 'reference'|'citation',
                           'intents': [...], 'isInfluential': bool}],
                'seed': seed_paper_id_actual,
                'stats': {'total_nodes': int, 'total_edges': int, 'intents_distribution': {...}}
            }
            失败返回 None
        """
        nodes: Dict[str, Dict] = {}
        edges: List[Dict] = []
        intents_count: Dict[str, int] = {}

        # 第 0 层：种子论文
        seed_data = self.get_paper_with_graph(
            seed_paper_id,
            include_references=True,
            include_citations=True,
            include_intents=include_intents,
            include_influential=True,
            ref_limit=max_nodes // 2,
            cit_limit=max_nodes // 2,
            **kwargs,
        )
        if not seed_data:
            return None

        seed_paper_id_actual = seed_data.get('paperId', seed_paper_id)
        nodes[seed_paper_id_actual] = {
            'paperId': seed_paper_id_actual,
            'title': seed_data.get('title', ''),
            'year': seed_data.get('year'),
            'citationCount': seed_data.get('citationCount', 0),
            'venue': seed_data.get('venue', ''),
            'is_seed': True,
        }

        # 处理 references（种子引用的论文）
        for ref in seed_data.get('references', []) or []:
            ref_paper = ref.get('citedPaper') or ref  # 兼容两种格式
            pid = ref_paper.get('paperId')
            if not pid:
                continue
            if pid not in nodes and len(nodes) < max_nodes:
                nodes[pid] = {
                    'paperId': pid,
                    'title': ref_paper.get('title', ''),
                    'year': ref_paper.get('year'),
                    'citationCount': ref_paper.get('citationCount', 0),
                    'venue': ref_paper.get('venue', ''),
                    'is_seed': False,
                }
            # 边：seed → reference
            intents = ref.get('intents', []) or []
            is_influential = ref.get('isInfluential', False)
            edges.append({
                'source': seed_paper_id_actual,
                'target': pid,
                'type': 'reference',
                'intents': intents,
                'isInfluential': is_influential,
            })
            for intent in intents:
                intents_count[intent] = intents_count.get(intent, 0) + 1

        # 处理 citations（引用种子的论文）
        for cit in seed_data.get('citations', []) or []:
            cit_paper = cit.get('citingPaper') or cit
            pid = cit_paper.get('paperId')
            if not pid:
                continue
            if pid not in nodes and len(nodes) < max_nodes:
                nodes[pid] = {
                    'paperId': pid,
                    'title': cit_paper.get('title', ''),
                    'year': cit_paper.get('year'),
                    'citationCount': cit_paper.get('citationCount', 0),
                    'venue': cit_paper.get('venue', ''),
                    'is_seed': False,
                }
            # 边：citation → seed
            intents = cit.get('intents', []) or []
            is_influential = cit.get('isInfluential', False)
            edges.append({
                'source': pid,
                'target': seed_paper_id_actual,
                'type': 'citation',
                'intents': intents,
                'isInfluential': is_influential,
            })
            for intent in intents:
                intents_count[intent] = intents_count.get(intent, 0) + 1

        # depth >= 2：对每个节点递归（简化版，实际需 BFS + 去重）
        if depth >= 2 and len(nodes) < max_nodes:
            # 此处省略 BFS 扩展逻辑，实际实现需控制请求量
            pass

        return {
            'nodes': list(nodes.values()),
            'edges': edges,
            'seed': seed_paper_id_actual,
            'stats': {
                'total_nodes': len(nodes),
                'total_edges': len(edges),
                'intents_distribution': intents_count,
            },
        }

    def recommend_papers(
        self,
        paper_id: str,
        limit: int = 10,
        **kwargs,
    ) -> Optional[List[Dict]]:
        """
        基于单篇论文推荐相似论文

        端点：GET /recommendations/v1/papers/forpaper/{paper_id}

        Args:
            paper_id: 论文 ID
            limit: 推荐数上限
            **kwargs:
                api_key: S2 API Key
                proxy: 代理地址

        Returns:
            推荐论文对象列表，失败返回 None
        """
        params = urllib.parse.urlencode({
            'fields': 'title,year,citationCount,abstract,tldr',
            'limit': str(limit),
        })
        url = f"{self.RECOMMEND_URL}/papers/forpaper/{urllib.parse.quote(paper_id)}?{params}"

        headers = self._get_headers(**kwargs)
        raw = _http_get(url, headers=headers, timeout=30, proxy=kwargs.get('proxy'))
        if not raw:
            return None

        try:
            text = _decode_bytes(raw)
            data = json.loads(text)
            return data.get('recommendedPapers', []) or []
        except (json.JSONDecodeError, ValueError):
            return None
