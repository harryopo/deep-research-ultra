"""v6.38.0 回归：许可证字段 NOASSERTION 不是结论，必须回读 LICENSE 本体。

报告 A17（2026-09-29 一轮实跑，4 例）：GitHub 的 `license.spdx_id` 给 `NOASSERTION` 时，
本体往往是明确的许可——`vercel/ai` 本体纯 Apache-2.0、`openai/evals` 本体逐字 MIT、
`neo4j-graphrag-python` 本体 Apache-2.0+PSF；`modelcontextprotocol/typescript-sdk` 更极端，
本体已从 MIT 迁到 Apache-2.0 而 npm 发布件的 package.json 仍标 MIT。

旧实现只用字段值：`license_spdx = lic.get('spdx_id')` → 判 `license_risk('NOASSERTION')`
→ 直接写进结论。字段说什么就印什么，等于把"GitHub 没识别出来"当成"这个件的许可是别的"。

判据补齐：字段是 NOASSERTION/空/"Other" 时强制二次取本体（`/repos/{o}/{r}/license` 会带回
识别到的那个文件与内容），按本体文本重新判级，并把"字段值 / 本体判定 / 本体 URL"三项一起落账；
本体取不到就写"许可证未证实"，不许把 NOASSERTION 当许可名抄进报告。
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import repo_health as rh  # noqa: E402

MIT_BODY = ("MIT License\n\nCopyright (c) 2024 OpenAI\n\nPermission is hereby granted, "
            "free of charge, to any person obtaining a copy of this software...")
APACHE_BODY = ("                                 Apache License\n\n"
               "                           Version 2.0, January 2004\n"
               "      http://www.apache.org/licenses/\n\n   TERMS AND CONDITIONS FOR USE, "
               "REPRODUCTION, and distribution...")
GPL_BODY = ("                    GNU GENERAL PUBLIC LICENSE\n\n"
            "                       Version 3, 29 June 2007\n"
            " Copyright (C) 2007 Free Software Foundation, Inc.")


def _payload(text: str, path: str = 'LICENSE') -> dict:
    return {'name': path, 'path': path,
           'url': f'https://api.github.com/repos/o/r/contents/{path}',
           'download_url': f'https://raw.githubusercontent.com/o/r/main/{path}',
           'license': {'spdx_id': 'NOASSERTION'},
           'content': base64.b64encode(text.encode('utf-8')).decode('ascii')}


def _fake_fetch(mapping):
    calls = []

    def fetch(url, headers=None):
        calls.append(url)
        for key, val in mapping.items():
            if key in url:
                return 200, val
        return 404, None
    fetch.calls = calls
    return fetch


def _mapping(body):
    return {'/repos/o/r/license': _payload(body),
            '/repos/o/r': {'full_name': 'o/r', 'description': 'd', 'language': 'Python',
                           'stargazers_count': 10, 'forks_count': 1, 'open_issues_count': 0,
                           'pushed_at': '2026-09-01T00:00:00Z', 'archived': False,
                           'license': {'spdx_id': 'NOASSERTION', 'name': 'Other'}}}


def test_noassertion_field_is_replaced_by_the_body(monkeypatch):
    """字段 NOASSERTION + 本体 Apache-2.0 → 结论按本体走，并留下本体 URL。"""
    monkeypatch.setattr(rh, 'fetch_json', _fake_fetch(_mapping(APACHE_BODY)))

    h = rh.scan_repo('o/r')

    f = h.facts
    assert 'Apache-2.0' in str(f.get('license_effective')), f
    assert f.get('license_body_url', '').startswith('https://'), f
    assert f.get('license_field') == 'NOASSERTION', f


def test_mit_body_is_read_as_mit(monkeypatch):
    monkeypatch.setattr(rh, 'fetch_json', _fake_fetch(_mapping(MIT_BODY)))

    h = rh.scan_repo('o/r')

    assert 'MIT' in str(h.facts.get('license_effective')), h.facts


def test_gpl_body_raises_the_copyleft_level(monkeypatch):
    """判级要跟着本体变：GPL 本体不能因为字段是 NOASSERTION 就免掉传染性告警。"""
    monkeypatch.setattr(rh, 'fetch_json', _fake_fetch(_mapping(GPL_BODY)))

    h = rh.scan_repo('o/r')

    assert 'GPL-3.0' in str(h.facts.get('license_effective')), h.facts
    assert any(r['category'] == 'license' and r['level'] == 'high' for r in h.risks), h.risks


def test_unreadable_body_says_unproven_not_noassertion(monkeypatch):
    """本体取不到时写"未证实"，不许把 NOASSERTION 当许可名抄进报告。"""
    monkeypatch.setattr(rh, 'fetch_json', _fake_fetch({
        '/repos/o/r': _mapping('')['/repos/o/r'],   # 仓库元数据有，license 端点 404
    }))

    h = rh.scan_repo('o/r')

    note = str(h.facts.get('license_note', ''))
    assert '未证实' in note, h.facts
    assert rh.license_risk('NOASSERTION')[0] != 'low'


def test_clean_spdx_field_does_not_fetch_the_body(monkeypatch):
    """正向对照 + 成本闸：字段本来就是 MIT 时不多打一次请求。"""
    fetch = _fake_fetch({'/repos/o/r': {
        'full_name': 'o/r', 'description': 'd', 'language': 'Python',
        'stargazers_count': 10, 'forks_count': 1, 'open_issues_count': 0,
        'pushed_at': '2026-09-01T00:00:00Z', 'archived': False,
        'license': {'spdx_id': 'MIT', 'name': 'MIT License'}}})
    monkeypatch.setattr(rh, 'fetch_json', fetch)

    rh.scan_repo('o/r')

    assert not any('/license' in u for u in fetch.calls), fetch.calls
