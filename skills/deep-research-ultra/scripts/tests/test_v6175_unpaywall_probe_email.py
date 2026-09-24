"""v6.17.5 回归：连通性自检不许用一个会被服务方拒掉的假邮箱。

实测（2026-09-23 那轮 --probe 复测）：UnpaywallEngine.is_available() 写死了
`email=test@example.com`，Unpaywall 对这种地址返回 HTTP 422 —— 于是"引擎今天可不可达"
这个问题，被一个自检自己编出来的坏参数回答成"不可达"。

同一个类里真正干活的 `search_by_doi()` 走 `_get_email()`：
kwargs.email > 环境变量 UNPAYWALL_EMAIL > 默认值 `research@deep-research-ultra.local`，
实测返回 200。两条路对同一个参数用两套值，自检那条还是错的那套。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engines.academic_fulltext as aft  # noqa: E402
from engines.academic_fulltext import UnpaywallEngine  # noqa: E402


def _captured_url(monkeypatch, email_env=None):
    """把 _http_get 换掉，只留请求 URL——不碰网络。"""
    box = {}

    def fake_get(url, **kw):
        box['url'] = url
        return '{}'

    monkeypatch.setattr(aft, '_http_get', fake_get)
    if email_env is None:
        monkeypatch.delenv('UNPAYWALL_EMAIL', raising=False)
    else:
        monkeypatch.setenv('UNPAYWALL_EMAIL', email_env)
    UnpaywallEngine().is_available()
    return box.get('url', '')


def test_default_email_matches_the_real_call_path(monkeypatch):
    """没配环境变量时，自检用的邮箱要和 search_by_doi 用的是同一个。"""
    from urllib.parse import parse_qs, urlparse
    url = _captured_url(monkeypatch)
    real_default = UnpaywallEngine()._get_email()
    assert 'test@example.com' not in url, (
        f'自检仍用写死的假地址，服务方会回 422：{url}')
    sent = parse_qs(urlparse(url).query).get('email', [''])
    assert sent and sent[0] == real_default, (
        f'自检的邮箱({sent!r})与真实调用路径({real_default!r})不是同一个')


def test_env_email_is_honoured_by_the_probe(monkeypatch):
    """配了 UNPAYWALL_EMAIL 就该用它，自检不能绕过配置。"""
    monkeypatch.setenv('UNPAYWALL_EMAIL', 'lead@corp.example.org')
    url = _captured_url(monkeypatch, email_env='lead@corp.example.org')
    assert 'lead%40corp.example.org' in url or 'lead@corp.example.org' in url, \
        f'配置里的邮箱没进自检请求：{url}'


def test_probe_still_uses_a_known_good_doi(monkeypatch):
    """反向保护：别把连通性测试改成不查任何东西的空壳。"""
    url = _captured_url(monkeypatch)
    assert '/10.1038/' in url, f'自检不再拿已知 DOI 探活，等于没测：{url}'
