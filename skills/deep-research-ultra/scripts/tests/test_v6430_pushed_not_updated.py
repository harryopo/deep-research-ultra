"""v6.42 端到端实跑交回的第二条缺陷：把 GitHub 的 `updated_at` 当成「最近有提交」。

真件取证（本机 2026-09-30，`gh api repos/...`）：

| 仓库 | pushed_at | updated_at |
|------|-----------|------------|
| serenakeyitan/citation-check-skill | 2026-01-26 | 2026-09-28 |
| chrisyangsong/citegate | 2026-08-30 | 2026-09-04 |

`updated_at` 是**仓库元数据**最后被动过的时间（改描述、加 star、调 topic 都会推后它），
不是代码活动时间。引擎却把它印成 `[Updated] 2026-09-28` 摆在结果摘要里，
`recommend._score_maintenance` 又拿它给「维护状态」加分——
于是八个月没有一次提交、且压根没有代码的纯提示词仓库，看起来像昨天刚动过。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.github_deep_search import GitHubDeepSearchEngine  # noqa: E402
from recommend import GitHubRecommender  # noqa: E402

NOW = datetime.now()


def _days_ago(n):
    return (NOW - timedelta(days=n)).strftime('%Y-%m-%dT%H:%M:%SZ')


def _item(**over):
    item = {
        'full_name': 'serenakeyitan/citation-check-skill',
        'name': 'citation-check-skill',
        'html_url': 'https://github.com/serenakeyitan/citation-check-skill',
        'description': 'Citation check skill',
        'stargazers_count': 250, 'forks_count': 17, 'language': None,
        'license': {'spdx_id': 'MIT'}, 'topics': ['claude-code'],
        'created_at': _days_ago(400),
        'updated_at': _days_ago(1),        # 昨天刚动过元数据
        'pushed_at': _days_ago(246),       # 八个月没提交
        'open_issues_count': 3, 'watchers_count': 250, 'archived': False,
        'owner': {'login': 'serenakeyitan'},
    }
    item.update(over)
    return item


def _parse(item):
    return GitHubDeepSearchEngine()._parse_repo(item)


def test_摘要里的活动时间用_pushed_at_不是_updated_at():
    r = _parse(_item())
    assert f"[Pushed] {_days_ago(246)[:10]}" in r.content, r.content
    assert 'Updated' not in r.content, \
        f'pushed_at 已知时不该再把元数据时间当活动时间印出去：{r.content}'


def test_没有_pushed_at_时_updated_at_必须自带限定说明():
    """瘦身对象没有 pushed_at；此时写 updated_at 就得说清它不代表提交。"""
    r = _parse(_item(pushed_at=''))
    assert 'Updated' in r.content, r.content
    assert ('元数据' in r.content and '提交' in r.content), \
        f'少了限定说明就会被读成活动时间：{r.content}'


def test_maintenance_不因元数据变动而加分():
    zombie = GitHubRecommender().score(
        {'full_name': 'a/zombie', 'stars': 250, 'repo_type': 'github',
         'pushed_at': _days_ago(246)[:10], 'updated_at': _days_ago(1)[:10]}, 'x')
    active = GitHubRecommender().score(
        {'full_name': 'a/active', 'stars': 250, 'repo_type': 'github',
         'pushed_at': _days_ago(1)[:10], 'updated_at': _days_ago(1)[:10]}, 'x')
    assert zombie.dimensions['maintenance'] < active.dimensions['maintenance'], \
        (zombie.dimensions, active.dimensions)


def test_只有_updated_at_时维护分照旧给_但不得高于同日的_pushed_at():
    """补不到 pushed_at（瘦身条目）时不能一律给零，但也不能因元数据时间就评成活跃。"""
    only_meta = GitHubRecommender().score(
        {'full_name': 'b/meta', 'stars': 10, 'repo_type': 'github',
         'updated_at': _days_ago(2)[:10]}, 'x')
    fresh_push = GitHubRecommender().score(
        {'full_name': 'b/push', 'stars': 10, 'repo_type': 'github',
         'pushed_at': _days_ago(2)[:10], 'updated_at': _days_ago(2)[:10]}, 'x')
    assert only_meta.dimensions['maintenance'] <= fresh_push.dimensions['maintenance']
