"""
Deep Research Ultra v5.2 — Layer 2: 国内内容源引擎层

解决"国内深度研究适配"问题的核心引擎。

设计理念（来自国内智能体平台与调研专家团调研报告）：
- 国内内容源（知乎/微信/CSDN/掘金/B站）大多无公开 API
- 通过搜狗作为代理搜索知乎/微信公众号内容
- 百度学术作为国内学术搜索补充
- 百度 SERP 作为国内搜索兜底
- 配合 Crawl4AI 浏览器自动化突破"无 API 私域源"

4 个引擎：
1. BaiduSerpEngine: 百度搜索 SERP（HTML 解析，含知乎/CSDN/掘金等国内站点）
2. SogouWeixinEngine: 搜狗微信搜索（微信公众号文章）
3. SogouZhihuEngine: 搜狗知乎搜索（知乎问答）
4. BaiduXueshuEngine: 百度学术（国内学术论文）

HTTP 请求统一走 fallback.py 的 _http_get（含 curl_cffi TLS 指纹伪装）
HTML 解析使用正则提取（国内站点 HTML 结构变化频繁，仅提取关键信息）
"""

import re
import time
import urllib.parse
from typing import Dict, List, Optional

from .base import SearchEngine, SearchResult, EngineMetadata
from .fallback import (_http_get, _decode_html, DEFAULT_USER_AGENT,
                      _is_http_url, _stub_page)


# ============================================================
# 1. 百度搜索 SERP 引擎
# ============================================================

