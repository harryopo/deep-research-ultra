"""
Deep Research Ultra v5.0 — Crawl4AI 引擎 + 分层爬取引擎

模块包含两个核心组件：

1. Crawl4aiEngine (SearchEngine)
   通过 Crawl4AI Docker REST API（端口 11235）进行网页爬取和内容提取。
   - 能力：extract / crawl（内容提取 + 网站深度爬取）
   - 配置：环境变量 CRAWL4AI_URL（默认 http://localhost:11235）、CRAWL4AI_API_TOKEN
   - 特性：JS 渲染、LLM 结构化提取、反检测（stealth/magic_mode）

2. LayeredCrawler
   四级渐进式爬取策略，从轻量到重量级自动升级：
   - Level 1: curl_cffi（TLS 指纹伪装，覆盖 90% 场景）
   - Level 2: Firecrawl MCP（远程，无需 Key，JS 渲染）
   - Level 3: Crawl4AI Docker（本地，magic_mode 反检测）
   - Level 4: Camoufox（C++ 级指纹，最强反检测，按需启用）

设计说明：
- 遵循现有引擎同步架构，所有异步操作（Camoufox）内部通过 asyncio.run() 包装
- HTTP 请求复用 fallback.py 的 _http_get / _http_post（含 curl_cffi TLS 伪装）
- Camoufox 为可选依赖，import 失败时优雅降级（跳过 Level 4）
- impersonate 参数统一使用 "chrome"（自动跟随最新版本指纹）
"""

import asyncio
import json
import os
from typing import Optional, List, Dict, Any

from .base import SearchEngine, SearchResult, EngineMetadata
from .fallback import _http_get, _http_post, _decode_html


# ============================================================
# Crawl4AI 引擎（Layer 3: 内置层）
# ============================================================

