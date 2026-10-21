"""
marketplaces.py — Skill/MCP 市场与 OSS 生态注册表引擎  [v6.101 新增]

起因（用户实测反馈，2026-10-20）：调研「找一个现成的 skill / 开源方案」时
只会从官方渠道找，不会去 skill 市场找 —— **因为来源面上根本没有市场类来源**。
`ENGINE_CHAIN_MAP['opensource']` 里只有 oss-finder(GitHub/GitLab/Gitee/npm/PyPI
的模板) + github-deep-search(仅 GitHub) + gitee + modelscope，市场类一个没有。

先量后写（2026-10-20 逐端点实测，本机网络）：
    市场类
    ✅ skills.sh   GET /api/search?q={q}
                   200 JSON {"skills":[{id, source, skillId, name, installs}],
                             "count": N}（语义搜索；item 无 description 字段，
                             **解析器不假装它有**）
    ✅ smithery    GET https://registry.smithery.ai/servers?q={q}&pageSize={N}
                   200 JSON {"servers":[{qualifiedName, displayName, description,
                             homepage, useCount, verified, …}], "pagination":{…}}
    ❌ glama       401 Unauthorized（要 key）— 不启用
    ❌ mcp.so      read timed out — 不启用
    ⚠️ smithery 页面 URL 无法自证：实测对任意 slug 都回 200 的 SPA 壳
      （bogus slug 也 200，没有 404 可分辨）—— 所以链接一律用 API 自带的
      homepage 字段；homepage 缺失时按实测条目形状拼
      https://smithery.ai/servers/{qualifiedName} 并在 raw 里标注 construct=True
    注册表类
    ✅ npm         GET registry.npmjs.org/-/v1/search?text={q}&size={N}
                   200 {"objects":[{downloads:{monthly}, dependents,
                         package:{name, links:{npm, repository}, description}}]}
                   （dependents 实测有时是字符串有时是整数 —— 解析器按 int 容错）
    ✅ crates.io   GET https://crates.io/api/v1/crates?q={q}&per_page={N}
                   200 {"crates":[{id, name, downloads, description, repository}]}
    ✅ gitlab      GET https://gitlab.com/api/v4/projects?search={q}&per_page={N}
                   200 [()]裸数组 {web_url, star_count, description, …}
    ❌ maven / huggingface  read timed out（本机网络）— 不启用
    ❌ pypi        无官方 JSON 搜索端点 — 不启用

设计约束（沿 platform_engines.py 的既定风格）：
- 纯 JSON API 直连，不解析 HTML；失败返回 None/[]，**编造 = 0**
- 子源相互独立：skills.sh 挂了 smithery 还能用；一个子源挂了不等于引擎死了
- 子源语义分开写死在条 result 里：「没抓到」([]=查无) 与「崩了」(None=端点
  故障) 是两种状态，混写会让断路器把"没抓到"记成引擎不可用
- is_available() 只对**本机可达性**负责（socket 连 443），不打真查询
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

from .base import SearchEngine, EngineMetadata, SearchResult
from .platform_engines import (
    _dedupe,
    _host_reachable,
    _http_get_json,
)

HOST_SKILLS_SH = 'skills.sh'
HOST_SMITHERY = 'registry.smithery.ai'
HOST_NPM = 'registry.npmjs.org'
HOST_CRATES = 'crates.io'
HOST_GITLAB = 'gitlab.com'


def _as_int(value: Any) -> Optional[int]:
    """npm 的 dependents 实测有时是字符串有时是整数 —— 统一按 int 容错。"""
    if value is None or value == '':
        return None
    try:
        return int(str(value).replace(',', ''))        # 实测出现 "129" 与 0 两种
    except (TypeError, ValueError):
        return None


def _interleave(batches: List[List[SearchResult]]) -> List[SearchResult]:
    """多子源结果**轮转合并**，不让先到的子源把后到的挤出厂截断。

    v6.101 第一版是朴素拼接 + 截断：实测「deep research」查回 5 条全是
    skills.sh、smithery 那 1 条被 [:max_results] 吃掉 —— 两个市场里用户
    永远只能看见一个，市场生态本来是我们这次要补的东西。轮转合并后
    两个子源在限额内交替露面，先到不再独占配额。
    """
    out: List[SearchResult] = []
    idx = 0
    while True:
        added = False
        for b in batches:
            if idx < len(b):
                out.append(b[idx])
                added = True
        if not added:
            break
        idx += 1
    return out


class SkillMarketEngine(SearchEngine):
    """Agent Skill / MCP server 市场检索（skills.sh + smithery）。

    这两个是市场聚合站不是官方渠道：skills.sh 聚合全网开源 agent skill
    （带真实安装量），smithery 聚合 MCP 服务器。查询走它们的语义/关键词
    搜索，不依赖安装了哪个 skill，Python 直接执行。
    """

    SEARCH_SKILLS_SH = 'https://skills.sh/api/search'
    SEARCH_SMITHERY = 'https://registry.smithery.ai/servers'

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name='skill-market',
            layer=2,
            description=('skill/MCP 市场检索（skills.sh 安装量排序 + smithery'
                         ' useCount，市场聚合而非官方渠道）'),
            requires_config=False,
            is_china_friendly=True,
            priority=66,            # 深度 GitHub(65) 之后、oss-finder(70) 之前
            capabilities=['search', 'marketplace', 'opensource', 'community'],
        )

    def is_available(self) -> bool:
        """至少一个市场的端口活着就算引擎可用；全挂才如实说不可用。"""
        return (_host_reachable(HOST_SKILLS_SH, timeout=3.0)
                or _host_reachable(HOST_SMITHERY, timeout=3.0))

    def search(self, query: str, max_results: int = 10,
               **kwargs) -> Optional[List[SearchResult]]:
        """两个市场各查一次。

        合成语义（三种状态分开，不混写）：
        - 有子源给出结果  -> 返回结果（子源 failures 只写在 raw 的 channel_note）
        - 全部子源都是查询连不上/崩 -> None（通道级故障，交给断路器降级）
        - 全部子源都正常返回但 0 条   -> []（市场里真的没有，不是故障）
        """
        note: List[str] = []
        batches: List[List[SearchResult]] = []
        exploded: int = 0
        for fetch in (self._skills_sh, self._smithery):
            try:
                part = fetch(query, max_results)
            except Exception as exc:                       # noqa: BLE001
                note.append(f'{fetch.__name__}: {exc.__class__.__name__}')
                exploded += 1
                continue
            if part is None:
                note.append(f'{fetch.__name__}: 端点无响应/解析失败')
                exploded += 1
            else:
                batches.append(part)
                if not part:
                    note.append(f'{fetch.__name__}: 查无结果')

        if exploded == 2 and not batches:
            return None          # 两个市场都崩 → 通道级失败，让上层降级
        out = _dedupe(_interleave(batches))[:max_results]
        for r in out:
            if note:
                r.raw['channel_note'] = '；'.join(note)
        return out

    # ------------------------------------------------------------------ #
    # 子源 1：skills.sh（Agent Skill 市场）

    def _skills_sh(self, query: str, max_results: int) -> Optional[List[SearchResult]]:
        url = (f'{self.SEARCH_SKILLS_SH}?'
               f'q={urllib.parse.quote(str(query).strip()[:300])}')
        data = _http_get_json(url)
        if data is None:
            return None
        items = data.get('skills') if isinstance(data, dict) else []
        out: List[SearchResult] = []
        for it in list(items or [])[:max_results]:
            if not isinstance(it, dict):
                continue
            source = str(it.get('source') or '')           # "owner/repo"
            skill_id = str(it.get('skillId') or it.get('name') or '')
            if not skill_id:
                continue
            installs = _as_int(it.get('installs'))
            # URL 用实测形状：/{source}/{skillId}（2026-10-20 实测 200 且命中内容）
            page = f'https://skills.sh/{source}/{skill_id}' if source else ''
            if not page:
                continue
            parts = [f'来源仓库 github.com/{source}']
            if installs is not None:
                parts.append(f'安装量(installs) {installs}')
            out.append(SearchResult(
                title=f'{skill_id}（skills.sh）',
                url=page,
                # 搜索端点没有 description 字段（实测形状），**不假装有摘要**
                content='[Market] skills.sh（Agent Skill 市场）'
                        + ('；' + '；'.join(parts) if parts else ''),
                source='skill-market',
                score=float(installs) if installs is not None else 0.0,
                engine='skill-market',
                raw={'marketplace': 'skills.sh', 'source': source,
                     'skillId': skill_id,
                     'github_repo': f'https://github.com/{source}' or None,
                     'installs': installs},
            ))
        return out

    # ------------------------------------------------------------------ #
    # 子源 2：smithery（MCP 服务器市场）

    def _smithery(self, query: str, max_results: int) -> Optional[List[SearchResult]]:
        url = (f'{self.SEARCH_SMITHERY}?'
               f'q={urllib.parse.quote(str(query).strip()[:300])}'
               f'&pageSize={min(int(max_results), 25)}')
        data = _http_get_json(url)
        if data is None:
            return None
        items = (data.get('servers') or []) if isinstance(data, dict) else []
        out: List[SearchResult] = []
        for it in list(items)[:max_results]:
            if not isinstance(it, dict):
                continue
            qname = str(it.get('qualifiedName') or '')
            if not qname:
                continue
            homepage = str(it.get('homepage') or '')
            if homepage:
                landing, flag = homepage, False
            else:
                # 平台自证字段缺失才构造；smithery 对任意 slug 都回 200 SPA 壳
                # （实测），构造链接**无法自证**，所以 raw 里必须标注。
                landing = f'https://smithery.ai/servers/{qname}'
                flag = True
            parts = []
            if it.get('description'):
                parts.append(str(it['description'])[:300])
            if _as_int(it.get('useCount')) is not None:
                parts.append(f'useCount {it.get("useCount")}')
            if it.get('verified'):
                parts.append('verified')
            if flag:
                parts.append('（链接为构造值：smithery 无 404 可分辨）')
            out.append(SearchResult(
                title=it.get('displayName') or qname,
                url=landing,
                content='[Market] smithery（MCP 市场）'
                        + ('；' + '；'.join(parts) if parts else ''),
                source='skill-market',
                score=float(_as_int(it.get('useCount')) or 0.0),
                engine='skill-market',
                raw={'marketplace': 'smithery', 'qualifiedName': qname,
                     'homepage': homepage or None,
                     'useCount': _as_int(it.get('useCount')),
                     'verified': bool(it.get('verified')),
                     'constructed_url': flag},
            ))
        return out


class OssRegistryEngine(SearchEngine):
    """OSS 生态注册表检索（npm + crates.io + GitLab，全部免 key）。

    与 github-deep-search 的分工：不是替代，是补 GitHub 之外的生态位 ——
    npm（JS 生态 + 真实下载量/被依赖数）、crates.io（Rust）、GitLab
    （GitHub 之外的自托管开源栈）。包注册表给的是**下载量**这种 GitHub
    star 看不到的真实使用信号。
    """

    SEARCH_NPM = 'https://registry.npmjs.org/-/v1/search'
    SEARCH_CRATES = 'https://crates.io/api/v1/crates'
    SEARCH_GITLAB = 'https://gitlab.com/api/v4/projects'

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name='oss-registry',
            layer=2,
            description=('npm/crates/GitLab 注册表搜索（GitHub 之外的生态 + '
                         '真实下载量信号）'),
            requires_config=False,
            is_china_friendly=True,
            priority=68,
            capabilities=['search', 'opensource'],
        )

    def is_available(self) -> bool:
        """任一注册表主机活着就算引擎可用；全挂才如实说不可用。

        第一版只探测 npm —— npm 被墙而 crates.io/GitLab 活着时会误报
        「引擎不可用」，把两个能用的源也排除掉（is_available=False 会让
        引擎整支被排除，这是 d025 的语义）。改为任一可达即 True。
        """
        for host in (HOST_NPM, HOST_CRATES, HOST_GITLAB):
            if _host_reachable(host, timeout=3.0):
                return True
        return False

    def search(self, query: str, max_results: int = 10,
               **kwargs) -> Optional[List[SearchResult]]:
        note: List[str] = []
        batches: List[List[SearchResult]] = []
        exploded = 0
        for fetch in (self._npm, self._crates, self._gitlab):
            try:
                part = fetch(query, max_results)
            except Exception as exc:                       # noqa: BLE001
                note.append(f'{fetch.__name__}: {exc.__class__.__name__}')
                exploded += 1
                continue
            if part is None:
                note.append(f'{fetch.__name__}: 端点无响应/解析失败')
                exploded += 1
            else:
                batches.append(part)
        if exploded == 3 and not batches:
            return None
        out = _dedupe(_interleave(batches))[:max_results]
        for r in out:
            if note:
                r.raw['channel_note'] = '；'.join(note)
        return out

    # ------------------------------------------------------------------ #
    # 子源 1：npm registry

    def _npm(self, query: str, max_results: int) -> Optional[List[SearchResult]]:
        url = (f'{self.SEARCH_NPM}?text={urllib.parse.quote(str(query).strip()[:200])}'
               f'&size={min(int(max_results), 20)}')
        data = _http_get_json(url)
        if data is None:
            return None
        out: List[SearchResult] = []
        for o in list((data.get('objects') or []))[:max_results]:
            pkg = o.get('package') if isinstance(o, dict) else None
            if not isinstance(pkg, dict):
                continue
            name = str(pkg.get('name') or '')
            if not name:
                continue
            links = pkg.get('links') if isinstance(pkg.get('links'), dict) else {}
            landing = str(links.get('npm') or '') or \
                f'https://www.npmjs.com/package/{name}'
            stats = o.get('downloads') if isinstance(o.get('downloads'), dict) else {}
            monthly = _as_int(stats.get('monthly'))
            deps = _as_int(o.get('dependents'))
            parts = []
            if pkg.get('description'):
                parts.append(str(pkg['description'])[:260])
            if monthly is not None:
                parts.append(f'[月下载] {monthly}')
            if deps is not None:
                parts.append(f'[被依赖数] {deps}')
            if pkg.get('version'):
                parts.append(f'v{pkg["version"]}')
            repo = str(links.get('repository') or '')
            # npm 的 repository 实测是 "git+https://github.com/x/y.git" 形状 ——
            # 规范化成可直接打开的 https 链接（仍是 API 原值，只去协议前后缀）
            if repo.startswith('git+'):
                repo = repo[4:]
            if repo.endswith('.git'):
                repo = repo[:-4]
            out.append(SearchResult(
                title=f'{name} (npm)',
                url=landing,
                content='[Registry] npm' + ('；' + '；'.join(parts) if parts else ''),
                source='oss-registry',
                score=float(monthly) if monthly is not None else 0.0,
                engine='oss-registry',
                raw={'registry': 'npm', 'name': name,
                     'monthly_downloads': monthly, 'dependents': deps,
                     'version': pkg.get('version') or None,
                     'github_repo': repo or None},
            ))
        return out

    # ------------------------------------------------------------------ #
    # 子源 2：crates.io

    def _crates(self, query: str, max_results: int) -> Optional[List[SearchResult]]:
        url = (f'{self.SEARCH_CRATES}?q={urllib.parse.quote(str(query).strip()[:200])}'
               f'&per_page={min(int(max_results), 20)}')
        data = _http_get_json(url)
        if data is None:
            return None
        out: List[SearchResult] = []
        for it in list((data.get('crates') or []))[:max_results]:
            if not isinstance(it, dict):
                continue
            cid = str(it.get('id') or '')
            if not cid:
                continue
            parts = []
            if it.get('description'):
                parts.append(str(it['description'])[:260])
            if _as_int(it.get('downloads')) is not None:
                parts.append(f'[总下载] {it.get("downloads")}')
            repo = str(it.get('repository') or '') or None
            out.append(SearchResult(
                title=f'{cid} (crates.io)',
                # crates.io 的规范 slug URL：实测条目含 id；下方 raw 注明认知来源
                url=f'https://crates.io/crates/{cid}',
                content='[Registry] crates.io' + ('；' + '；'.join(parts) if parts else ''),
                source='oss-registry',
                score=float(_as_int(it.get('downloads')) or 0.0),
                engine='oss-registry',
                raw={'registry': 'crates.io', 'name': cid,
                     'downloads': _as_int(it.get('downloads')),
                     'description': it.get('description') or None,
                     'github_repo': repo},
            ))
        return out

    # ------------------------------------------------------------------ #
    # 子源 3：GitLab（免 key 项目搜索）

    def _gitlab(self, query: str, max_results: int) -> Optional[List[SearchResult]]:
        data = _http_get_json(
            f'{self.SEARCH_GITLAB}?search={urllib.parse.quote(str(query).strip()[:200])}'
            f'&per_page={min(int(max_results), 20)}'
            f'&order_by=name&sort=asc')
        if data is None:
            return None
        items = data if isinstance(data, list) else (data.get('items') or [])
        out: List[SearchResult] = []
        for it in list(items)[:max_results]:
            if not isinstance(it, dict):
                continue
            web = str(it.get('web_url') or '')
            if not web:
                continue
            parts = []
            if it.get('description'):
                parts.append(str(it['description'])[:260])
            if _as_int(it.get('star_count')) is not None:
                parts.append(f'[Stars] {it.get("star_count")}')
            if it.get('last_activity_at'):
                parts.append(f'[Last activity] {str(it["last_activity_at"])[:10]}')
            out.append(SearchResult(
                title=it.get('name_with_namespace') or it.get('name') or web,
                url=web,                       # API 自证字段
                content='[Registry] GitLab' + ('；' + '；'.join(parts) if parts else ''),
                source='oss-registry',
                score=float(_as_int(it.get('star_count')) or 0.0),
                engine='oss-registry',
                raw={'registry': 'gitlab',
                     'star_count': _as_int(it.get('star_count')),
                     'last_activity': it.get('last_activity_at') or None},
            ))
        return out
