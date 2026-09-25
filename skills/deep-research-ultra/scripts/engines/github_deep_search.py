"""
Deep Research Ultra v5.2 — Layer 2: GitHub 深度搜索引擎

解决"调研开源项目漏掉低星项目"问题的核心引擎。

设计理念（来自 GitHub 深度搜索技巧调研报告）：
- 分桶搜索（Bucket Search）：将 star 范围分为 4 档，每档独立搜索，确保低星项目不被淹没
- 多维度组合查询：language + topic + created + pushed 多维度交叉
- 依赖图反向挖掘：从种子项目出发，搜索其 dependents
- Awesome 列表挖掘：自动查找相关 awesome 列表并提取项目
- 多源交叉：GitHub REST API + 代码搜索 + topic 搜索

关键改进（对比 OssFinderEngine）：
- OssFinderEngine 只生成调用模板交给 oss-finder skill，无分页、无低星挖掘
- GitHubDeepSearchEngine 直接调用 GitHub REST API，分桶+多维度+依赖图+awesome

API 文档：
- Search repositories: https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28#search-repositories
- Search code: https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28#search-code
- Rate limit: 无认证 10 req/min，有认证 30 req/min（搜索端点专用）
"""

import json
import sys
import os
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Any

from .base import SearchEngine, SearchResult, EngineMetadata
from .fallback import _http_get, _json_loads, _decode_html


# ============================================================
# GitHub 深度搜索引擎
# ============================================================

# GitHub repository search 把多词查询按 AND 同时匹配 name/description/readme，
# 因此一条长自然语言查询几乎必然 0 命中。仓库搜索的有效查询长度 <= 3 个词。
MAX_QUERY_TOKENS = 3
_QUERY_NOISE = {
    'the', 'a', 'an', 'for', 'with', 'and', 'or', 'of', 'to', 'in', 'on',
    'how', 'what', 'why', 'that', 'this', 'it', 'is', 'are', 'from', 'by',
    'all', 'can', 'do', 'does', 'you', 'your', 'i', 'we', 'best', 'top',
    'please', 'some', 'any', 'used', 'using', 'use',
}


def normalize_repo_query(query: str, max_tokens: int = MAX_QUERY_TOKENS) -> str:
    """把过长的自然语言查询压成 GitHub 能用的高信号短查询。

    词数已 <= max_tokens 时原样返回（不干扰调用方精心构造的查询）；
    超长时按词长降序挑词、再按原顺序拼回——词长是本文件可用且无依赖的
    信息量代理（'correction' 比 'with' 更可能是仓库主题词）。
    """
    raw = ' '.join(str(query).split())
    if not raw:
        return ''
    tokens = [t for t in re.split(r"[\s,;|]+", raw) if t]
    kept = [t for t in tokens
            if len(t) > 1 and t.lower() not in _QUERY_NOISE and ':' not in t]
    if len(kept) <= max_tokens:
        return raw.lower()
    order = sorted(range(len(kept)), key=lambda i: (-len(kept[i]), i))[:max_tokens]
    return ' '.join(kept[i].lower() for i in sorted(order))