class Crawl4aiEngine(SearchEngine):
    """
    Crawl4AI 引擎 — 通过 Docker REST API 进行网页爬取和内容提取

    能力：extract / crawl
    需要：Docker 部署 Crawl4AI 容器（默认端口 11235）
    国内可用：✅（本地部署，无网络限制）
    优先级：P200（作为 curl_cffi 的 JS 渲染 fallback）

    环境变量：
        CRAWL4AI_URL       — Docker REST API 地址（默认 http://localhost:11235）
        CRAWL4AI_API_TOKEN — API 认证令牌（可选，Docker 部署时可设置）
        CRAWL4AI_LLM_PROVIDER — LLM 提供商（如 openai/gpt-4o，用于 extract）
        CRAWL4AI_LLM_API_KEY  — LLM API Key（用于 extract）
    """

    def __init__(self):
        self._api_base = os.environ.get("CRAWL4AI_URL", "http://localhost:11235")
        self._api_token = os.environ.get("CRAWL4AI_API_TOKEN", "")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="crawl4ai",
            layer=3,
            description="Crawl4AI 本地爬虫（Docker 部署，JS 渲染 + LLM 提取 + 反检测）",
            requires_config=True,
            config_keys=["CRAWL4AI_URL", "CRAWL4AI_API_TOKEN"],
            is_async_supported=True,
            is_china_friendly=True,
            priority=200,
            capabilities=["extract", "crawl"],
        )

    def is_available(self) -> bool:
        """
        检测 Crawl4AI 服务是否可用

        检查项：
        1. CRAWL4AI_URL 环境变量是否已设置
        2. /health 端点是否返回 200
        """
        if not os.environ.get("CRAWL4AI_URL"):
            return False

        headers: Dict[str, str] = {}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"

        raw = _http_get(
            f"{self._api_base}/health",
            headers=headers,
            timeout=5,
            max_retries=1,
            impersonate="chrome",
        )
        return raw is not None

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        通过 /crawl 端点爬取 URL 并返回 Markdown 内容

        Crawl4AI 不支持关键词搜索，此方法将 query 视为 URL 进行爬取，
        返回包含 Markdown 内容的 SearchResult 列表。

        Args:
            query: 目标 URL（非搜索关键词）
            max_results: 保留参数（Crawl4AI 单次返回一个页面）
            **kwargs: 传递给 _call_crawl 的参数（stealth, timeout 等）
        """
        url = query.strip()
        if not url.startswith(("http://", "https://")):
            return None

        markdown = self._call_crawl(url, **kwargs)
        if not markdown:
            return None

        return [SearchResult(
            title=url,
            url=url,
            content=markdown,
            source="crawl4ai",
            engine="crawl4ai",
        )]

    def extract(self, url: str, **kwargs) -> Optional[str]:
        """
        提取单个 URL 的内容（Markdown 格式），支持 LLMExtractionStrategy

        Args:
            url: 目标 URL
            **kwargs:
                stealth: 是否启用反检测（默认 True）
                use_llm: 是否使用 LLMExtractionStrategy（默认 False）
                llm_instruction: LLM 提取指令（默认提取主内容）
                timeout: 页面超时（毫秒，默认 60000）
                http_timeout: HTTP 请求超时（秒，默认 60）
                word_count_threshold: 最小词数阈值（默认 15）
        """
        return self._call_crawl(url, **kwargs)

    def crawl(self, url: str, max_pages: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        深度爬取网站（BFS 策略）

        Args:
            url: 起始 URL
            max_pages: 最大页面数
            **kwargs:
                stealth: 是否启用反检测（默认 True）
        """
        stealth = kwargs.get("stealth", True)

        payload = {
            "urls": [url],
            "browser_config": {
                "type": "BrowserConfig",
                "params": {
                    "headless": True,
                    "user_agent_mode": "random" if stealth else "",
                    "enable_stealth": stealth,
                }
            },
            "crawler_config": {
                "type": "CrawlerRunConfig",
                "params": {
                    "deep_crawl_strategy": "bfs",
                    "max_pages": max_pages,
                    "scan_full_page": True,
                    "simulate_user": stealth,
                    "override_navigator": stealth,
                    "magic": stealth,
                }
            }
        }

        headers: Dict[str, str] = {}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"

        raw = _http_post(
            f"{self._api_base}/crawl",
            json_body=payload,
            headers=headers,
            timeout=120,
            impersonate="chrome",
        )
        if not raw:
            return None

        try:
            data = json.loads(_decode_html(raw))
            results = []
            for item in data.get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("markdown", ""),
                    source="crawl4ai",
                    engine="crawl4ai-crawl",
                ))
            return results if results else None
        except (json.JSONDecodeError, KeyError):
            return None

    # ------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------

    def _call_crawl(self, url: str, **kwargs) -> Optional[str]:
        """
        调用 Crawl4AI /crawl 端点，返回 Markdown 内容

        Args:
            url: 目标 URL
            **kwargs:
                stealth: 反检测模式（默认 True）
                use_llm: 是否启用 LLMExtractionStrategy（默认 False）
                llm_instruction: LLM 提取指令
                timeout: 页面超时（毫秒）
                http_timeout: HTTP 请求超时（秒）
                word_count_threshold: 最小词数阈值
        """
        stealth = kwargs.get("stealth", True)
        use_llm = kwargs.get("use_llm", False)

        crawler_params: Dict[str, Any] = {
            "simulate_user": stealth,
            "override_navigator": stealth,
            "magic": stealth,
            "scan_full_page": True,
            "word_count_threshold": kwargs.get("word_count_threshold", 15),
            "wait_until": "networkidle",
            "page_timeout": kwargs.get("timeout", 60000),
        }

        # LLMExtractionStrategy（可选）
        if use_llm:
            llm_provider = os.environ.get("CRAWL4AI_LLM_PROVIDER", "")
            llm_api_key = os.environ.get("CRAWL4AI_LLM_API_KEY", "")
            llm_instruction = kwargs.get(
                "llm_instruction", "Extract the main content of this page."
            )
            if llm_provider and llm_api_key:
                crawler_params["extraction_strategy"] = {
                    "type": "LLMExtractionStrategy",
                    "params": {
                        "provider": llm_provider,
                        "api_key": llm_api_key,
                        "instruction": llm_instruction,
                    }
                }

        payload = {
            "urls": [url],
            "browser_config": {
                "type": "BrowserConfig",
                "params": {
                    "headless": True,
                    "user_agent_mode": "random" if stealth else "",
                    "enable_stealth": stealth,
                }
            },
            "crawler_config": {
                "type": "CrawlerRunConfig",
                "params": crawler_params,
            }
        }

        headers: Dict[str, str] = {}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"

        raw = _http_post(
            f"{self._api_base}/crawl",
            json_body=payload,
            headers=headers,
            timeout=kwargs.get("http_timeout", 60),
            impersonate="chrome",
        )
        if not raw:
            return None

        try:
            data = json.loads(_decode_html(raw))
            results = data.get("results", [])
            if results:
                return results[0].get("markdown", "")
        except (json.JSONDecodeError, KeyError):
            pass
        return None


# ============================================================
# 分层爬取引擎（LayeredCrawler）
# ============================================================

