"""
Deep Research Ultra v4.0 — Layer 4: 降级引擎层

四个降级引擎（Python 脚本直接执行，无需 Claude 工具）：
- DuckDuckGoEngine: ddgs Python 库（免费、无需 Key、国内可用）
- BaiduHtmlEngine: 百度搜索 HTML 解析（最后手段）
- BingHtmlEngine: Bing 搜索 HTML 解析（最后手段）
- SearXNGEngine: 自建 SearXNG 元搜索（需 Docker）

设计说明：
- Layer 4 是最后的兜底方案，仅当 Layer 1-3 全部不可用时使用
- 这些引擎由 Python 直接执行 HTTP 请求，不依赖 Claude 工具
- HTML 解析引擎（百度/Bing）容易因搜索引擎改版失效，仅作最后手段
- 推荐优先配置 MCP 服务器以避免降级到此层

修复 v3.2.0 的问题：
- v3 用 re.findall 解析 HTML，极易失效 → v4 优先用 MCP，HTML 解析仅作最后手段
- v3 同步阻塞 IO → v4 保留同步实现（降级场景下简单可靠）
- v3 错误处理过于简略（except: pass）→ v4 结构化错误处理
"""

import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Any

from .base import SearchEngine, SearchResult, EngineMetadata


# ============================================================
# 通用 HTTP 工具
# ============================================================

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 最近一次 HTTP 失败原因。引擎契约只返回 None，调用方无法区分
# "406/429 限流"「404 端点变更」「DNS 挂了」——探针与自检报告需要这个信息。
LAST_HTTP_ERROR: str = ''


def _note_http_error(detail: str) -> None:
    global LAST_HTTP_ERROR
    LAST_HTTP_ERROR = detail


def _clear_http_error() -> None:
    global LAST_HTTP_ERROR
    LAST_HTTP_ERROR = ''


def _http_get(
    url: str,
    headers: Optional[Dict] = None,
    timeout: int = 15,
    max_retries: int = 3,
    proxy: Optional[str] = None,
    impersonate: str = "chrome124",
) -> Optional[bytes]:
    """
    带重试的 HTTP GET 请求（优先使用 curl_cffi 进行 TLS 指纹伪装）

    Args:
        url: 请求 URL
        headers: 请求头
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        proxy: HTTP 代理地址
        impersonate: curl_cffi TLS 指纹伪装目标（默认 chrome124）

    Returns:
        响应内容（bytes），失败返回 None
    """
    if headers is None:
        headers = {}
    headers.setdefault('User-Agent', DEFAULT_USER_AGENT)
    headers.setdefault('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
    headers.setdefault('Accept-Language', 'zh-CN,zh;q=0.9,en;q=0.8')
    _clear_http_error()

    # 优先使用 curl_cffi（TLS 指纹伪装）
    server_responded = False          # 服务端已给出状态码 ≠ 传输失败，不得再走 urllib
    try:
        from curl_cffi import requests as cffi_requests
        last_error = None
        for attempt in range(max_retries):
            try:
                r = cffi_requests.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                    proxies={"http": proxy, "https": proxy} if proxy else None,
                    impersonate=impersonate,
                )
                if r.status_code == 200:
                    _clear_http_error()
                    return r.content
                elif r.status_code == 429:
                    # 限流，等待更长时间
                    server_responded = True
                    last_error = f"HTTP 429 rate limited"
                    _note_http_error(last_error)
                    if attempt < max_retries - 1:
                        time.sleep(2.0 * (2 ** attempt))
                else:
                    server_responded = True
                    last_error = f"HTTP {r.status_code}"
                    _note_http_error(last_error)
                    if attempt < max_retries - 1:
                        time.sleep(1.0 * (2 ** attempt))
            except Exception as e:
                last_error = e
                _note_http_error(f'{type(e).__name__}: {e}')
                if attempt < max_retries - 1:
                    time.sleep(1.0 * (2 ** attempt))
        # curl_cffi 全部重试失败：仅当是传输层异常才降级到 urllib。
        # 服务端已回过状态码（429/403/404…）时直接返回——换一条 TLS 指纹
        # 重写同一请求只会把已限流的端点再打一遍（实测双倍请求量）。
        if server_responded:
            return None
    except ImportError:
        pass  # curl_cffi 未安装，使用 urllib

    # 降级到 urllib 实现（保留原有代码）
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
        opener = urllib.request.build_opener(proxy_handler)
    else:
        opener = urllib.request.build_opener()

    last_error = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=timeout) as response:
                raw_data = response.read()
                _clear_http_error()
                content_encoding = response.headers.get('Content-Encoding', '')
                if content_encoding == 'gzip':
                    return gzip.decompress(raw_data)
                return raw_data
        except urllib.error.HTTPError as e:
            last_error = e
            _note_http_error(f'HTTP {e.code}')
            if attempt < max_retries - 1:
                delay = 1.0 * (2 ** attempt)
                time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_error = e
            _note_http_error(f'{type(e).__name__}: {e}')
            if attempt < max_retries - 1:
                delay = 1.0 * (2 ** attempt)
                time.sleep(delay)
    return None


