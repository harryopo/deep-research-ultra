"""X-D11 回归：仓库健康扫描要把「限流/无权限」和「仓库真有问题」分开。

起因（另一次 effort=deep 实跑交回的清单）：repo_health 把所有 HTTP 失败压成一个
`_get_json → None`，然后一律写 high 风险「官方 API 不可达或仓库不存在（事实无法核实）」。
匿名 GitHub API 只有 60 次/小时，一次深跑很容易撞 403/429——于是一个活跃仓库被判成
高风险，报告里读起来还像那么回事。限流是我们的问题，不是仓库的问题。
"""

from __future__ import annotations

import repo_health as rh
from repo_health import RepoHealth, scan_repo

OK_PAYLOAD = {
    'full_name': 'fastapi/fastapi',
    'description': 'Fast API framework',
    'language': 'Python',
    'stargazers_count': 7000,
    'forks_count': 100,
    'open_issues_count': 5,
    'pushed_at': '2026-09-01T00:00:00Z',
    'archived': False,
    'license': {'spdx_id': 'MIT'},
}


def _fake(result):
    """把 fetch_json 换成固定返回，并记下调用头。"""
    calls = []

    def fetch(url, headers=None):
        calls.append({'url': url, 'headers': headers or {}})
        return result
    return fetch, calls


# ---------------------------------------------------------------------------
# 三态判定
# ---------------------------------------------------------------------------

def test_rate_limited_is_not_a_repo_risk(monkeypatch):
    fetch, _ = _fake((429, None))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    h = scan_repo('fastapi/fastapi')
    assert h.verdict == 'rate_limited'
    assert h.overall() == 'unknown'          # 没查到 ≠ 有风险
    assert not any(r['category'] in ('maintenance', 'api_unavailable') for r in h.risks)


def test_forbidden_is_reported_as_its_own_state(monkeypatch):
    fetch, _ = _fake((403, None))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    h = scan_repo('fastapi/fastapi')
    assert h.verdict == 'forbidden'
    assert h.overall() == 'unknown'


def test_not_found_is_a_real_conclusion(monkeypatch):
    """404 是仓库自己的事实：该判高风险，不能和限流混成"未核实"。"""
    fetch, _ = _fake((404, None))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    h = scan_repo('no-such-owner/no-such-repo')
    assert h.verdict == 'not_found'
    assert h.overall() == 'high'
    assert any(r['category'] == 'not_found' for r in h.risks)


def test_network_failure_is_unreachable(monkeypatch):
    fetch, _ = _fake((0, None))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    h = scan_repo('fastapi/fastapi')
    assert h.verdict == 'unreachable'
    assert h.overall() == 'unknown'


def test_200_still_produces_facts(monkeypatch):
    fetch, _ = _fake((200, OK_PAYLOAD))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    h = scan_repo('fastapi/fastapi')
    assert h.verdict == 'ok'
    assert h.api_ok is True
    assert h.facts['stars'] == 7000
    assert h.facts['license'] == 'MIT'


# ---------------------------------------------------------------------------
# 认证与限额
# ---------------------------------------------------------------------------

def test_github_token_is_actually_sent(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_test123')
    fetch, calls = _fake((200, OK_PAYLOAD))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    scan_repo('fastapi/fastapi')
    assert calls[0]['headers'].get('Authorization') == 'Bearer ghp_test123'


def test_without_token_the_scan_is_marked_anonymous(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    fetch, calls = _fake((200, OK_PAYLOAD))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    h = scan_repo('fastapi/fastapi')
    assert h.anonymous is True
    assert 'Authorization' not in calls[0]['headers']


def test_gitee_does_not_leak_the_github_token(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_test123')
    fetch, calls = _fake((200, OK_PAYLOAD))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    scan_repo('https://gitee.com/oschina/git-osc')
    assert 'Authorization' not in calls[0]['headers']


# ---------------------------------------------------------------------------
# 输出：未核实要说人话，且不许冒充结论
# ---------------------------------------------------------------------------

def test_markdown_says_unverified_and_gives_the_fix(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    fetch, _ = _fake((403, None))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    md = rh.build_markdown(scan_repo('fastapi/fastapi'))
    assert '未核实' in md
    assert 'GITHUB_TOKEN' in md                  # 缺配置就给配法，别只说"无法核实"
    assert 'Star' not in md                      # 没拿到事实就不摆事实表


def test_cli_exits_nonzero_when_nothing_was_verified(monkeypatch, capsys):
    fetch, _ = _fake((429, None))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    assert rh._main(['fastapi/fastapi']) != 0


def test_cli_exits_zero_on_a_real_scan(monkeypatch):
    fetch, _ = _fake((200, OK_PAYLOAD))
    monkeypatch.setattr(rh, 'fetch_json', fetch)
    assert rh._main(['fastapi/fastapi']) == 0