class BaiduSerpEngine(SearchEngine):
    """
    百度搜索 SERP 引擎（国内搜索主力）

    能力：search, cn_source
    数据量：百度索引的全网中文内容
    API Key：无需
    国内可用：✅（国内主力搜索）
    功能：通用搜索 + 知乎/CSDN/掘金等国内站点内容

    与 fallback.py 的 BaiduHtmlEngine 区别：
    - BaiduHtmlEngine 是 Layer 4 降级引擎（最后手段）
    - BaiduSerpEngine 是 Layer 2 主动引擎（国内内容源主力）
    - BaiduSerpEngine 增强了中文内容提取和站点识别
    """

    SEARCH_URL = "https://www.baidu.com/s"

    # 国内技术站点域名识别
    CN_TECH_SITES = {
        'zhihu.com': '知乎',
        'csdn.net': 'CSDN',
        'juejin.cn': '掘金',
        'segmentfault.com': 'SegmentFault',
        'cnblogs.com': '博客园',
        'jianshu.com': '简书',
        'oschina.net': '开源中国',
        'gitee.com': 'Gitee',
        'bilibili.com': 'B站',
        'weixin.qq.com': '微信公众号',
    }

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="baidu-serp",
            layer=2,
            description="百度搜索 SERP（国内搜索主力，含知乎/CSDN/掘金等）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=80,
            capabilities=["search", "cn_source"],
        )

    def is_available(self) -> bool:
        """百度在国内始终可用"""
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        百度搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                site: 站点限定（如 'zhihu.com'）
                page: 页码（默认 1）
                proxy: 代理
        """
        site = kwargs.get('site', '')
        page = kwargs.get('page', 1)
        proxy = kwargs.get('proxy')

        params_dict = {
            'wd': query,
            'rn': str(min(max_results * 2, 50)),  # 多取一些用于过滤
            'pn': str((page - 1) * max_results),
            'ie': 'utf-8',
        }
        if site:
            params_dict['wd'] = f"{query} site:{site}"

        params = urllib.parse.urlencode(params_dict)
        url = f"{self.SEARCH_URL}?{params}"

        raw = _http_get(url, timeout=15, proxy=proxy, impersonate="chrome124")
        if not raw or _stub_page(raw):
            return None

        html = _decode_html(raw)
        results = self._parse_baidu_results(html, max_results)

        return results   # 取数成功但一条没解析出来＝0 结果，不是通道故障；None 会让断路器把引擎记成不可用

    def _parse_baidu_results(self, html: str, max_results: int) -> List[SearchResult]:
        """解析百度搜索结果页 HTML"""
        results: List[SearchResult] = []

        # 百度搜索结果通常在 class="result" 或 class="c-container" 的 div 中
        # 提取标题和链接
        # 模式1: <h3 class="t"><a href="...">标题</a></h3>
        title_pattern = re.compile(
            r'<h3[^>]*class="[^"]*t[^"]*"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        # 摘要模式
        snippet_pattern = re.compile(
            r'<span[^>]*class="content-right_[^"]*"[^>]*>(.*?)</span>',
            re.DOTALL,
        )
        snippet_fallback = re.compile(
            r'<div[^>]*class="c-abstract[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL,
        )

        titles = title_pattern.findall(html)
        snippets = snippet_pattern.findall(html)
        if not snippets:
            snippets = snippet_fallback.findall(html)

        for i, (url, title_html) in enumerate(titles[:max_results]):
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if not title or not _is_http_url(url):   # 伪链接不是结果
                continue

            snippet = ''
            if i < len(snippets):
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()

            # 识别国内技术站点
            site_name = ''
            for domain, name in self.CN_TECH_SITES.items():
                if domain in url or domain in snippet:
                    site_name = name
                    break

            content_parts = []
            if snippet:
                content_parts.append(snippet)
            if site_name:
                content_parts.append(f"[来源] {site_name}")

            results.append(SearchResult(
                title=title,
                url=url,
                content='\n'.join(content_parts),
                source='baidu-serp',
                score=0.0,
                engine='baidu-serp',
                raw={
                    'site_name': site_name,
                    'result_index': i + 1,
                    'is_cn_tech': bool(site_name),
                },
            ))

        return results


# ============================================================
# 2. 搜狗微信搜索引擎
# ============================================================

class SogouWeixinEngine(SearchEngine):
    """
    搜狗微信搜索引擎（微信公众号文章搜索）

    能力：search, cn_source, weixin
    数据量：微信公众号文章索引
    API Key：无需
    国内可用：✅
    功能：搜索微信公众号文章（搜狗是微信公众号唯一官方搜索代理）

    注意：搜狗微信搜索可能需要验证码，遇到验证码时降级到百度搜索 site:weixin.qq.com
    """

    SEARCH_URL = "https://weixin.sogou.com/weixin"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="sogou-weixin",
            layer=2,
            description="搜狗微信搜索（微信公众号文章）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=85,
            capabilities=["search", "cn_source", "weixin"],
        )

    def is_available(self) -> bool:
        """搜狗在国内可用"""
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        搜狗微信搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                proxy: 代理
        """
        proxy = kwargs.get('proxy')
        params = urllib.parse.urlencode({
            'type': '2',  # 搜索文章（type=2）
            'query': query,
            'ie': 'utf-8',
        })
        url = f"{self.SEARCH_URL}?{params}"

        raw = _http_get(url, timeout=15, proxy=proxy, impersonate="chrome124")
        if not raw or _stub_page(raw):
            return None

        html = _decode_html(raw)

        # 检查是否被验证码拦截
        if '验证码' in html or 'antispider' in html.lower():
            # 降级到百度搜索 site:weixin.qq.com
            return self._fallback_baidu(query, max_results, proxy)

        results = self._parse_weixin_results(html, max_results)
        return results   # 取数成功但一条没解析出来＝0 结果，不是通道故障；None 会让断路器把引擎记成不可用

    def _parse_weixin_results(self, html: str, max_results: int) -> List[SearchResult]:
        """解析搜狗微信搜索结果"""
        results: List[SearchResult] = []

        # 搜狗微信文章结果模式
        # <div class="txt-box"> <h3><a href="...">标题</a></h3> <p class="txt-info">摘要</p>
        item_pattern = re.compile(
            r'<div[^>]*class="[^"]*txt-box[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL,
        )
        title_pattern = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
        snippet_pattern = re.compile(r'<p[^>]*class="[^"]*txt-info[^"]*"[^>]*>(.*?)</p>', re.DOTALL)
        account_pattern = re.compile(r'<a[^>]*class="account"[^>]*>(.*?)</a>', re.DOTALL)

        for block in item_pattern.findall(html):
            if len(results) >= max_results:
                break

            title_match = title_pattern.search(block)
            if not title_match:
                continue

            url = title_match.group(1)
            title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
            if not title or not _is_http_url(url):   # 伪链接不是结果
                continue

            snippet = ''
            snippet_match = snippet_pattern.search(block)
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

            account = ''
            account_match = account_pattern.search(block)
            if account_match:
                account = re.sub(r'<[^>]+>', '', account_match.group(1)).strip()

            content_parts = []
            if snippet:
                content_parts.append(snippet)
            if account:
                content_parts.append(f"[公众号] {account}")

            results.append(SearchResult(
                title=title,
                url=url,
                content='\n'.join(content_parts),
                source='sogou-weixin',
                score=0.0,
                engine='sogou-weixin',
                raw={
                    'account': account,
                    'content_type': 'weixin_article',
                },
            ))

        return results

    def _fallback_baidu(self, query: str, max_results: int, proxy: Optional[str]) -> Optional[List[SearchResult]]:
        """降级到百度搜索 site:weixin.qq.com"""
        baidu = BaiduSerpEngine()
        return baidu.search(query, max_results, site='weixin.qq.com', proxy=proxy)


