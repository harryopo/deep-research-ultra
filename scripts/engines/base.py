"""
Deep Research Ultra v4.0 — 搜索引擎抽象基类

所有数据源（MCP/Skill/内置/降级）都实现此接口，
实现统一的多源并发调度与降级策略。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from datetime import datetime


# ============================================================
# 数据结构定义
# ============================================================

@dataclass
class EngineMetadata:
    """引擎元数据"""
    name: str                        # 引擎唯一标识（如 'tavily'）
    layer: int                       # 架构层（1=MCP, 2=Skill, 3=内置, 4=降级）
    description: str                 # 中文描述
    requires_config: bool = False    # 是否需要配置（API Key/VPN/自建实例）
    config_keys: List[str] = field(default_factory=list)  # 需要的环境变量
    is_async_supported: bool = True  # 是否支持异步
    is_china_friendly: bool = True   # 国内是否可用
    priority: int = 100              # 降级优先级（数字越小优先级越高）
    capabilities: List[str] = field(default_factory=list)  # 能力标签：['search', 'extract', 'crawl', 'academic', 'community']


@dataclass
class SearchResult:
    """统一的搜索结果数据结构"""
    title: str                       # 标题
    url: str                         # 来源 URL
    content: str                     # 摘要/内容
    source: str                      # 数据源名称（如 'tavily'）
    score: float = 0.0               # 原始评分（如有）
    craap_score: Optional[Dict] = None  # CRAAP 五维评分（由 score.py 填充）
    published_date: str = ''         # 发布日期
    author: str = ''                 # 作者
    engine: str = ''                 # 实际使用的引擎
    raw: Dict = field(default_factory=dict)  # 原始数据（调试用）

    def to_dict(self) -> Dict:
        """转为字典"""
        return {
            'title': self.title,
            'url': self.url,
            'content': self.content,
            'source': self.source,
            'score': self.score,
            'craap_score': self.craap_score,
            'published_date': self.published_date,
            'author': self.author,
            'engine': self.engine,
        }


# ============================================================
# 抽象基类
# ============================================================

class SearchEngine(ABC):
    """
    搜索引擎抽象基类

    所有数据源（MCP/Skill/内置/降级）都实现此接口。

    使用模式：
        class MyEngine(SearchEngine):
            @property
            def metadata(self) -> EngineMetadata:
                return EngineMetadata(name='my-engine', ...)

            def is_available(self) -> bool:
                ...

            def search(self, query, max_results=10, **kwargs) -> Optional[List[SearchResult]]:
                ...

    调用方式：
        engine = MyEngine()
        if engine.is_available():
            results = engine.search("关键词")
    """

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata:
        """返回引擎元数据"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        检查引擎是否可用

        Returns:
            True 如果引擎配置正确且可达
        """
        pass

    @abstractmethod
    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        执行搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs: 引擎特定参数（如 search_depth, timelimit, language 等）

        Returns:
            SearchResult 列表，失败返回 None
        """
        pass

    def extract(self, url: str, **kwargs) -> Optional[str]:
        """
        从 URL 提取内容（可选实现）

        Args:
            url: 要提取的 URL

        Returns:
            提取的 Markdown/文本内容，不支持返回 None
        """
        return None

    def crawl(self, url: str, max_pages: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        爬取网站（可选实现）

        Args:
            url: 起始 URL
            max_pages: 最大页面数

        Returns:
            SearchResult 列表，不支持返回 None
        """
        return None

    def get_name(self) -> str:
        """获取引擎名称"""
        return self.metadata.name

    def get_layer(self) -> int:
        """获取架构层（1-4）"""
        return self.metadata.layer

    def get_capabilities(self) -> List[str]:
        """获取能力标签"""
        return self.metadata.capabilities

    def has_capability(self, capability: str) -> bool:
        """检查是否具备某项能力"""
        return capability in self.metadata.capabilities

    def __repr__(self) -> str:
        m = self.metadata
        return f"<{self.__class__.__name__} name={m.name} layer={m.layer} available={self.is_available()}>"


# ============================================================
# 引擎注册表
# ============================================================

class EngineRegistry:
    """
    引擎注册表 — 管理所有已注册的搜索引擎

    用途：
        - 按名称获取引擎
        - 按 layer 获取一组引擎
        - 按 capability 获取一组引擎
        - 按可用性过滤引擎
    """

    def __init__(self):
        self._engines: Dict[str, SearchEngine] = {}

    def register(self, engine: SearchEngine) -> None:
        """注册引擎"""
        name = engine.get_name()
        if name in self._engines:
            raise ValueError(f"引擎已注册: {name}")
        self._engines[name] = engine

    def get(self, name: str) -> Optional[SearchEngine]:
        """按名称获取引擎"""
        return self._engines.get(name)

    def get_by_layer(self, layer: int, only_available: bool = True) -> List[SearchEngine]:
        """按架构层获取引擎"""
        engines = [e for e in self._engines.values() if e.get_layer() == layer]
        if only_available:
            engines = [e for e in engines if e.is_available()]
        # 按 priority 排序（数字越小优先级越高）
        engines.sort(key=lambda e: e.metadata.priority)
        return engines

    def get_by_capability(self, capability: str, only_available: bool = True) -> List[SearchEngine]:
        """按能力获取引擎"""
        engines = [e for e in self._engines.values() if e.has_capability(capability)]
        if only_available:
            engines = [e for e in engines if e.is_available()]
        engines.sort(key=lambda e: e.metadata.priority)
        return engines

    def get_available(self) -> List[SearchEngine]:
        """获取所有可用引擎"""
        return [e for e in self._engines.values() if e.is_available()]

    def get_all(self) -> List[SearchEngine]:
        """获取所有已注册引擎"""
        return list(self._engines.values())

    def get_names(self, only_available: bool = False) -> List[str]:
        """获取引擎名称列表"""
        if only_available:
            return [e.get_name() for e in self._engines.values() if e.is_available()]
        return list(self._engines.keys())

    def get_fallback_chain(self) -> List[SearchEngine]:
        """
        获取降级链（按优先级排序的可用引擎）

        优先级顺序：
            Layer 1 (MCP) → Layer 2 (Skill) → Layer 3 (内置) → Layer 4 (降级)
        """
        available = self.get_available()
        # 先按 layer，再按 priority
        available.sort(key=lambda e: (e.get_layer(), e.metadata.priority))
        return available

    def __len__(self) -> int:
        return len(self._engines)

    def __contains__(self, name: str) -> bool:
        return name in self._engines

    def summary(self) -> Dict:
        """返回引擎注册表摘要"""
        available = self.get_available()
        return {
            "total": len(self._engines),
            "available": len(available),
            "by_layer": {
                1: len([e for e in available if e.get_layer() == 1]),
                2: len([e for e in available if e.get_layer() == 2]),
                3: len([e for e in available if e.get_layer() == 3]),
                4: len([e for e in available if e.get_layer() == 4]),
            },
            "available_names": [e.get_name() for e in available],
        }
