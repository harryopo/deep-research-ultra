"""
Deep Research Ultra v4.0 — Layer 3: Claude 内置工具引擎封装

两个内置工具引擎：
- WebSearchEngine: Claude 内置 WebSearch 工具（实时网络搜索）
- WebFetchEngine: Claude 内置 WebFetch 工具（简单网页抓取）

设计说明：
- 这两个引擎对应 Claude Code 内置的 WebSearch 和 WebFetch 工具
- Python 不能直接调用 Claude 内置工具
- 本模块的作用是：
  1. 声明能力（metadata）
  2. is_available() 始终返回 True（内置工具总是可用）
  3. search() 返回 None（需 Claude 通过工具调用）
  4. get_invocation_template() 返回调用提示

与其他层的关系：
- Layer 1 (MCP) 不可用时降级到 Layer 3
- Layer 2 (Skill) 不可用时降级到 Layer 3
- Layer 3 是 Claude 自带能力，永远可用
- Layer 4 (Fallback) 是 Python 脚本兜底
"""

from typing import Dict, List, Optional, Any

from .base import SearchEngine, SearchResult, EngineMetadata


# ============================================================
# 1. WebSearch 引擎
# ============================================================

class WebSearchEngine(SearchEngine):
    """
    Claude 内置 WebSearch 引擎

    能力：实时网络搜索
    国内可用：✅（Claude 内置工具，由 Claude 处理网络访问）
    """

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="websearch",
            layer=3,
            description="Claude 内置 WebSearch 工具（实时网络搜索）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=200,
            capabilities=["search"],
        )

    def is_available(self) -> bool:
        """Claude 内置工具始终可用"""
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        WebSearch 不能从 Python 直接调用

        返回 None 表示需要 Claude 通过 WebSearch 工具调用。
        """
        return None

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        """生成 Claude 调用提示"""
        query = kwargs.get("query", "")
        num = kwargs.get("num", 5)
        lr = kwargs.get("lr", "")  # 语言限制，如 'lang_en' / 'lang_zh-CN'

        instruction = (
            f"使用 Claude 内置 WebSearch 工具搜索：\n"
            f"  query: {query}\n"
            f"  num: {num}\n"
        )
        if lr:
            instruction += f"  lr: {lr}\n"

        return {
            'tool_name': 'WebSearch',
            'instruction': instruction,
            'expected_output': '包含 title/url/snippet 的搜索结果列表',
            'post_process': '将每条结果转为 SearchResult(source="websearch", engine="websearch")',
        }


# ============================================================
# 2. WebFetch 引擎
# ============================================================

class WebFetchEngine(SearchEngine):
    """
    Claude 内置 WebFetch 引擎

    能力：网页内容抓取（转 Markdown）
    国内可用：✅（Claude 内置工具）
    限制：对认证页面/私域无效
    """

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="webfetch",
            layer=3,
            description="Claude 内置 WebFetch 工具（网页抓取转 Markdown）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=210,
            capabilities=["extract"],
        )

    def is_available(self) -> bool:
        """Claude 内置工具始终可用"""
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """WebFetch 不是搜索引擎，不能搜索"""
        return None

    def extract(self, url: str, **kwargs) -> Optional[str]:
        """
        WebFetch 不能从 Python 直接调用

        返回 None 表示需要 Claude 通过 WebFetch 工具调用。
        """
        return None

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        """生成 Claude 调用提示"""
        url = kwargs.get("url", "")

        return {
            'tool_name': 'WebFetch',
            'instruction': (
                f"使用 Claude 内置 WebFetch 工具抓取网页：\n"
                f"  url: {url}\n"
                f"返回 Markdown 格式的内容。"
            ),
            'expected_output': 'Markdown 格式的网页内容',
            'post_process': '将内容包装为 SearchResult(source="webfetch", engine="webfetch")',
        }
