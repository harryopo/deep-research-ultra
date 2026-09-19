"""
Deep Research Ultra v4.0 — Layer 1: MCP 服务器引擎封装

五个 MCP 引擎：
- TavilyMcpEngine: AI 搜索 + 内容提取 + 爬取（1000 次/月免费）
- FirecrawlMcpEngine: 搜索 + 抓取 + 浏览器自动化（500 credits/月免费）
- OpenWebsearchMcpEngine: 完全免费、无 Key、Bing/百度/CSDN/掘金多引擎
- ArxivMcpEngine: arXiv 论文搜索与下载（完全免费）
- PaperSearchMcpEngine: 14 学术平台聚合（arXiv/PubMed/bioRxiv/Semantic Scholar 等）

每个引擎通过 McpClient 与 MCP 服务器通信，支持：
- 配置检测（is_available）
- 搜索（search）
- 内容提取（extract，部分引擎）
- 爬取（crawl，部分引擎）
"""

import json
from typing import Dict, List, Optional, Any

from .base import SearchEngine, SearchResult, EngineMetadata
from .mcp_client import McpClient


# ============================================================
# 通用辅助函数
# ============================================================

def _parse_mcp_result(result: Optional[Dict]) -> List[Dict]:
    """
    解析 MCP 工具调用的返回结果

    MCP 返回格式：
    {
        "content": [
            {"type": "text", "text": "..."},
            {"type": "text", "text": "..."}
        ]
    }

    或一些 MCP 直接返回结构化数据。

    Returns:
        解析后的字典列表
    """
    if not result:
        return []
    # 错误响应
    if "error" in result:
        return []
    # content 字段
    content = result.get("content", [])
    if isinstance(content, list):
        parsed_items = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text", "")
            if not text:
                continue
            # 尝试解析为 JSON
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    parsed_items.extend(parsed)
                elif isinstance(parsed, dict):
                    # 可能是单个结果或包含 results 字段
                    if "results" in parsed:
                        parsed_items.extend(parsed["results"])
                    else:
                        parsed_items.append(parsed)
                else:
                    parsed_items.append({"text": text})
            except json.JSONDecodeError:
                # 纯文本
                parsed_items.append({"text": text})
        return parsed_items
    # 直接返回字典
    if isinstance(content, dict):
        return [content]
    return []


def _build_search_result(item: Dict, source: str, engine: str) -> SearchResult:
    """从字典构建 SearchResult"""
    return SearchResult(
        title=item.get('title', '') or item.get('name', ''),
        url=item.get('url', '') or item.get('link', ''),
        content=item.get('content', '') or item.get('snippet', '') or item.get('summary', '') or item.get('text', ''),
        source=source,
        score=float(item.get('score', 0.0) or 0.0),
        published_date=item.get('published_date', '') or item.get('published', '') or item.get('date', ''),
        author=item.get('author', ''),
        engine=engine,
        raw=item,
    )


# ============================================================
# 1. Tavily MCP 引擎
# ============================================================

