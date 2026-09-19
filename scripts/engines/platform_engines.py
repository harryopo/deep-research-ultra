"""
platform_engines.py — 国内开源平台引擎（Gitee / ModelScope）  [v6.1 新增]

- GiteeEngine：Gitee 仓库搜索（`gitee.com/api/v5/search/repositories`，v5 搜索端点需 access_token，
  匿名请求实测静默返回 []，故 requires_config=True / 需 GITEE_TOKEN）
- ModelScopeEngine：魔搭模型卡详情查询（`/api/v1/models/{Path}/{Name}`；公开关键词搜索端点
  实测已 404，故不声明 search 能力）

设计约束：
- 纯 JSON API 直连（不解析 HTML，避免反爬脆弱性），失败返回 None / 空列表
- 解析多字段容错（Gitee 兼容裸数组与 items[]/rows[] 包装）
- 与 SearchEngine 基类契约一致，注册进 Layer 2（Skill+平台层）
"""

from __future__ import annotations

import json
import os
import socket
import urllib.request
import urllib.parse
from typing import Any, Dict, List, Optional

from .base import SearchEngine, EngineMetadata, SearchResult

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

TIMEOUT = 8.0


def _host_reachable(host: str, port: int = 443, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _http_get_json(url: str) -> Optional[Any]:
    """GET JSON（urllib，UA 伪装，超时，容错）。"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _UA, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8', errors='ignore'))
    except Exception:
        return None


def _dedupe(results: List[SearchResult]) -> List[SearchResult]:
    seen = set()
    out = []
    for r in results:
        if r.url not in seen:
            seen.add(r.url)
            out.append(r)
    return out


class GiteeEngine(SearchEngine):
    """Gitee 仓库搜索（免费公开 API，国内主力代码平台）。"""

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name='gitee',
            layer=2,
            description='Gitee 仓库搜索（v5 搜索端点需 access_token）',
            requires_config=True,
            config_keys=['GITEE_TOKEN'],
            is_china_friendly=True,
            priority=70,
            capabilities=['search', 'opensource'],
        )

    def is_available(self) -> bool:
        """无 token 时 Gitee 搜索端点静默返回 []（实测），等于拿不到数据 —— 如实标为不可用。"""
        return bool(os.environ.get('GITEE_TOKEN')) and _host_reachable('gitee.com')

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        token = os.environ.get('GITEE_TOKEN', '')
        if not token:
            return None
        q = urllib.parse.quote(query)
        url = (f'https://gitee.com/api/v5/search/repositories?q={q}'
               f'&per_page={max_results}&sort=best_match&access_token={urllib.parse.quote(token)}')
        data = _http_get_json(url)
        if data is None:
            return None
        # v6.3 修复：Gitee v5 实测返回裸数组（无 items/rows 包装）；
        # 兼容 dict（items/rows）与 list 两种契约
        if isinstance(data, list):
            items = data
        else:
            items = data.get('items') or data.get('rows') or []
        out: List[SearchResult] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            out.append(SearchResult(
                title=it.get('full_name') or it.get('name') or '',
                url=it.get('html_url') or it.get('url') or '',
                content=it.get('description') or '',
                source='gitee',
                published_date=it.get('pushed_at') or '',
                author=it.get('owner', {}).get('login', '') if isinstance(it.get('owner'), dict) else '',
                engine='gitee',
                raw={'stars': it.get('stargazers_count'),
                     'language': it.get('language'),
                     'forks': it.get('forks_count')},
            ))
        return _dedupe(out)


class ModelScopeEngine(SearchEngine):
    """魔搭社区（ModelScope）模型卡详情查询。

    v6.5 能力收缩：公开 API 只有模型详情端点（GET /api/v1/models/{Path}/{Name}，
    实测 200），v6.1 依赖的 dolphin 列表/搜索端点已 404（实测），因此不再声明
    search 能力，只按精确 model id 取模型卡，供开源六维质量门的「合规安全」取证。
    """

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name='modelscope',
            layer=2,
            description='魔搭模型卡详情（精确 model id → 许可证/下载量/任务）',
            requires_config=False,
            is_china_friendly=True,
            priority=72,
            capabilities=['lookup', 'opensource', 'model'],
        )

    def is_available(self) -> bool:
        return _host_reachable('modelscope.cn')

    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[List[SearchResult]]:
        model_id = (query or '').strip()
        if '/' not in model_id:
            return []          # 无关键词搜索端点：如实返回空，不编造结果
        data = _http_get_json(
            f'https://modelscope.cn/api/v1/models/{urllib.parse.quote(model_id)}')
        if data is None:
            return None
        item = data.get('Data') if isinstance(data, dict) else None
        if not isinstance(item, dict) or not (item.get('Name') or item.get('Path')):
            return []          # 200 但查无此模型
        path = str(item.get('Path') or '')
        full = f"{path}/{item.get('Name')}" if path else str(item.get('Name'))
        name = str(item.get('ChineseName') or item.get('Name') or '')
        license_ = str(item.get('License') or item.get('license') or '')
        desc = str(item.get('Description') or item.get('description') or '')
        return _dedupe([SearchResult(
            title=name or full,
            url=f'https://modelscope.cn/models/{full}',
            content=(f'许可证: {license_}；' if license_ else '') + desc[:300],
            source='modelscope',
            published_date=str(item.get('LastUpdatedTime') or ''),
            author=path,
            engine='modelscope',
            raw={'downloads': item.get('Downloads'), 'license': license_,
                 'tasks': item.get('Tasks')},
        )])