def _http_post(
    url: str,
    json_body: Optional[Dict] = None,
    data: Optional[bytes] = None,
    headers: Optional[Dict] = None,
    timeout: int = 30,
    max_retries: int = 3,
    proxy: Optional[str] = None,
    impersonate: str = "chrome",
) -> Optional[bytes]:
    """
    带重试的 HTTP POST 请求（优先使用 curl_cffi 进行 TLS 指纹伪装）

    Args:
        url: 请求 URL
        json_body: JSON 请求体（与 data 二选一）
        data: 原始请求体（bytes）
        headers: 请求头
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        proxy: HTTP 代理地址
        impersonate: curl_cffi TLS 指纹伪装目标（默认 chrome，自动跟随最新版本）

    Returns:
        响应内容（bytes），失败返回 None
    """
    if headers is None:
        headers = {}
    headers.setdefault('User-Agent', DEFAULT_USER_AGENT)
    headers.setdefault('Accept', 'application/json, text/html, */*')
    headers.setdefault('Accept-Language', 'zh-CN,zh;q=0.9,en;q=0.8')
    if json_body is not None:
        headers.setdefault('Content-Type', 'application/json')

    # 优先使用 curl_cffi（TLS 指纹伪装）
    try:
        from curl_cffi import requests as cffi_requests
        for attempt in range(max_retries):
            try:
                r = cffi_requests.post(
                    url,
                    json=json_body,
                    data=data,
                    headers=headers,
                    timeout=timeout,
                    proxies={"http": proxy, "https": proxy} if proxy else None,
                    impersonate=impersonate,
                )
                if r.status_code in (200, 201):
                    return r.content
                elif r.status_code == 429:
                    time.sleep(2.0 * (2 ** attempt))
                else:
                    if attempt < max_retries - 1:
                        time.sleep(1.0 * (2 ** attempt))
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(1.0 * (2 ** attempt))
        return None
    except ImportError:
        pass  # curl_cffi 未安装，使用 urllib

    # 降级到 urllib 实现
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
        opener = urllib.request.build_opener(proxy_handler)
    else:
        opener = urllib.request.build_opener()

    for attempt in range(max_retries):
        try:
            body = None
            if json_body is not None:
                body = json.dumps(json_body).encode('utf-8')
            elif data is not None:
                body = data
            req = urllib.request.Request(url, data=body, headers=headers, method='POST')
            with opener.open(req, timeout=timeout) as response:
                raw_data = response.read()
                content_encoding = response.headers.get('Content-Encoding', '')
                if content_encoding == 'gzip':
                    return gzip.decompress(raw_data)
                return raw_data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError):
            if attempt < max_retries - 1:
                time.sleep(1.0 * (2 ** attempt))
    return None


def _decode_html(raw: bytes) -> str:
    """解码 HTML（自动检测编码）"""
    if not raw:
        return ''
    # 尝试常见编码
    for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='ignore')


def _json_loads(raw):
    """安全 JSON 解析（接受 bytes 或 str，失败返回 None）"""
    import json as _json
    if not raw:
        return None
    if isinstance(raw, bytes):
        for encoding in ['utf-8', 'gbk', 'latin-1']:
            try:
                raw = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    if not isinstance(raw, str):
        return None
    try:
        return _json.loads(raw)
    except (ValueError, TypeError):
        return None


# ============================================================
# 1. DuckDuckGo 引擎（ddgs 库）
# ============================================================