class LayeredCrawler:
    """
    四级爬取策略 — 从轻到重逐级升级

    Level 1: curl_cffi（TLS 伪装，90% 场景）
    Level 2: Firecrawl MCP（远程，无需 Key，JS 渲染）
    Level 3: Crawl4AI Docker（本地，magic_mode 反检测）
    Level 4: Camoufox（C++ 级指纹，最强反检测，按需）

    使用方式：
        crawler = LayeredCrawler()
        result = crawler.crawl("https://example.com", stealth=True)
        if result:
            print(result["content"], result["method"], result["level"])
    """

    # 反爬拦截信号（检测到这些关键词则认为被拦截）
    BLOCK_SIGNALS = [
        "cloudflare", "access denied", "captcha",
        "please verify", "attention required", "blocked",
        "unusual traffic", "rate limit", "cf-ray",
    ]

    def __init__(self):
        self._firecrawl_client = None       # 懒加载 Firecrawl MCP 客户端
        self._camoufox_available: Optional[bool] = None  # None = 尚未检测

    # ------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------

    def crawl(self, url: str, stealth: bool = False) -> Optional[Dict]:
        """
        自动选择最佳爬取层级（同步入口）

        Args:
            url: 目标 URL
            stealth: 是否启用反检测模式（启用后尝试 Level 4 Camoufox）

        Returns:
            {"content": str, "method": str, "level": int}，全部失败返回 None
        """
        # Level 1: curl_cffi 快速尝试
        try:
            html = self._crawl_cffi(url)
            if html and self._is_valid(html):
                return {"content": html, "method": "curl_cffi", "level": 1}
        except Exception:
            pass

        # Level 2: Firecrawl 远程 MCP（无需 Key）
        try:
            content = self._crawl_firecrawl(url)
            if content:
                return {"content": content, "method": "firecrawl", "level": 2}
        except Exception:
            pass

        # Level 3: Crawl4AI Docker（本地，magic_mode）
        try:
            content = self._crawl_crawl4ai(url, stealth=stealth)
            if content:
                return {"content": content, "method": "crawl4ai", "level": 3}
        except Exception:
            pass

        # Level 4: Camoufox（最强反检测，仅 stealth 模式下启用）
        if stealth:
            try:
                content = self._crawl_camoufox(url)
                if content:
                    return {"content": content, "method": "camoufox", "level": 4}
            except Exception:
                pass

        return None

    async def acrawl(self, url: str, stealth: bool = False) -> Optional[Dict]:
        """
        异步入口（同步包装，供异步调用方使用）

        现有引擎为同步架构，此方法内部直接调用同步 crawl()。
        """
        return self.crawl(url, stealth)

    # ------------------------------------------------------------
    # Level 1: curl_cffi
    # ------------------------------------------------------------

    def _crawl_cffi(self, url: str) -> Optional[str]:
        """Level 1: curl_cffi TLS 伪装（自动最新 Chrome 指纹）"""
        raw = _http_get(
            url,
            timeout=15,
            max_retries=2,
            impersonate="chrome",
        )
        if raw:
            return _decode_html(raw)
        return None

    # ------------------------------------------------------------
    # Level 2: Firecrawl MCP
    # ------------------------------------------------------------

    def _crawl_firecrawl(self, url: str) -> Optional[str]:
        """Level 2: Firecrawl 远程 MCP（JS 渲染，无需 API Key）"""
        if self._firecrawl_client is None:
            try:
                from .mcp_client import McpClient
                self._firecrawl_client = McpClient("firecrawl")
            except Exception:
                return None

        if not self._firecrawl_client.is_available():
            return None

        result = self._firecrawl_client.call_tool("firecrawl_scrape", {
            "url": url,
            "formats": ["markdown"],
        })

        if result and "content" in result:
            for item in result["content"]:
                if item.get("text"):
                    try:
                        data = json.loads(item["text"])
                        return data.get("markdown") or data.get("content")
                    except json.JSONDecodeError:
                        return item["text"]
        return None

    # ------------------------------------------------------------
    # Level 3: Crawl4AI Docker
    # ------------------------------------------------------------

    def _crawl_crawl4ai(self, url: str, stealth: bool = True) -> Optional[str]:
        """Level 3: Crawl4AI Docker REST API（magic_mode 反检测）"""
        engine = Crawl4aiEngine()
        return engine.extract(url, stealth=stealth)

    # ------------------------------------------------------------
    # Level 4: Camoufox
    # ------------------------------------------------------------

    def _crawl_camoufox(self, url: str) -> Optional[str]:
        """
        Level 4: Camoufox C++ 级指纹（最强反检测）

        Camoufox 为可选依赖，import 失败时优雅降级（返回 None）。
        异步 API 通过 asyncio.run() 同步包装。
        """

        # 检测 Camoufox 是否可用（仅首次检测，缓存结果）
        if self._camoufox_available is None:
            try:
                from camoufox.async_api import AsyncCamoufox  # noqa: F401
                self._camoufox_available = True
            except ImportError:
                self._camoufox_available = False

        if not self._camoufox_available:
            return None

        async def _do_crawl() -> Optional[str]:
            from camoufox.async_api import AsyncCamoufox
            async with AsyncCamoufox(
                headless=True,
                humanize=True,    # 人形化鼠标移动
                geoip=True,       # 自动地理匹配
            ) as browser:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle")
                html = await page.content()
                await page.close()
                return html

        try:
            return asyncio.run(_do_crawl())
        except Exception:
            return None

    # ------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------

    @classmethod
    def _is_valid(cls, html: str) -> bool:
        """
        检测 HTML 内容是否有效（未被反爬拦截）

        判定规则：
        1. 内容不为空且长度 ≥ 200 字符
        2. 不包含已知的反爬拦截信号
        """
        if not html or len(html) < 200:
            return False
        lower = html.lower()
        return not any(sig in lower for sig in cls.BLOCK_SIGNALS)