# ============================================================
# 3. 搜狗知乎搜索引擎
# ============================================================

class SogouZhihuEngine(SearchEngine):
    """
    搜狗知乎搜索引擎（知乎问答搜索）

    能力：search, cn_source, zhihu
    数据量：知乎问答内容索引
    API Key：无需
    国内可用：✅
    功能：搜索知乎问答（搜狗是知乎搜索代理）

    注意：搜狗知乎搜索可能需要验证码，遇到验证码时降级到百度搜索 site:zhihu.com
    """

    SEARCH_URL = "https://zhihu.sogou.com/zhihu"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="sogou-zhihu",
            layer=2,
            description="搜狗知乎搜索（知乎问答）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=82,
            capabilities=["search", "cn_source", "zhihu"],
        )

    def is_available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        搜狗知乎搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                proxy: 代理
        """
        proxy = kwargs.get('proxy')
        params = urllib.parse.urlencode({
            'query': query,
            'ie': 'utf-8',
        })
        url = f"{self.SEARCH_URL}?{params}"

        raw = _http_get(url, timeout=15, proxy=proxy, impersonate="chrome124")
        if not raw or _stub_page(raw):
            return None

        html = _decode_html(raw)

        if '验证码' in html or 'antispider' in html.lower():
            return self._fallback_baidu(query, max_results, proxy)

        results = self._parse_zhihu_results(html, max_results)
        return results   # 取数成功但一条没解析出来＝0 结果，不是通道故障；None 会让断路器把引擎记成不可用

    def _parse_zhihu_results(self, html: str, max_results: int) -> List[SearchResult]:
        """解析搜狗知乎搜索结果"""
        results: List[SearchResult] = []

        # 知乎搜索结果模式
        item_pattern = re.compile(
            r'<div[^>]*class="[^"]*results[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL,
        )
        title_pattern = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
        snippet_pattern = re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL)

        for block in item_pattern.findall(html):
            if len(results) >= max_results:
                break

            title_match = title_pattern.search(block)
            if not title_match:
                continue

            url = title_match.group(1)
            title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
            if not title or not _is_http_url(url):   # 伪链接不是结果
                continue

            snippet = ''
            snippet_match = snippet_pattern.search(block)
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

            results.append(SearchResult(
                title=title,
                url=url,
                content=snippet,
                source='sogou-zhihu',
                score=0.0,
                engine='sogou-zhihu',
                raw={
                    'content_type': 'zhihu_qa',
                },
            ))

        return results

    def _fallback_baidu(self, query: str, max_results: int, proxy: Optional[str]) -> Optional[List[SearchResult]]:
        """降级到百度搜索 site:zhihu.com"""
        baidu = BaiduSerpEngine()
        return baidu.search(query, max_results, site='zhihu.com', proxy=proxy)


# ============================================================
# 4. 百度学术搜索引擎
# ============================================================

class BaiduXueshuEngine(SearchEngine):
    """
    百度学术搜索引擎（国内学术搜索）

    能力：search, academic, cn_academic
    数据量：百度学术索引的中英文学术论文
    API Key：无需
    国内可用：✅
    功能：搜索学术论文（补充 OpenAlex/S2 等国际学术源的中文论文覆盖）

    注意：百度学术无公开 API，通过 HTML 解析获取结果。
    知网/万方/维普无公开 API，百度学术是可用的国内学术搜索替代方案。
    """

    SEARCH_URL = "https://xueshu.baidu.com/s"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="baidu-xueshu",
            layer=2,
            description="百度学术（国内学术论文搜索）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=78,
            capabilities=["search", "academic", "cn_academic"],
        )

    def is_available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        百度学术搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                proxy: 代理
        """
        proxy = kwargs.get('proxy')
        params = urllib.parse.urlencode({
            'wd': query,
            'ie': 'utf-8',
        })
        url = f"{self.SEARCH_URL}?{params}"

        raw = _http_get(url, timeout=15, proxy=proxy, impersonate="chrome124")
        if not raw or _stub_page(raw):
            return None

        html = _decode_html(raw)
        results = self._parse_xueshu_results(html, max_results)
        return results   # 取数成功但一条没解析出来＝0 结果，不是通道故障；None 会让断路器把引擎记成不可用

    def _parse_xueshu_results(self, html: str, max_results: int) -> List[SearchResult]:
        """解析百度学术搜索结果"""
        results: List[SearchResult] = []

        # 百度学术结果模式：<div class="result">...<h3><a href="...">标题</a></h3>...<div class="c_abstract">摘要</div>
        item_pattern = re.compile(
            r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="result|$)',
            re.DOTALL,
        )
        title_pattern = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
        snippet_pattern = re.compile(r'<div[^>]*class="[^"]*c_abstract[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
        author_pattern = re.compile(r'<span[^>]*class="[^"]*author[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
        year_pattern = re.compile(r'<span[^>]*class="[^"]*year[^"]*"[^>]*>(.*?)</span>', re.DOTALL)

        for block in item_pattern.findall(html):
            if len(results) >= max_results:
                break

            title_match = title_pattern.search(block)
            if not title_match:
                continue

            url = title_match.group(1)
            title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
            if not title or not _is_http_url(url):   # 伪链接不是结果
                continue

            snippet = ''
            snippet_match = snippet_pattern.search(block)
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

            author = ''
            author_match = author_pattern.search(block)
            if author_match:
                author = re.sub(r'<[^>]+>', '', author_match.group(1)).strip()

            year = ''
            year_match = year_pattern.search(block)
            if year_match:
                year = re.sub(r'<[^>]+>', '', year_match.group(1)).strip()

            content_parts = []
            if snippet:
                content_parts.append(snippet)
            if author:
                content_parts.append(f"[作者] {author}")
            if year:
                content_parts.append(f"[年份] {year}")

            results.append(SearchResult(
                title=title,
                url=url,
                content='\n'.join(content_parts),
                source='baidu-xueshu',
                score=0.0,
                published_date=year,
                author=author,
                engine='baidu-xueshu',
                raw={
                    'content_type': 'academic_paper',
                    'year': year,
                },
            ))

        return results