class GitHubDeepSearchEngine(SearchEngine):
    """
    GitHub 深度搜索引擎（分桶搜索 + 低星挖掘 + 依赖图 + awesome 列表）

    能力：search, opensource, deep_search, dependency_graph, awesome_mining
    数据量：100M+ 仓库
    API Key：可选（GITHUB_TOKEN，无认证有严格速率限制）
    国内可用：✅（api.github.com 国内可达）
    速率限制：无认证 10 req/min，有认证 30 req/min（搜索端点）
    功能：分桶搜索 + 多维度组合 + 依赖图挖掘 + awesome 列表挖掘

    分桶策略（确保低星项目不被遗漏）：
        Bucket 1 (旗舰): stars:>=1000    → 25% 结果配额
        Bucket 2 (主流): stars:100..999  → 25% 结果配额
        Bucket 3 (小众): stars:10..99    → 25% 结果配额
        Bucket 4 (微星): stars:<10       → 25% 结果配额
    """

    # GitHub API 端点
    SEARCH_REPOS_URL = "https://api.github.com/search/repositories"
    SEARCH_CODE_URL = "https://api.github.com/search/code"
    SEARCH_TOPICS_URL = "https://api.github.com/search/topics"
    REPO_URL = "https://api.github.com/repos/{full_name}"

    # 分桶配置：(star_range, label)
    STAR_BUCKETS = [
        ('stars:>=1000', '旗舰', 'flagship'),
        ('stars:100..999', '主流', 'mainstream'),
        ('stars:10..99', '小众', 'niche'),
        ('stars:<10', '微星', 'emerging'),
    ]

    # 类变量：上次请求时间（用于速率限制，跨实例共享）
    _last_request_time: float = 0.0

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="github-deep-search",
            layer=2,
            description="GitHub 深度搜索（分桶+低星挖掘+依赖图+awesome，不漏项目）",
            requires_config=False,
            config_keys=["GITHUB_TOKEN"],
            is_async_supported=False,
            is_china_friendly=True,
            priority=65,  # 优先于 oss-finder（70），深度搜索优先
            capabilities=["search", "opensource", "deep_search", "dependency_graph", "awesome_mining"],
        )

    def _get_headers(self) -> Dict[str, str]:
        """获取 GitHub API 请求头（含认证 token 如有）"""
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        token = os.environ.get('GITHUB_TOKEN', '')
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def _rate_limit(self) -> None:
        """
        GitHub 搜索 API 速率限制
        无认证: 10 req/min → 间隔 6 秒
        有认证: 30 req/min → 间隔 2 秒
        """
        token = os.environ.get('GITHUB_TOKEN', '')
        min_interval = 2.0 if token else 6.0
        elapsed = time.time() - GitHubDeepSearchEngine._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        GitHubDeepSearchEngine._last_request_time = time.time()

    def is_available(self) -> bool:
        """检查 GitHub API 是否可达"""
        try:
            headers = self._get_headers()
            params = urllib.parse.urlencode({'q': 'test', 'per_page': 1})
            url = f"{self.SEARCH_REPOS_URL}?{params}"
            self._rate_limit()
            raw = _http_get(url, headers=headers, timeout=15, max_retries=1)
            return raw is not None
        except Exception:
            return False

    def search(self, query: str, max_results: int = 20, **kwargs) -> Optional[List[SearchResult]]:
        """
        GitHub 深度搜索（分桶策略，确保低星项目不被遗漏）

        Args:
            query: 搜索关键词
            max_results: 最大结果数（总数，会分配到各桶）
            **kwargs:
                language: 编程语言过滤（如 'python'）
                topic: topic 过滤（如 'deep-learning'）
                created_after: 创建时间过滤（如 '2024-01-01'）
                pushed_after: 最近推送时间过滤（如 '2025-01-01'）
                license: 许可证过滤（如 'mit'）
                sort: 排序方式（'stars'/'forks'/'updated'/'best-match'）
                exclude_forks: 排除 fork（默认 True）
                deep: 启用深度搜索（依赖图 + awesome，默认 False）
                seed_repos: 种子项目列表（用于依赖图挖掘，如 ['langchain-ai/langchain']）

        Returns:
            SearchResult 列表，按桶分组，低星项目也有展示机会
        """
        language = kwargs.get('language', '')
        topic = kwargs.get('topic', '')
        created_after = kwargs.get('created_after', '')
        pushed_after = kwargs.get('pushed_after', '')
        license_filter = kwargs.get('license', '')
        sort = kwargs.get('sort', 'best-match')
        exclude_forks = kwargs.get('exclude_forks', True)
        deep = kwargs.get('deep', False)
        seed_repos = kwargs.get('seed_repos', [])

        # 首轮就归一，不做"先按原查询打满 4 个桶、失败再重试"——
        # 长 AND 查询必然 0 命中，那样只是把搜索配额白烧一倍。
        normalized = normalize_repo_query(query)
        if normalized != query.strip().lower():
            kept = normalized.split()
            dropped = [t.lower() for t in re.split(r"[\s,;|]+", query.strip())
                       if t and t.lower() not in kept]
            print(f"\u26a0\ufe0f github-deep-search 查询已归一："
                  f"{query[:60]!r} \u2192 {normalized!r}"
                  f"（GitHub 仓库搜索按 AND 匹配，长查询恒 0 命中）"
                  f"被丢掉的词：{', '.join(dropped) or '（无）'}", file=sys.stderr)
            query = normalized

        # 分桶搜索：每桶分配 1/4 的结果配额
        per_bucket = max(5, max_results // len(self.STAR_BUCKETS))
        all_results: List[SearchResult] = []
        seen_repos: set = set()

        for star_range, bucket_label, bucket_key in self.STAR_BUCKETS:
            bucket_results = self._search_bucket(
                query=query,
                star_range=star_range,
                per_bucket=per_bucket,
                language=language,
                topic=topic,
                created_after=created_after,
                pushed_after=pushed_after,
                license_filter=license_filter,
                sort=sort,
                exclude_forks=exclude_forks,
            )
            if bucket_results:
                for r in bucket_results:
                    repo_url = r.url
                    if repo_url not in seen_repos:
                        seen_repos.add(repo_url)
                        # 标注分桶信息
                        r.raw['star_bucket'] = bucket_key
                        r.raw['star_bucket_label'] = bucket_label
                        r.query = query
                        all_results.append(r)

            if len(all_results) >= max_results:
                break

        # 深度搜索：依赖图挖掘（要种子）+ awesome 列表挖掘（不要种子）
        # 旧写法把两段一起挂在 `if deep and seed_repos:` 下 —— 只传 deep=True 时整段不跑
        discovery: List[SearchResult] = []
        if deep:
            for r in self._search_dependents(seed_repos, per_bucket=per_bucket):
                r.raw['discovery_method'] = 'dependency_graph'
                discovery.append(r)
            for r in self._search_awesome(query, per_bucket=per_bucket):
                r.raw['discovery_method'] = 'awesome_list'
                r.query = query
                discovery.append(r)
            # 挖掘结果排在分桶之后，不给配额就会被下面的截断全部吃掉
            # （实测 deep=True 在 max_results=8/20 下返回的条目 100% 是分桶结果）
            reserve = min(len(discovery), max(1, max_results // 4))
            kept = all_results[:max(0, max_results - reserve)]
            for r in discovery:
                if len(kept) >= max_results:
                    break
                if r.url in seen_repos:
                    continue
                seen_repos.add(r.url)
                kept.append(r)
            all_results = kept

        all_results = all_results[:max_results]
        self._attach_missing_metadata(all_results)
        return all_results if all_results else None

    # 匿名 GitHub API 只有 60 次/小时：补数据也得给正常查询留配额
    ENRICH_LIMIT = 10

    def _attach_missing_metadata(self, results: List[SearchResult]) -> None:
        """就地给"只知道仓库名"的挖掘条目补真实元数据。

        补不到就保留 metadata_missing——"没取到"与"0 星"必须能分开，
        否则评分器会把一个 586 星的仓库按死项目评（get_repo_details 本来就写着
        "用于推荐度评分"，但一直没有调用点）。
        """
        for r in results[:self.ENRICH_LIMIT]:
            if not r.raw.get('metadata_missing'):
                continue
            full_name = r.raw.get('full_name', '')
            details = self.get_repo_details(full_name) if full_name else None
            if not details or details.get('stargazers_count') is None:
                continue
            fresh = self._parse_repo(details)
            if not fresh:
                continue
            for key in ('discovery_method', 'depends_on', 'awesome_source',
                        'star_bucket', 'star_bucket_label'):
                if key in r.raw:
                    fresh.raw[key] = r.raw[key]
            fresh.query = r.query
            r.title, r.url, r.content, r.score = (
                fresh.title, fresh.url, fresh.content, fresh.score)
            r.published_date, r.author, r.raw = (
                fresh.published_date, fresh.author, fresh.raw)

    def _search_bucket(
        self,
        query: str,
        star_range: str,
        per_bucket: int,
        language: str = '',
        topic: str = '',
        created_after: str = '',
        pushed_after: str = '',
        license_filter: str = '',
        sort: str = 'best-match',
        exclude_forks: bool = True,
    ) -> List[SearchResult]:
        """搜索单个 star 桶"""
        # 构建查询字符串
        q_parts = [query, star_range]
        if language:
            q_parts.append(f'language:{language}')
        if topic:
            q_parts.append(f'topic:{topic}')
        if created_after:
            q_parts.append(f'created:>{created_after}')
        if pushed_after:
            q_parts.append(f'pushed:>{pushed_after}')
        if license_filter:
            q_parts.append(f'license:{license_filter}')
        if exclude_forks:
            q_parts.append('fork:false')

        q = ' '.join(q_parts)
        params_dict = {
            'q': q,
            'per_page': str(min(per_bucket, 100)),
            'page': '1',
        }
        if sort != 'best-match':
            params_dict['sort'] = sort
            params_dict['order'] = 'desc' if star_range.startswith('stars:>=') else 'asc'

        params = urllib.parse.urlencode(params_dict)
        url = f"{self.SEARCH_REPOS_URL}?{params}"
        headers = self._get_headers()

        self._rate_limit()
        raw = _http_get(url, headers=headers, timeout=30, max_retries=2)
        if not raw:
            return []

        data = _json_loads(raw)
        if not data or 'items' not in data:
            return []

        results: List[SearchResult] = []
        for item in data['items'][:per_bucket]:
            r = self._parse_repo(item)
            if r:
                results.append(r)
        return results

    def _parse_repo(self, item: Dict) -> Optional[SearchResult]:
        """解析 GitHub 仓库数据为 SearchResult"""
        full_name = item.get('full_name', '')
        if not full_name:
            return None

        name = item.get('name', '')
        html_url = item.get('html_url', '')
        description = item.get('description', '') or ''
        # 「这条通道没返回这个字段」与「这个仓库 star 是 0」是两件事。
        # 实测：code search 的 items[].repository 是瘦身对象（没有 stargazers_count 等），
        # 旧写法 .get(..., 0) 把不知道写成了 0 —— app-builder 被报成 ⭐0，真实 586。
        # 所以这些字段一律取「缺失即 None」，None 的字段不进标题、不进摘要、不进 raw。
        stars = item.get('stargazers_count')
        forks = item.get('forks_count')
        lang = item.get('language', '') or ''
        license_info = item.get('license', {})
        license_name = license_info.get('spdx_id', '') if license_info else ''
        topics = item.get('topics', [])
        created_at = item.get('created_at', '')[:10]
        updated_at = item.get('updated_at', '')[:10]
        pushed_at = item.get('pushed_at', '')[:10]
        open_issues = item.get('open_issues_count')
        watchers = item.get('watchers_count')
        archived = item.get('archived', False)
        owner = item.get('owner', {})
        owner_name = owner.get('login', '') if owner else ''

        # 构建内容摘要：没取到的字段就不写，写了就是编造
        content_parts = []
        if description:
            content_parts.append(description)
        if stars is not None:
            content_parts.append(f"[Stars] {stars}")
        if forks is not None:
            content_parts.append(f"[Forks] {forks}")
        if lang:
            content_parts.append(f"[Language] {lang}")
        if license_name:
            content_parts.append(f"[License] {license_name}")
        if topics:
            content_parts.append(f"[Topics] {', '.join(topics[:5])}")
        if updated_at:
            content_parts.append(f"[Updated] {updated_at}")
        if archived:
            content_parts.append("[Archived] ⚠️ 此仓库已归档")
        content = '\n'.join(content_parts)

        raw = {
            'full_name': full_name,
            'name': name,
            'description': description,
            'language': lang,
            'license': license_name,
            'topics': topics,
            'created_at': created_at,
            'updated_at': updated_at,
            'pushed_at': pushed_at,
            'archived': archived,
            'owner': owner_name,
            'repo_type': 'github',
        }
        for _key, _val in (('stars', stars), ('forks', forks),
                           ('open_issues', open_issues), ('watchers', watchers)):
            if _val is not None:
                raw[_key] = _val
        if stars is None:
            raw['metadata_missing'] = True

        return SearchResult(
            title=f"{full_name} (⭐{stars})" if stars is not None else full_name,
            url=html_url,
            content=content,
            source='github-deep-search',
            score=float(stars) if stars is not None else 0.0,
            published_date=created_at,
            author=owner_name,
            engine='github-deep-search',
            raw=raw,
        )

    def _search_dependents(self, seed_repos: List[str], per_bucket: int = 10) -> List[SearchResult]:
        """
        依赖图反向挖掘：从种子项目出发，搜索依赖它的项目

        GitHub 不提供 dependents API，需通过 code search 间接查找。
        策略：搜索 package.json/requirements.txt/setup.py 中引用种子项目的代码。
        """
        results: List[SearchResult] = []
        for seed in seed_repos[:3]:  # 最多 3 个种子项目
            # 提取项目名（如 'langchain-ai/langchain' → 'langchain'）
            seed_name = seed.split('/')[-1] if '/' in seed else seed

            # 在 package.json / requirements.txt 中搜索引用
            q = f'"{seed_name}" filename:package.json OR filename:requirements.txt OR filename:setup.py'
            params = urllib.parse.urlencode({
                'q': q,
                'per_page': str(min(per_bucket, 30)),
            })
            url = f"{self.SEARCH_CODE_URL}?{params}"
            headers = self._get_headers()

            self._rate_limit()
            raw = _http_get(url, headers=headers, timeout=30, max_retries=1)
            if not raw:
                continue

            data = _json_loads(raw)
            if not data or 'items' not in data:
                continue

            for item in data['items'][:per_bucket]:
                repo = item.get('repository', {})
                if not repo:
                    continue
                full_name = repo.get('full_name', '')
                if not full_name:
                    continue

                # code search 的 repository 对象只给这些字段。旧写法在这里补了一堆
                # `stargazers_count: 0 / license: None / pushed_at: ''`，等于把"不知道"写成事实
                r = self._parse_repo({
                    'full_name': full_name,
                    'name': repo.get('name', ''),
                    'html_url': repo.get('html_url', ''),
                    'description': repo.get('description', ''),
                    'created_at': repo.get('created_at', ''),
                    'updated_at': repo.get('updated_at', ''),
                    'owner': repo.get('owner', {}),
                })
                if r:
                    r.raw['depends_on'] = seed
                    results.append(r)

        return results

    def _search_awesome(self, query: str, per_bucket: int = 10) -> List[SearchResult]:
        """
        Awesome 列表挖掘：查找相关 awesome 列表并提取其中的项目链接

        策略：
        1. 搜索 'awesome-{query}' 仓库
        2. 获取 README 内容
        3. 提取其中的 GitHub 仓库链接
        """
        # 搜索 awesome 列表仓库
        awesome_query = f'awesome {query}'
        params = urllib.parse.urlencode({
            'q': awesome_query,
            'per_page': '5',
            'sort': 'stars',
            'order': 'desc',
        })
        url = f"{self.SEARCH_REPOS_URL}?{params}"
        headers = self._get_headers()

        self._rate_limit()
        raw = _http_get(url, headers=headers, timeout=30, max_retries=1)
        if not raw:
            return []

        data = _json_loads(raw)
        if not data or 'items' not in data:
            return []

        results: List[SearchResult] = []
        for awesome_repo in data['items'][:3]:  # 最多 3 个 awesome 列表
            full_name = awesome_repo.get('full_name', '')
            if not full_name:
                continue

            # 获取 README 内容
            readme_url = f"https://api.github.com/repos/{full_name}/readme"
            readme_headers = self._get_headers()
            readme_headers['Accept'] = 'application/vnd.github.raw+json'

            self._rate_limit()
            readme_raw = _http_get(readme_url, headers=readme_headers, timeout=30, max_retries=1)
            if not readme_raw:
                continue

            readme_text = _decode_html(readme_raw)
            # 提取 GitHub 仓库链接
            import re
            repo_pattern = re.compile(r'https://github\.com/[\w.-]+/[\w.-]+')
            repo_urls = set(repo_pattern.findall(readme_text))

            # 将提取的仓库转为 SearchResult
            for repo_url in list(repo_urls)[:per_bucket]:
                # 排除 awesome 列表本身和非仓库链接
                repo_path = repo_url.replace('https://github.com/', '')
                parts = repo_path.split('/')
                if len(parts) < 2:
                    continue
                repo_full_name = '/'.join(parts[:2])
                if repo_full_name == full_name:
                    continue
                # 排除 GitHub 自身的链接
                if parts[0] in ('github', 'torvalds', 'octocat'):
                    continue

                results.append(SearchResult(
                    title=f"{repo_full_name} (via awesome: {full_name})",
                    url=repo_url,
                    content=f'从 awesome 列表 {full_name} 中发现',
                    source='github-deep-search',
                    score=0.0,
                    engine='github-deep-search',
                    raw={
                        'full_name': repo_full_name,
                        'discovery_method': 'awesome_list',
                        'awesome_source': full_name,
                        # 从 README 里只挖到仓库名，其余字段一概不知道：交给
                        # _attach_missing_metadata 去 /repos 补，补不到就照实留缺字段标记
                        'metadata_missing': True,
                        'repo_type': 'github',
                    },
                ))

        return results

    def get_repo_details(self, full_name: str) -> Optional[Dict]:
        """获取仓库详细信息（用于推荐度评分）"""
        url = self.REPO_URL.format(full_name=full_name)
        headers = self._get_headers()
        self._rate_limit()
        raw = _http_get(url, headers=headers, timeout=30, max_retries=2)
        if not raw:
            return None
        return _json_loads(raw)


# ============================================================
# GitHub 代码搜索引擎
# ============================================================

class GitHubCodeSearchEngine(SearchEngine):
    """
    GitHub 代码搜索引擎（搜索源码中的关键词）

    用于深度调研：搜索特定技术实现、配置示例、API 用法等。
    补充仓库搜索：有时仓库描述不含关键词，但源码中有。

    能力：search, code_search
    数据量：全 GitHub 公开源码
    API Key：可选（GITHUB_TOKEN，代码搜索**必需**认证）
    """

    SEARCH_URL = "https://api.github.com/search/code"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="github-code-search",
            layer=2,
            description="GitHub 代码搜索（源码关键词搜索，补充仓库搜索）",
            requires_config=True,  # 代码搜索需要认证
            config_keys=["GITHUB_TOKEN"],
            is_async_supported=False,
            is_china_friendly=True,
            priority=75,
            capabilities=["search", "code_search"],
        )

    def is_available(self) -> bool:
        """代码搜索需要 GITHUB_TOKEN"""
        return bool(os.environ.get('GITHUB_TOKEN', ''))

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        """
        GitHub 代码搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs:
                language: 代码语言（如 'python'）
                filename: 文件名过滤（如 'package.json'）
                extension: 文件扩展名（如 'py'）
                org: 组织过滤（如 'langchain-ai'）
                user: 用户过滤
        """
        token = os.environ.get('GITHUB_TOKEN', '')
        if not token:
            return None

        q_parts = [query]
        if kwargs.get('language'):
            q_parts.append(f'language:{kwargs["language"]}')
        if kwargs.get('filename'):
            q_parts.append(f'filename:{kwargs["filename"]}')
        if kwargs.get('extension'):
            q_parts.append(f'extension:{kwargs["extension"]}')
        if kwargs.get('org'):
            q_parts.append(f'org:{kwargs["org"]}')
        if kwargs.get('user'):
            q_parts.append(f'user:{kwargs["user"]}')

        q = ' '.join(q_parts)
        params = urllib.parse.urlencode({
            'q': q,
            'per_page': str(min(max_results, 100)),
        })
        url = f"{self.SEARCH_URL}?{params}"
        headers = {
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {token}',
            'X-GitHub-Api-Version': '2022-11-28',
        }

        raw = _http_get(url, headers=headers, timeout=30, max_retries=2)
        if not raw:
            return None

        data = _json_loads(raw)
        if not data or 'items' not in data:
            return None

        results: List[SearchResult] = []
        for item in data['items'][:max_results]:
            repo = item.get('repository', {})
            full_name = repo.get('full_name', '')
            file_path = item.get('path', '')
            html_url = item.get('html_url', '')

            results.append(SearchResult(
                title=f"{full_name}: {file_path}",
                url=html_url,
                content=f'在 {full_name} 仓库中找到代码: {file_path}',
                source='github-code-search',
                score=float(repo.get('stargazers_count', 0)),
                engine='github-code-search',
                raw={
                    'full_name': full_name,
                    'file_path': file_path,
                    'repo_url': repo.get('html_url', ''),
                    'stars': repo.get('stargazers_count', 0),
                },
            ))

        return results   # 取数成功但一条没解析出来＝0 结果，不是通道故障；None 会让断路器把引擎记成不可用
