"""
Deep Research Ultra v4.0 — Layer 2: 全局 Skill 引擎封装

六个 Skill 引擎（Claude Code 已安装的全局 skill，直接复用）：
- AgentReachEngine: 13 平台社交媒体搜索（小红书/X/B站/Reddit/V2EX/LinkedIn/YouTube/GitHub/播客/RSS）
- OssFinderEngine: 跨 GitHub/GitLab/Gitee/npm/PyPI 搜索开源项目
- Last30DaysEngine: 近 30 天全网调研（Reddit/X/YouTube/TikTok/HN/Polymarket/GitHub）
- SciverseEngine: 学术论文深度检索（结构化元数据、语义分块、图表提取）
- DefuddleEngine: 网页转 Markdown（去除广告/导航，替代 Jina Reader）
- Context7Engine: 拉取最新库文档（用于技术调研）

设计说明：
- Skill 必须通过 Claude Code 的 Skill 工具调用，Python 无法直接调用
- 本模块的作用是：
  1. 声明每个 skill 的能力（metadata）
  2. 检测 skill 是否已安装（is_available）
  3. 生成调用模板（get_invocation_template），供 Claude 读取后通过 Skill 工具调用
- 实际搜索由 Claude 在 Execute 阶段通过 Skill 工具完成
- Python 负责结果处理（评分、验证、合成）

使用流程：
    engine = AgentReachEngine()
    if engine.is_available():
        template = engine.get_invocation_template(query="AI agent", max_results=10)
        # template 是一段提示词，告诉 Claude 如何调用 agent-reach skill
        # Claude 读取后通过 Skill 工具调用，并把结果传回 Python 处理
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from .base import SearchEngine, SearchResult, EngineMetadata


# ============================================================
# Skill 安装位置检测
# ============================================================

def _get_skill_directories() -> List[Path]:
    """
    返回所有可能的 skill 安装目录

    按优先级：
    1. 项目级 .agents/skills/
    2. 用户级 ~/.claude/skills/
    3. 用户级 ~/.trae-cn/skills/
    4. 用户级 ~/.config/claude/skills/
    """
    home = Path.home()
    cwd = Path.cwd()
    return [
        cwd / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".trae-cn" / "skills",
        home / ".config" / "claude" / "skills",
    ]


def is_skill_installed(skill_name: str) -> bool:
    """
    检测 skill 是否已安装

    Args:
        skill_name: skill 名称（如 'agent-reach', 'sciverse'）

    Returns:
        True 如果在任何 skill 目录中找到对应 SKILL.md
    """
    for skills_dir in _get_skill_directories():
        if not skills_dir.exists():
            continue
        # 检查多种命名：agent-reach / skill_agent_agent-reach
        candidates = [
            skills_dir / skill_name / "SKILL.md",
            skills_dir / f"skill_agent_{skill_name}" / "SKILL.md",
            skills_dir / skill_name / "skill.md",
        ]
        for candidate in candidates:
            if candidate.exists():
                return True
    return False


def list_installed_skills() -> List[str]:
    """列出所有已安装的 skill"""
    installed = set()
    for skills_dir in _get_skill_directories():
        if not skills_dir.exists():
            continue
        for entry in skills_dir.iterdir():
            if entry.is_dir():
                skill_file = entry / "SKILL.md"
                if skill_file.exists():
                    # 提取 skill 名（去掉 skill_agent_ 前缀）
                    name = entry.name
                    if name.startswith("skill_agent_"):
                        name = name[len("skill_agent_"):]
                    installed.add(name)
    return sorted(installed)


# ============================================================
# Skill 引擎基类
# ============================================================

class SkillEngineBase(SearchEngine):
    """
    Skill 引擎基类

    提供 skill 引擎的通用功能：
    - is_available(): 检测 skill 是否已安装
    - search(): 返回调用模板（不直接执行搜索）
    - get_invocation_template(): 生成 Claude 调用提示词
    """

    def __init__(self, skill_name: str):
        self._skill_name = skill_name

    @property
    def skill_name(self) -> str:
        """获取 skill 名称"""
        return self._skill_name

    def is_available(self) -> bool:
        """检测 skill 是否已安装"""
        return is_skill_installed(self._skill_name)

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        Skill 引擎不能从 Python 直接调用

        返回 None 表示需要 Claude 通过 Skill 工具调用。
        Claude 应先调用 get_invocation_template() 获取调用提示，
        然后通过 Skill 工具执行，再把结果传回 Python 处理。
        """
        return None

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        """
        生成 Claude 调用提示模板

        Returns:
            {
                'skill_name': str,
                'trigger_keywords': List[str],
                'instruction': str,  # Claude 应该读取并执行的指令
                'expected_output': str,  # 期望的输出格式
                'post_process': str,  # 结果后处理提示
            }
        """
        return {
            'skill_name': self._skill_name,
            'trigger_keywords': [],
            'instruction': f"通过 Skill 工具调用 {self._skill_name} skill",
            'expected_output': 'SearchResult 列表',
            'post_process': '将结果转为 SearchResult 对象',
        }