class DuckDuckGoEngine(SearchEngine):
    """
    DuckDuckGo 搜索引擎（ddgs Python 库）

    能力：search
    需要：ddgs 库（pip install ddgs）
    国内可用：✅（DuckDuckGo 在国内部分网络环境下可用）
    """

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="duckduckgo",
            layer=4,
            description="DuckDuckGo 搜索（ddgs Python 库，免费无需 Key）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=300,
            capabilities=["search"],
        )

    def is_available(self) -> bool:
        """检测 ddgs 库是否已安装"""
        try:
            import ddgs  # noqa: F401
            return True
        except ImportError:
            # 也检查旧版 duckduckgo_search
            try:
                from duckduckgo_search import DDGS  # noqa: F401
                return True
            except ImportError:
                return False

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        DuckDuckGo 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                region: 地区（wt-wt 全球, wt-zh 中国）
                timelimit: 时间限制（d/w/m/y）
        """
        try:
            # 优先使用新版 ddgs 库
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            region = kwargs.get('region', 'wt-wt')
            timelimit = kwargs.get('timelimit', '')

            with DDGS() as ddgs:
                search_kwargs = {
                    'query': query,
                    'max_results': max_results,
                    'region': region,
                }
                if timelimit:
                    search_kwargs['timelimit'] = timelimit
                results = list(ddgs.text(**search_kwargs))

            return [
                SearchResult(
                    title=r.get('title', ''),
                    url=r.get('href', '') or r.get('link', ''),
                    content=r.get('body', '') or r.get('snippet', ''),
                    source='duckduckgo',
                    score=0.0,
                    engine='duckduckgo',
                    raw=r,
                )
                for r in results
            ]
        except Exception:
            return None


# ============================================================
# 2. 百度 HTML 引擎
# ============================================================

class BaiduHtmlEngine(SearchEngine):
    """
    百度搜索 HTML 解析引擎（最后手段）

    能力：search
    国内可用：✅
    警告：HTML 解析容易因百度改版失效，仅作最后手段
    """

    # 百度搜索 URL
    SEARCH_URL = "https://www.baidu.com/s"

    # 结果项正则（匹配搜索结果块）
    # 百度搜索结果通常在 <div class="result ..."> 中
    RESULT_PATTERN = re.compile(
        r'<div[^>]*class="result[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="result|<div[^>]*id="content_bottom")',
        re.DOTALL,
    )
    # 标题与链接
    TITLE_PATTERN = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    # 摘要
    SNIPPET_PATTERN = re.compile(r'<span[^>]*class="content-right_[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
    # 备用摘要
    SNIPPET_FALLBACK_PATTERN = re.compile(r'<div[^>]*class="c-abstract[^"]*"[^>]*>(.*?)</div>', re.DOTALL)

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="baidu-html",
            layer=4,
            description="百度搜索 HTML 解析（最后手段，易失效）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=310,
            capabilities=["search"],
        )

    def is_available(self) -> bool:
        """百度在国内始终可用（不实际测试，避免被风控）"""
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        百度搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                page: 页码（默认 1）
                proxy: 代理
        """
        page = kwargs.get('page', 1)
        proxy = kwargs.get('proxy')
        params = urllib.parse.urlencode({
            'wd': query,
            'rn': str(max_results),
            'pn': str((page - 1) * max_results),
            'ie': 'utf-8',
        })
        url = f"{self.SEARCH_URL}?{params}"

        raw = _http_get(url, timeout=15, proxy=proxy)
        if not raw:
            return None
        html = _decode_html(raw)

        results = []
        # 提取结果块
        for block in self.RESULT_PATTERN.findall(html):
            if len(results) >= max_results:
                break
            # 提取标题和链接
            title_match = self.TITLE_PATTERN.search(block)
            if not title_match:
                continue
            link = title_match.group(1)
            title_html = title_match.group(2)
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if not title or not link:
                continue

            # 提取摘要
            snippet = ''
            snippet_match = self.SNIPPET_PATTERN.search(block)
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
            if not snippet:
                snippet_match = self.SNIPPET_FALLBACK_PATTERN.search(block)
                if snippet_match:
                    snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

            # 百度链接可能是重定向链接（baidu.com/link?url=...）
            results.append(SearchResult(
                title=title,
                url=link,
                content=snippet,
                source='baidu-html',
                score=0.0,
                engine='baidu-html',
            ))

        return results if results else None


# ============================================================
# 3. Bing HTML 引擎
# ============================================================

