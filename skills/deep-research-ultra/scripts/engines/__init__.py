"""
Deep Research Ultra v5.2 — 引擎模块包

四层架构：
- Layer 1: MCP 服务器层 + 学术直连引擎（mcp_engines.py + academic_engines.py）
- Layer 2: 全局 Skill 层 + GitHub 深度搜索 + 国内内容源（skill_engines.py + github_deep_search.py + cn_sources.py）
- Layer 3: Claude 内置工具层（builtin.py）
- Layer 4: 降级引擎层（fallback.py，含 curl_cffi TLS 指纹伪装）

v5.2 新增引擎：
- GitHubDeepSearchEngine: 分桶搜索 + 低星挖掘 + 依赖图 + awesome 列表（不漏项目）
- GitHubCodeSearchEngine: GitHub 代码搜索（Code Search API）
- BaiduSerpEngine: 百度搜索 SERP（国内搜索主力）
- SogouWeixinEngine: 搜狗微信搜索（公众号文章）
- SogouZhihuEngine: 搜狗知乎搜索（知乎问答）
- BaiduXueshuEngine: 百度学术（国内学术论文）
"""

from .base import SearchEngine, SearchResult, EngineMetadata
from .mcp_engines import (
    TavilyMcpEngine,
    FirecrawlMcpEngine,
    OpenWebsearchMcpEngine,
    ArxivMcpEngine,
    PaperSearchMcpEngine,
)
from .academic_engines import (
    OpenAlexEngine,
    SemanticScholarEngine,
    PubmedEngine,
)
from .academic_fulltext import (
    ArxivFulltextEngine,
    UnpaywallEngine,
    CitationGraphEngine,
)
from .skill_engines import (
    AgentReachEngine,
    OssFinderEngine,
    Last30DaysEngine,
    SciverseEngine,
    DefuddleEngine,
    Context7Engine,
)
from .github_deep_search import GitHubDeepSearchEngine, GitHubCodeSearchEngine
from .cn_sources import (
    BaiduSerpEngine,
    SogouWeixinEngine,
    SogouZhihuEngine,
    BaiduXueshuEngine,
)
from .builtin import WebSearchEngine, WebFetchEngine
from .crawl4ai_engine import Crawl4aiEngine, LayeredCrawler
from .platform_engines import GiteeEngine, ModelScopeEngine  # v6.1：国内开源平台
from .fallback import DuckDuckGoEngine, BaiduHtmlEngine, BingHtmlEngine, SearXNGEngine

__all__ = [
    # 基类
    "SearchEngine", "SearchResult", "EngineMetadata",
    # Layer 1: MCP
    "TavilyMcpEngine", "FirecrawlMcpEngine", "OpenWebsearchMcpEngine",
    "ArxivMcpEngine", "PaperSearchMcpEngine",
    # Layer 1: 学术直连（v5.0 新增）
    "OpenAlexEngine", "SemanticScholarEngine", "PubmedEngine",
    # Layer 1: 学术全文+引用图谱（v5.1 新增）
    "ArxivFulltextEngine", "UnpaywallEngine", "CitationGraphEngine",
    # Layer 2: Skill
    "AgentReachEngine", "OssFinderEngine", "Last30DaysEngine",
    "SciverseEngine", "DefuddleEngine", "Context7Engine",
    # Layer 2: GitHub 深度搜索（v5.2 新增）
    "GitHubDeepSearchEngine", "GitHubCodeSearchEngine",
    # Layer 2: 国内内容源（v5.2 新增）
    "BaiduSerpEngine", "SogouWeixinEngine", "SogouZhihuEngine", "BaiduXueshuEngine",
    # Layer 3: 内置
    "WebSearchEngine", "WebFetchEngine",
    # Layer 3: 浏览器自动化（v5.1 新增）
    "Crawl4aiEngine", "LayeredCrawler",
    # Layer 2: 国内开源平台（v6.1 新增）
    "GiteeEngine", "ModelScopeEngine",
    # Layer 4: 降级
    "DuckDuckGoEngine", "BaiduHtmlEngine", "BingHtmlEngine", "SearXNGEngine",
]