# ============================================================
# 1. agent-reach 引擎
# ============================================================

class AgentReachEngine(SkillEngineBase):
    """
    agent-reach skill 引擎

    能力：13 平台社交媒体搜索
    平台：小红书/X/B站/Reddit/V2EX/LinkedIn/YouTube/GitHub/播客/RSS
    用途：社区讨论、口碑、真实案例
    """

    # 支持的平台
    SUPPORTED_PLATFORMS = [
        "xiaohongshu", "twitter", "bilibili", "reddit", "v2ex",
        "linkedin", "youtube", "github", "podcast", "rss",
        "weibo", "zhihu", "tiktok",
    ]

    def __init__(self):
        super().__init__("agent-reach")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="agent-reach",
            layer=2,
            description="agent-reach 13 平台社交媒体搜索（小红书/X/B站/Reddit/V2EX/LinkedIn/YouTube 等）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=60,
            capabilities=["search", "community"],
        )

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        platform = kwargs.get("platform", "")
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 10)
        platform_hint = f"平台: {platform}" if platform else "自动路由平台"
        return {
            'skill_name': 'agent-reach',
            'trigger_keywords': ['调研', 'research', '搜索', 'search', '小红书', 'reddit', 'twitter'],
            'instruction': (
                f"通过 Skill 工具调用 agent-reach skill。\n"
                f"任务：搜索 '{query}'\n"
                f"{platform_hint}\n"
                f"返回最多 {max_results} 条结果\n"
                f"如果指定了 platform，请明确告诉 skill 要搜索的平台。\n"
                f"如果未指定，让 agent-reach 自动路由到合适的平台。"
            ),
            'expected_output': '包含 title/url/content/platform 的列表',
            'post_process': '将每条结果转为 SearchResult(source="agent-reach", engine=platform)',
        }


# ============================================================
# 2. oss-finder 引擎
# ============================================================

class OssFinderEngine(SkillEngineBase):
    """
    oss-finder skill 引擎

    能力：跨 GitHub/GitLab/Gitee/npm/PyPI 搜索开源项目
    用途：技术调研、开源方案对比
    """

    SUPPORTED_REGISTRIES = ["github", "gitlab", "gitee", "npm", "pypi"]

    def __init__(self):
        super().__init__("oss-finder")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="oss-finder",
            layer=2,
            description="oss-finder 开源项目搜索（GitHub/GitLab/Gitee/npm/PyPI）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=70,
            capabilities=["search", "community"],
        )

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 10)
        registry = kwargs.get("registry", "")
        language = kwargs.get("language", "")
        stars_min = kwargs.get("stars_min", 0)

        instruction = (
            f"通过 Skill 工具调用 oss-finder skill。\n"
            f"任务：搜索开源项目 '{query}'\n"
            f"返回最多 {max_results} 条结果\n"
        )
        if registry:
            instruction += f"指定仓库: {registry}\n"
        if language:
            instruction += f"编程语言: {language}\n"
        if stars_min:
            instruction += f"最低 stars 数: {stars_min}\n"

        return {
            'skill_name': 'oss-finder',
            'trigger_keywords': ['开源', 'open source', 'github', 'npm', 'pypi', 'find repos'],
            'instruction': instruction,
            'expected_output': '包含 name/url/description/stars/language 的列表',
            'post_process': '将每条结果转为 SearchResult(source="oss-finder", engine=registry)',
        }


# ============================================================
# 3. last30days 引擎
# ============================================================