class BingHtmlEngine(SearchEngine):
    """
    Bing 搜索 HTML 解析引擎（最后手段）

    能力：search
    国内可用：✅（cn.bing.com）
    警告：HTML 解析容易因 Bing 改版失效，仅作最后手段
    """

    SEARCH_URL = "https://cn.bing.com/search"

    # Bing 结果项在 <li class="b_algo"> 中
    RESULT_PATTERN = re.compile(r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>', re.DOTALL)
    # 标题与链接
    TITLE_PATTERN = re.compile(r'<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    # 摘要
    SNIPPET_PATTERN = re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL)

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="bing-html",
            layer=4,
            description="Bing 搜索 HTML 解析（最后手段，易失效）",
            requires_config=False,
            config_keys=[],
            is_async_supported=False,
            is_china_friendly=True,
            priority=320,
            capabilities=["search"],
        )

    def is_available(self) -> bool:
        """Bing 在国内可用（cn.bing.com）"""
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        Bing 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                page: 页码（默认 1）
                proxy: 代理
        """
        page = kwargs.get('page', 1)
        proxy = kwargs.get('proxy')
        params = urllib.parse.urlencode({
            'q': query,
            'count': str(max_results),
            'first': str((page - 1) * max_results + 1),
            'setlang': 'zh-CN',
        })
        url = f"{self.SEARCH_URL}?{params}"

        raw = _http_get(url, timeout=15, proxy=proxy)
        if not raw:
            return None
        html = _decode_html(raw)

        results = []
        for block in self.RESULT_PATTERN.findall(html):
            if len(results) >= max_results:
                break
            title_match = self.TITLE_PATTERN.search(block)
            if not title_match:
                continue
            link = title_match.group(1)
            title_html = title_match.group(2)
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if not title or not link:
                continue

            snippet = ''
            snippet_match = self.SNIPPET_PATTERN.search(block)
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

            results.append(SearchResult(
                title=title,
                url=link,
                content=snippet,
                source='bing-html',
                score=0.0,
                engine='bing-html',
            ))

        return results if results else None


# ============================================================
# 4. SearXNG 引擎（自建）
# ============================================================

class SearXNGEngine(SearchEngine):
    """
    SearXNG 元搜索引擎（自建实例）

    能力：search
    需要：自建 SearXNG 实例（Docker 部署）
    国内可用：✅（自建后无限制）
    配置：环境变量 SEARXNG_URL（如 http://localhost:8080）
    """

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="searxng",
            layer=4,
            description="SearXNG 自建元搜索（聚合 70+ 引擎，需 Docker 部署）",
            requires_config=True,
            config_keys=["SEARXNG_URL"],
            is_async_supported=False,
            is_china_friendly=True,
            priority=330,
            capabilities=["search"],
        )

    def is_available(self) -> bool:
        """检测 SearXNG 实例是否可达"""
        import os
        searxng_url = os.environ.get('SEARXNG_URL', '')
        if not searxng_url:
            return False
        # 检测连通性
        try:
            raw = _http_get(searxng_url, timeout=5)
            return raw is not None
        except Exception:
            return False

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        SearXNG 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                categories: 搜索类别（general/images/news/videos/it/science/files/social media）
                engines: 指定引擎（如 google,bing,baidu）
                language: 语言（zh-CN/en-US）
                time_range: 时间范围（day/week/month/year）
                proxy: 代理
        """
        import os
        searxng_url = os.environ.get('SEARXNG_URL', '').rstrip('/')
        if not searxng_url:
            return None

        params_dict = {
            'q': query,
            'format': 'json',
            'pageno': str(kwargs.get('page', 1)),
        }
        if 'categories' in kwargs:
            params_dict['categories'] = kwargs['categories']
        if 'engines' in kwargs:
            params_dict['engines'] = kwargs['engines']
        if 'language' in kwargs:
            params_dict['language'] = kwargs['language']
        if 'time_range' in kwargs:
            params_dict['time_range'] = kwargs['time_range']

        params = urllib.parse.urlencode(params_dict)
        url = f"{searxng_url}/search?{params}"

        raw = _http_get(url, timeout=20, proxy=kwargs.get('proxy'))
        if not raw:
            return None
        try:
            data = json.loads(_decode_html(raw))
        except json.JSONDecodeError:
            return None

        results = []
        for item in data.get('results', [])[:max_results]:
            results.append(SearchResult(
                title=item.get('title', ''),
                url=item.get('url', ''),
                content=item.get('content', ''),
                source='searxng',
                score=float(item.get('score', 0.0)),
                published_date=item.get('publishedDate', ''),
                engine=item.get('engine', ''),
                raw=item,
            ))

        return results if results else None