class TavilyMcpEngine(SearchEngine):
    """
    Tavily MCP 引擎

    能力：search / extract / map / crawl
    需要：TAVILY_API_KEY（1000 次/月免费）
    国内可用：✅
    """

    # 工具名常量
    TOOL_SEARCH = "tavily-search"
    TOOL_EXTRACT = "tavily-extract"
    TOOL_MAP = "tavily-map"
    TOOL_CRAWL = "tavily-crawl"

    def __init__(self):
        self._client = McpClient("tavily")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="tavily",
            layer=1,
            description="Tavily AI 搜索引擎（1000 次/月免费，支持搜索/提取/爬取）",
            requires_config=True,
            config_keys=["TAVILY_API_KEY"],
            is_async_supported=True,
            is_china_friendly=True,
            priority=10,
            capabilities=["search", "extract", "crawl"],
        )

    def is_available(self) -> bool:
        return self._client.is_available()

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        Tavily 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                search_depth: 'basic' 或 'advanced'（高级模式更深入）
                topic: 'general' 或 'news'
                days: 新闻模式下返回最近 N 天
                include_domains: 仅包含这些域名
                exclude_domains: 排除这些域名
        """
        arguments = {
            "query": query,
            "max_results": max_results,
            "search_depth": kwargs.get("search_depth", "basic"),
            "topic": kwargs.get("topic", "general"),
            "include_answer": kwargs.get("include_answer", True),
            "include_raw_content": kwargs.get("include_raw_content", False),
        }
        if "days" in kwargs:
            arguments["days"] = kwargs["days"]
        if "include_domains" in kwargs:
            arguments["include_domains"] = kwargs["include_domains"]
        if "exclude_domains" in kwargs:
            arguments["exclude_domains"] = kwargs["exclude_domains"]

        result = self._client.call_tool(self.TOOL_SEARCH, arguments)
        items = _parse_mcp_result(result)
        return [_build_search_result(item, "tavily", "tavily") for item in items if item.get('url') or item.get('title')]

    def extract(self, url: str, **kwargs) -> Optional[str]:
        """Tavily 内容提取"""
        result = self._client.call_tool(self.TOOL_EXTRACT, {
            "urls": url if isinstance(url, list) else [url],
        })
        items = _parse_mcp_result(result)
        if not items:
            return None
        # 拼接所有提取的内容
        contents = []
        for item in items:
            content = item.get('raw_content', '') or item.get('content', '') or item.get('text', '')
            if content:
                contents.append(content)
        return '\n\n'.join(contents) if contents else None

    def crawl(self, url: str, max_pages: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """Tavily 网站爬取"""
        result = self._client.call_tool(self.TOOL_CRAWL, {
            "url": url,
            "max_depth": kwargs.get("max_depth", 2),
            "limit": max_pages,
        })
        items = _parse_mcp_result(result)
        return [_build_search_result(item, "tavily", "tavily-crawl") for item in items if item.get('url')]


# ============================================================
# 2. Firecrawl MCP 引擎
# ============================================================

class FirecrawlMcpEngine(SearchEngine):
    """
    Firecrawl MCP 引擎

    能力：search / scrape / crawl / map / browser
    需要：FIRECRAWL_API_KEY（500 credits/月免费）
    国内可用：✅（远程服务）
    """

    TOOL_SEARCH = "firecrawl_search"
    TOOL_SCRAPE = "firecrawl_scrape"
    TOOL_CRAWL = "firecrawl_crawl"
    TOOL_MAP = "firecrawl_map"

    def __init__(self):
        self._client = McpClient("firecrawl")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="firecrawl",
            layer=1,
            description="Firecrawl 搜索 + 抓取 + 浏览器自动化（500 credits/月免费）",
            requires_config=True,
            config_keys=["FIRECRAWL_API_KEY"],
            is_async_supported=True,
            is_china_friendly=True,
            priority=20,
            capabilities=["search", "extract", "crawl"],
        )

    def is_available(self) -> bool:
        return self._client.is_available()

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        Firecrawl 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                search_options: 搜索选项字典
        """
        arguments = {
            "query": query,
            "limit": max_results,
        }
        if "search_options" in kwargs:
            arguments["searchOptions"] = kwargs["search_options"]

        result = self._client.call_tool(self.TOOL_SEARCH, arguments)
        items = _parse_mcp_result(result)
        return [_build_search_result(item, "firecrawl", "firecrawl") for item in items if item.get('url') or item.get('title')]

    def extract(self, url: str, **kwargs) -> Optional[str]:
        """Firecrawl 单页抓取"""
        result = self._client.call_tool(self.TOOL_SCRAPE, {
            "url": url,
            "formats": kwargs.get("formats", ["markdown"]),
        })
        items = _parse_mcp_result(result)
        if not items:
            return None
        for item in items:
            content = item.get('markdown', '') or item.get('content', '') or item.get('html', '')
            if content:
                return content
        return None

    def crawl(self, url: str, max_pages: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """Firecrawl 网站爬取"""
        result = self._client.call_tool(self.TOOL_CRAWL, {
            "url": url,
            "limit": max_pages,
            "crawlerOptions": kwargs.get("crawler_options", {}),
        })
        items = _parse_mcp_result(result)
        return [_build_search_result(item, "firecrawl", "firecrawl-crawl") for item in items if item.get('url')]


# ============================================================
# 3. open-websearch MCP 引擎
# ============================================================

class OpenWebsearchMcpEngine(SearchEngine):
    """
    open-websearch MCP 引擎

    能力：search（Bing/百度/CSDN/DuckDuckGo/Exa/Brave/掘金多引擎）
    需要：无（完全免费）
    国内可用：✅
    """

    TOOL_SEARCH = "search"

    def __init__(self):
        self._client = McpClient("open-websearch")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="open-websearch",
            layer=1,
            description="open-websearch 多引擎搜索（完全免费，Bing/百度/CSDN/掘金等）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=30,
            capabilities=["search"],
        )

    def is_available(self) -> bool:
        return self._client.is_available()

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        open-websearch 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                engine: 指定引擎（bing/baidu/csdn/duckduckgo/exa/brave/juejin）
                        不指定则使用默认引擎
        """
        arguments = {
            "query": query,
            "num": max_results,
        }
        if "engine" in kwargs:
            arguments["engine"] = kwargs["engine"]

        result = self._client.call_tool(self.TOOL_SEARCH, arguments)
        items = _parse_mcp_result(result)
        engine_name = kwargs.get("engine", "open-websearch")
        return [_build_search_result(item, "open-websearch", f"open-websearch-{engine_name}")
                for item in items if item.get('url') or item.get('title')]


# ============================================================
# 4. arXiv MCP 引擎
# ============================================================

class ArxivMcpEngine(SearchEngine):
    """
    arXiv MCP 引擎

    能力：search / download / list / read（学术论文）
    需要：无（完全免费，需 uvx）
    国内可用：✅
    """

    TOOL_SEARCH = "search_papers"
    TOOL_DOWNLOAD = "download_paper"
    TOOL_LIST = "list_papers"
    TOOL_READ = "read_paper"

    def __init__(self):
        self._client = McpClient("arxiv")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="arxiv",
            layer=1,
            description="arXiv 学术论文搜索（完全免费，含下载与全文阅读）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=40,
            capabilities=["search", "academic"],
        )

    def is_available(self) -> bool:
        return self._client.is_available()

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        arXiv 论文搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                sort_by: 排序字段（relevance/date）
                sort_order: 排序方向（ascending/descending）
        """
        arguments = {
            "query": query,
            "max_results": max_results,
        }
        if "sort_by" in kwargs:
            arguments["sort_by"] = kwargs["sort_by"]
        if "sort_order" in kwargs:
            arguments["sort_order"] = kwargs["sort_order"]

        result = self._client.call_tool(self.TOOL_SEARCH, arguments)
        items = _parse_mcp_result(result)
        results = []
        for item in items:
            if not (item.get('url') or item.get('title')):
                continue
            # arXiv 特定字段映射
            paper_id = item.get('paper_id', '') or item.get('id', '')
            if paper_id and not item.get('url'):
                item['url'] = f"https://arxiv.org/abs/{paper_id}"
            results.append(_build_search_result(item, "arxiv", "arxiv"))
        return results