class Last30DaysEngine(SkillEngineBase):
    """
    last30days skill 引擎

    能力：近 30 天全网调研
    平台：Reddit/X/YouTube/TikTok/HackerNews/Polymarket/GitHub
    用途：时效性调研、热点追踪
    """

    SUPPORTED_SOURCES = ["reddit", "x", "youtube", "tiktok", "hackernews", "polymarket", "github"]

    def __init__(self):
        super().__init__("last30days")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="last30days",
            layer=2,
            description="last30days 近 30 天全网调研（Reddit/X/YouTube/TikTok/HN/Polymarket/GitHub）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=80,
            capabilities=["search", "community"],
        )

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        days = kwargs.get("days", 30)
        sources = kwargs.get("sources", [])

        instruction = (
            f"通过 Skill 工具调用 last30days skill。\n"
            f"任务：搜索 '{query}' 在最近 {days} 天的内容\n"
        )
        if sources:
            instruction += f"指定数据源: {', '.join(sources)}\n"

        return {
            'skill_name': 'last30days',
            'trigger_keywords': ['最近', 'latest', 'recent', '近30天', 'last 30 days', '热点'],
            'instruction': instruction,
            'expected_output': '包含 title/url/content/date/engagement 的列表',
            'post_process': '将每条结果转为 SearchResult(source="last30days", engine=原始平台)',
        }


# ============================================================
# 4. sciverse 引擎
# ============================================================

class SciverseEngine(SkillEngineBase):
    """
    sciverse skill 引擎

    能力：学术论文深度检索
    功能：结构化元数据、语义分块、图表提取、来源扩展
    用途：学术调研、论文引用
    """

    def __init__(self):
        super().__init__("sciverse")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="sciverse",
            layer=2,
            description="sciverse 学术论文深度检索（结构化元数据、语义分块、图表提取）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=90,
            capabilities=["search", "academic"],
        )

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 10)
        year_from = kwargs.get("year_from", "")
        year_to = kwargs.get("year_to", "")

        instruction = (
            f"通过 Skill 工具调用 sciverse skill。\n"
            f"任务：检索学术论文 '{query}'\n"
            f"返回最多 {max_results} 篇论文\n"
        )
        if year_from:
            instruction += f"起始年份: {year_from}\n"
        if year_to:
            instruction += f"截止年份: {year_to}\n"

        return {
            'skill_name': 'sciverse',
            'trigger_keywords': ['论文', 'paper', '学术', 'academic', 'citation', '引用'],
            'instruction': instruction,
            'expected_output': '包含 title/authors/abstract/doi/url/year 的论文列表',
            'post_process': '将每篇论文转为 SearchResult(source="sciverse", engine="sciverse")',
        }


# ============================================================
# 5. defuddle 引擎
# ============================================================

class DefuddleEngine(SkillEngineBase):
    """
    defuddle skill 引擎

    能力：网页转 Markdown（去除广告/导航）
    用途：替代 Jina Reader，本地化、无需 VPN
    """

    def __init__(self):
        super().__init__("defuddle")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="defuddle",
            layer=2,
            description="defuddle 网页转 Markdown（去除广告/导航，替代 Jina Reader）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=100,
            capabilities=["extract"],
        )

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        url = kwargs.get("url", "")

        return {
            'skill_name': 'defuddle',
            'trigger_keywords': ['提取', 'extract', '网页内容', 'markdown', 'read'],
            'instruction': (
                f"通过 Skill 工具调用 defuddle skill。\n"
                f"任务：提取网页内容并转为 Markdown\n"
                f"URL: {url}\n"
                f"去除广告、导航、侧边栏等干扰内容，只保留正文。"
            ),
            'expected_output': 'Markdown 格式的正文内容',
            'post_process': '将内容包装为 SearchResult(source="defuddle", engine="defuddle")',
        }


# ============================================================
# 6. context7 引擎
# ============================================================

class Context7Engine(SkillEngineBase):
    """
    context7 skill 引擎

    能力：拉取最新库文档
    用途：技术调研、API 文档查询
    """

    def __init__(self):
        super().__init__("context7")

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="context7",
            layer=2,
            description="context7 库文档拉取（用于技术调研、API 文档查询）",
            requires_config=False,
            config_keys=[],
            is_async_supported=True,
            is_china_friendly=True,
            priority=110,
            capabilities=["search", "extract"],
        )

    def get_invocation_template(self, **kwargs) -> Dict[str, Any]:
        library = kwargs.get("library", "")
        topic = kwargs.get("topic", "")

        instruction = (
            f"通过 Skill 工具调用 context7 skill。\n"
            f"任务：拉取库的最新文档\n"
        )
        if library:
            instruction += f"库名: {library}\n"
        if topic:
            instruction += f"主题/特性: {topic}\n"

        return {
            'skill_name': 'context7',
            'trigger_keywords': ['文档', 'docs', 'documentation', 'API', '库', 'library'],
            'instruction': instruction,
            'expected_output': 'Markdown 格式的 API 文档片段',
            'post_process': '将文档包装为 SearchResult(source="context7", engine="context7")',
        }
