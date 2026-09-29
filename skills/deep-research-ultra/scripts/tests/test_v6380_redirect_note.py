"""v6.38.0 回归：仓库改名要在回执里看得见，不能只印终态。

报告 A16（2026-09-29 一轮实跑）：`princeton-nlp/SWE-bench`→`SWE-bench/SWE-bench`、
`All-Hands-AI/OpenHands`→`OpenHands/OpenHands`、`laude-institute/terminal-bench`→
`harbor-framework/terminal-bench-1`；`princeton-nlp/HAL` 今日 404 且无重定向。

GitHub 对改名仓库会直接返回新主人的元数据，所以 `facts.name` 本来就是终态（实测确认）。
缺的是另一半：**Lead 手里那条 URL 还是旧的**。回执只印终态名，旧 URL 就从"已核对"的
错觉里溜进引用清单——报告里点进去 301 一跳还好，像 HAL 那样 404 无重定向的就是死链。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import repo_health as rh  # noqa: E402

META = {'full_name': 'SWE-bench/SWE-bench', 'description': 'd', 'language': 'Python',
        'stargazers_count': 5000, 'forks_count': 10, 'open_issues_count': 2,
        'pushed_at': '2026-09-01T00:00:00Z', 'archived': False,
        'license': {'spdx_id': 'MIT', 'name': 'MIT License'}}


def _fetch(mapping):
    def fetch(url, headers=None):
        for key, val in mapping.items():
            if key in url:
                return 200, val
        return 404, None
    return fetch


def test_rename_is_reported_as_requested_vs_resolved(monkeypatch):
    monkeypatch.setattr(rh, 'fetch_json', _fetch({'/repos/princeton-nlp/SWE-bench': META}))

    h = rh.scan_repo('princeton-nlp/SWE-bench')

    assert h.facts.get('requested') == 'princeton-nlp/SWE-bench', h.facts
    assert h.facts.get('renamed') is True, h.facts
    assert h.facts.get('rename_note'), h.facts


def test_same_name_reports_no_rename(monkeypatch):
    """正向对照：没改名就别硬造一条"已迁移"，噪声会让 Lead 不看备注。"""
    monkeypatch.setattr(rh, 'fetch_json', _fetch({'/repos/SWE-bench/SWE-bench': META}))

    h = rh.scan_repo('SWE-bench/SWE-bench')

    assert h.facts.get('renamed') is False, h.facts
    assert not h.facts.get('rename_note'), h.facts