# ============================================================
# 5. paper-search MCP 引擎
# ============================================================

class PaperSearchMcpEngine(SearchEngine):
    """
    paper-search MCP 引擎

    能力：search（聚合 arXiv/PubMed/bioRxiv/medRxiv/Semantic Scholar/Crossref/OpenAlex 等 14 个学术源）
    需要：无（完全免费，需 Node.js）
    国内可用：✅
    """

    # 不同数据源的工具名（部分 MCP 实现按数据源分工具）
    TOOL_GENERIC = "search_papers"
    TOOL_ARXIV = "search_arxiv"
    TOOL_PUBMED = "search_pubmed"
    TOOL_BIORXIV = "search_biorxiv"
    TOOL_SEMANTIC_SCHOLAR = "search_semantic_scholar"
    TOOL_CROSSREF = "search_crossref"
    TOOL_OPENALEX = "search_openalex"

    # 支持的数据源
    SUPPORTED_SOURCES = [
        "arxiv", "pubmed", "biorxiv", "medrxiv",
        "semantic_scholar", "crossref", "openalex",
    ]

    def __init__(self):
        self._client = McpClient("paper-search")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="paper-search",
            layer=1,
            description="paper-search 学术平台聚合（14 个源：arXiv/PubMed/bioRxiv/Semantic Scholar 等）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=50,
            capabilities=["search", "academic"],
        )

    def is_available(self) -> bool:
        return self._client.is_available()

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        paper-search 学术搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                source: 指定数据源（arxiv/pubmed/biorxiv/semantic_scholar/crossref/openalex）
                year_from: 起始年份
                year_to: 截止年份
        """
        source = kwargs.get("source", "")
        # 优先调用特定源的工具，回退到通用搜索
        tool_name = self.TOOL_GENERIC
        if source and source in self.SUPPORTED_SOURCES:
            tool_name = f"search_{source}"

        arguments = {
            "query": query,
            "limit": max_results,
        }
        if source:
            arguments["source"] = source
        if "year_from" in kwargs:
            arguments["year_from"] = kwargs["year_from"]
        if "year_to" in kwargs:
            arguments["year_to"] = kwargs["year_to"]

        result = self._client.call_tool(tool_name, arguments)
        items = _parse_mcp_result(result)
        source_label = source or "multi-source"
        return [_build_search_result(item, "paper-search", f"paper-search-{source_label}")
                for item in items if item.get('url') or item.get('title')]
