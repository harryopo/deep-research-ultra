"""v6.26.0 回归：github-deep-search 的字段完整度。

实测来源（本机 2026-09-25，查询词「vector database」，直连 GitHub API）：

1. **编造零值**：`_search_dependents` 走的是 code search 端点，它的 `items[].repository`
   是**瘦身对象**——没有 stargazers_count / forks_count / pushed_at / license / topics。
   旧代码用 `.get(..., 0)` 兜底，于是把"不知道"写成了"0"：
   实测 `baidubce/app-builder` 报 ⭐0（真实 586）、`prompt-security/ps-fuzz` 报 ⭐0（真实 713），
   而 `[Stars] 0` 与 `[Updated] ` 会一路进报告。
2. **深度挖掘必然被截光**：`search(deep=True)` 先跑 4 个分桶填满配额，挖掘结果排在后面，
   最后 `all_results[:max_results]` 一刀切。实测 deep=True 在 max_results=8 与 20 下
   返回的 8/8、20/20 条**全是分桶结果**，而 `_search_awesome` 单独调用能出 10 条、
   `_search_dependents` 能出 5 条——请求发了、结果扔了。
   另外 awesome 挖掘被写在 `if deep and seed_repos:` 里，不传种子时整段不跑。
3. **详情补全从未发生**：`get_repo_details()` 的 docstring 写着"用于推荐度评分"，
   但全仓库（除测试外）**没有任何调用点**——所以 awesome 发现的条目带着 3 个 raw 键
   就进了 `recommend.GitHubRecommender`，popularity/activity/maintenance 全按 0 评。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import github_deep_search as gds  # noqa: E402
from engines.github_deep_search import GitHubDeepSearchEngine  # noqa: E402

DETAILS = {           # /repos/nl/two 的真实形态（含 code search 里拿不到的字段）
    'full_name': 'nl/two', 'name': 'two', 'html_url': 'https://github.com/nl/two',
    'description': '向量检索库', 'stargazers_count': 5323, 'forks_count': 402,
    'language': 'Python', 'license': {'spdx_id': 'Apache-2.0'}, 'topics': ['rag'],
    'created_at': '2021-03-01T00:00:00Z', 'updated_at': '2026-09-01T00:00:00Z',
    'pushed_at': '2026-09-20T00:00:00Z', 'open_issues_count': 31,
    'watchers_count': 5323, 'archived': False, 'owner': {'login': 'nl'},
}
BUCKET_ITEM = dict(DETAILS, full_name='nl/one', name='one',
                   html_url='https://github.com/nl/one', stargazers_count=900,
                   watchers_count=900)
AWESOME_README = (b'# Awesome\n- [two](https://github.com/nl/two)\n'
                  b'- [three](https://github.com/nl/three)\n')


class _Api:
    """按 URL 分派的假 GitHub API；同时记下打过哪些请求，用于断言"有没有去补详情"。"""

    def __init__(self, details_ok=True):
        self.calls = []
        self.details_ok = details_ok

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith('/readme'):
            return AWESOME_README
        if url.startswith(GitHubDeepSearchEngine.SEARCH_CODE_URL):
            # code search 的 repository 对象就是没有 stars 这些字段——照实模拟
            return json.dumps({'items': [{
                'repository': {'full_name': 'corp/app-builder', 'name': 'app-builder',
                               'html_url': 'https://github.com/corp/app-builder',
                               'description': '平台', 'owner': {'login': 'corp'}}}]}).encode()
        if url.startswith('https://api.github.com/repos/'):
            # /repos/{full_name} 只该回那一个仓库：别的条目补不到详情，走"照实标注"那条路
            if url.endswith('/repos/nl/two') and self.details_ok:
                return json.dumps(DETAILS).encode()
            return None
        if 'awesome' in url:
            return json.dumps({'items': [{'full_name': 'nl/awesome-vdb'}]}).encode()
        # 分桶一次就给满 8 条：旧行为下这会把配额填满，挖掘结果排在后面被 [:max_results] 截光
        items = [dict(BUCKET_ITEM, full_name=f'nl/one' if i == 0 else f'nl/b{i}',
                      name='one' if i == 0 else f'b{i}',
                      html_url=('https://github.com/nl/one' if i == 0
                                else f'https://github.com/nl/b{i}'))
                 for i in range(8)]
        return json.dumps({'items': items}).encode()


@pytest.fixture()
def engine(monkeypatch):
    def _patch(api):
        monkeypatch.setattr(gds, '_http_get', api)
        # 限速器是生产约束（匿名 6 秒/请求），不是这里的被测行为
        monkeypatch.setattr(gds.time, 'sleep', lambda *a: None)
        return GitHubDeepSearchEngine()
    return _patch


def test_不知道的字段不许写成零(engine):
    """code search 的瘦身响应里没 stargazers_count → 不许输出 ⭐0 与 [Stars] 0。"""
    eng = engine(_Api())
    r = eng._parse_repo({'full_name': 'corp/app-builder',
                         'html_url': 'https://github.com/corp/app-builder'})
    assert '⭐' not in r.title, r.title
    assert '[Stars]' not in r.content, r.content
    assert 'stars' not in r.raw, r.raw
    assert r.raw.get('metadata_missing') is True, r.raw


def test_依赖挖掘不编造元数据(engine):
    eng = engine(_Api())
    got = eng._search_dependents(['nl/seed'], per_bucket=5)
    assert got, '依赖挖掘应至少出一条'
    assert '⭐' not in got[0].title, got[0].title
    assert got[0].raw.get('metadata_missing') is True, got[0].raw


def test_deep_无种子也要跑_awesome_挖掘(engine):
    api = _Api()
    eng = engine(api)
    rs = eng.search('vector database', max_results=8, deep=True) or []
    assert any('awesome' in u for u in api.calls), 'deep=True 却没去搜 awesome 列表'
    assert any(r.raw.get('discovery_method') == 'awesome_list' for r in rs), \
        [r.raw.get('discovery_method') for r in rs]


def test_挖掘结果不被配额截光(engine):
    api = _Api()
    eng = engine(api)
    rs = eng.search('vector database', max_results=8, deep=True) or []
    # 桩里只有 5 个不同的分桶仓库（每桶返回同一批），所以满配额是 5 分桶 + 2 挖掘 = 7
    assert len(rs) == 7, [r.raw.get('full_name') for r in rs]
    found = [r for r in rs if r.raw.get('discovery_method')]
    assert found, '深度挖掘的结果一条都没留下（旧行为：填满配额后被 [:max_results] 截光）'


def test_挖掘条目会补全元数据(engine):
    """awesome 发现的 nl/two 应当去 /repos 补详情，把真实 star 数带回来。"""
    api = _Api()
    eng = engine(api)
    rs = eng.search('vector database', max_results=8, deep=True) or []
    two = next((r for r in rs if r.raw.get('full_name') == 'nl/two'), None)
    assert two, [r.raw.get('full_name') for r in rs]
    assert any(u.endswith('/repos/nl/two') for u in api.calls), '没去补详情'
    assert '⭐5323' in two.title, two.title
    assert two.raw['stars'] == 5323 and two.raw['pushed_at'] == '2026-09-20', two.raw
    assert two.raw.get('metadata_missing') is not True, two.raw
    assert '[License] Apache-2.0' in two.content, two.content


def test_补不到详情就照实标注(engine):
    api = _Api(details_ok=False)
    eng = engine(api)
    rs = eng.search('vector database', max_results=8, deep=True) or []
    two = next((r for r in rs if r.raw.get('full_name') == 'nl/two'), None)
    assert two, [r.raw.get('full_name') for r in rs]
    assert '⭐' not in two.title and '5323' not in two.content, two.title
    assert two.raw.get('metadata_missing') is True, two.raw


def test_缺元数据不许被说成零星死项目():
    """补不到详情时分数仍按缺项计（这是机械口径），但**结论话术不许说成"零星/不活跃"**——
    实测这种条目里就有真实 586 星的 app-builder。"""
    from recommend import GitHubRecommender
    rec = GitHubRecommender().score({'full_name': 'corp/app-builder', 'repo_type': 'github',
                                     'metadata_missing': True}, 'vector database')
    assert '未取到' in rec.recommendation_reason, rec.recommendation_reason
    assert '活跃度较低' not in rec.recommendation_reason, rec.recommendation_reason


def test_字段齐全的条目照旧评(engine):
    from recommend import GitHubRecommender
    rec = GitHubRecommender().score({'full_name': 'nl/two', 'stars': 5323,
                                     'pushed_at': '2026-09-20'}, 'vector database')
    assert '未取到' not in rec.recommendation_reason, rec.recommendation_reason
    assert rec.total_score > 0


def test_分桶条目的字段照旧完整(engine):
    """补全逻辑不许把原本就有数据的分桶结果弄坏。"""
    api = _Api()
    eng = engine(api)
    rs = eng.search('vector database', max_results=8, deep=True) or []
    one = next(r for r in rs if r.raw.get('full_name') == 'nl/one')
    assert one.raw['stars'] == 900 and one.raw['pushed_at'] == '2026-09-20', one.raw
    assert not any(u.endswith('/repos/nl/one') for u in api.calls), '已有完整字段还去补＝白烧配额'
