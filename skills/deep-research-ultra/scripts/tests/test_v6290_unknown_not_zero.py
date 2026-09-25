"""v6.29.0 回归：「没取到这个字段」在报告与分组里不许写成 0。

v6.26.0/v6.27.0 把引擎层与打分层的编造零值收住了，但下游两处还在继续编：

1. `GitHubCodeSearchEngine.search` 的 `items[].repository` 是瘦身对象——本机
   `gh api search/code` 实测回 50 个键，里面**没有 stargazers_count**（有 stargazers_url
   但没有计数）。旧写法 `repo.get('stargazers_count', 0)` 把每条代码命中都写成 ⭐0，
   并带着这个 0 进推荐度表、进 niche 分组（表头写着「⭐ < 100」）。
2. `recommend.GitHubRecommender.score` 用 `repo_data.get('stars', 0)` 分组，
   于是「star 未知」被判成 niche＝「小众项目（⭐ < 100，可借鉴）」——一句没有依据的话。
3. `report.py` 推荐度表把 stars 与引用数直接印进单元格：缺项时印 "0"，
   读者读到的是「这个项目 0 star / 这篇论文 0 引用」。

对照面（必须保住，防止把修复做成"一律显示未取到"）：真实为 0 的 star 与真实为 0 的
引用数仍要照实印 0。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import github_deep_search as gds  # noqa: E402
from engines.base import SearchResult  # noqa: E402
from engines.github_deep_search import GitHubCodeSearchEngine  # noqa: E402
from recommend import GitHubRecommender, PaperRecommender  # noqa: E402
from report import ReportGenerator  # noqa: E402

# gh api "search/code?q=..." 的 items[0] 实测形态：repository 子对象没有 stargazers_count
CODE_SEARCH_ITEM = {
    'name': 'rag.py', 'path': 'app/rag.py',
    'html_url': 'https://github.com/corp/app-builder/blob/main/app/rag.py',
    'repository': {
        'id': 1, 'node_id': 'R_kg', 'name': 'app-builder', 'full_name': 'corp/app-builder',
        'private': False, 'owner': {'login': 'corp', 'id': 2},
        'description': '平台', 'fork': False,
        'url': 'https://api.github.com/repos/corp/app-builder',
        'html_url': 'https://github.com/corp/app-builder',
        'archive_url': 'https://api.github.com/repos/corp/app-builder/{archive_format}{/ref}',
        'forks_url': 'https://api.github.com/repos/corp/app-builder/forks',
        'stargazers_url': 'https://api.github.com/repos/corp/app-builder/stargazers',
        'created_at': '2021-01-01T00:00:00Z', 'updated_at': '2026-09-01T00:00:00Z',
        'pushed_at': '2026-09-20T00:00:00Z', 'size': 1024, 'forks_count': 12,
    },
}
REPO_DETAILS = {
    'id': 1, 'name': 'app-builder', 'full_name': 'corp/app-builder',
    'html_url': 'https://github.com/corp/app-builder', 'description': '平台',
    'stargazers_count': 586, 'forks_count': 12, 'watchers_count': 586,
    'open_issues_count': 3, 'language': 'Python', 'license': None, 'topics': [],
    'created_at': '2021-01-01T00:00:00Z', 'updated_at': '2026-09-01T00:00:00Z',
    'pushed_at': '2026-09-20T00:00:00Z', 'archived': False, 'owner': {'login': 'corp'},
}


@pytest.fixture()
def code_results(monkeypatch):
    """拿实测形态的 code search 响应跑一次 GitHubCodeSearchEngine.search。"""
    monkeypatch.setenv('GITHUB_TOKEN', 't')

    def _fake(url, **kwargs):
        if url.startswith(GitHubCodeSearchEngine.SEARCH_URL):
            return json.dumps({'items': [CODE_SEARCH_ITEM]}).encode('utf-8')
        return None

    monkeypatch.setattr(gds, '_http_get', _fake)
    return GitHubCodeSearchEngine().search('retrieval augmented', max_results=5) or []


# ---------------------------------------------------------------------------
# ① 引擎侧：code search 不许把「没有这个字段」写成 0
# ---------------------------------------------------------------------------

def test_code_search_不编造_star(code_results):
    raw = code_results[0].raw
    assert raw.get('stars') is None, f"未知 star 被写成 {raw.get('stars')!r}"
    assert raw.get('metadata_missing') is True


def test_code_search_仍标成_github_仓库(code_results):
    """去掉编造的 0 之后，这条命中还得能进推荐度表——不能因为没 stars 就整个消失。"""
    assert code_results[0].raw.get('repo_type') == 'github'


# ---------------------------------------------------------------------------
# ② 打分侧：star 未知不许归入「小众项目 ⭐ < 100」
# ---------------------------------------------------------------------------

def test_未知_star_不落入_niche_分组():
    rec = GitHubRecommender().score(
        {'full_name': 'corp/app-builder', 'repo_type': 'github', 'metadata_missing': True})
    assert rec.group != 'niche', '把"没取到"归进"⭐<100（可借鉴）"是没有依据的判断'
    assert rec.group == 'unknown'


def test_真实低星仍归_niche():
    """对照面：修复不许把真实的低星也一并推成"未知"。"""
    rec = GitHubRecommender().score({'full_name': 'a/b', 'repo_type': 'github', 'stars': 12})
    assert rec.group == 'niche'


def test_真实零星仍归_niche_且分组不缺键():
    rec = GitHubRecommender().score({'full_name': 'a/b', 'repo_type': 'github', 'stars': 0})
    assert rec.group == 'niche'


def test_rank_results_认得_unknown_组():
    rows = [
        SearchResult(title='r1', url='https://github.com/a/b', content='x',
                     source='github-deep-search',
                     raw={'full_name': 'a/b', 'repo_type': 'github', 'stars': 5000}),
        SearchResult(title='r2', url='https://github.com/c/d', content='x',
                     source='github-code-search',
                     raw={'full_name': 'c/d', 'repo_type': 'github', 'metadata_missing': True}),
    ]
    ranked = GitHubRecommender().rank_results(rows)
    assert len(ranked) == 2, '未知元数据的行被静默丢掉'
    assert [i['recommendation'].group for i in ranked] == ['flagship', 'unknown']


# ---------------------------------------------------------------------------
# ③ 报告侧：缺项印「未取到」，真实 0 照印 0
# ---------------------------------------------------------------------------

def _github_html(rows):
    ranked = GitHubRecommender().rank_results(rows, '', 'default')
    return ReportGenerator()._render_github_recommendations(ranked, 'default')


def _paper_html(rows):
    ranked = PaperRecommender().rank_results(rows, '')
    return ReportGenerator()._render_paper_recommendations(ranked)


def test_报告_star_缺项不印_zero():
    rows = [SearchResult(
        title='corp/app-builder: rag.py', url='https://github.com/corp/app-builder',
        content='x', source='github-code-search',
        raw={'full_name': 'corp/app-builder', 'repo_type': 'github',
             'metadata_missing': True})]
    out = _github_html(rows)
    assert '<td>未取到</td>' in out
    assert '⭐0' not in out and '<td>0</td>' not in out
    assert '⭐ < 100（可借鉴）' not in out, '不许给未知行套上"小众项目"的星级断言'


def test_报告_star_真实_zero_照印():
    """该发生的必须真发生：0 星要印 0，不能一律"未取到"。"""
    rows = [SearchResult(
        title='a/b', url='https://github.com/a/b', content='x', source='github-deep-search',
        raw={'full_name': 'a/b', 'repo_type': 'github', 'stars': 0, 'forks': 0})]
    out = _github_html(rows)
    assert '<td>0</td>' in out
    assert '<td>未取到</td>' not in out


def test_报告_引用数缺项不印_zero():
    rows = [SearchResult(
        title='某论文', url='https://pubmed.example/1', content='x', source='pubmed',
        raw={'title': '某论文', 'abstract': 'x' * 80, 'venue': ''})]
    out = _paper_html(rows)
    assert '<td>未提供</td>' in out
    assert '<td>0</td>' not in out


def test_报告_引用数真实_zero_照印():
    rows = [SearchResult(
        title='某论文', url='https://s2.example/1', content='x', source='semantic-scholar',
        raw={'title': '某论文', 'abstract': 'x' * 80, 'citation_count': 0})]
    out = _paper_html(rows)
    assert '<td>未提供</td>' not in out
    assert '<td>0</td>' in out
