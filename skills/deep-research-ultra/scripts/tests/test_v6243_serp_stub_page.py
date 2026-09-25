"""SERP 拿到空壳页（几百字节）时，要说"被风控"，不许报"这个查询 0 结果"。

实测（本机连续跑 baidu-html 五次）：返回字节数依次是
1136856 / 925038 / 870379 / 1438 / …——真 SERP 页面是百万级字节，最后那次只有 1.4 KB，
里面连一个 `<h3>`、一个 `link?url=` 都没有。这是百度对这个客户端降级成空壳页（风控/待验证）。

现在这条路径的后果：`_http_get` 拿到 200 和 1.4 KB → 引擎解析出 0 条 →
`--probe` 报"⚠️ 可调通但 0 结果（查询词无命中，或端点契约变更/需授权）"，
调研里则表现为"百度今天对这个主题没东西"。都不对：这一发根本没拿到可解析的页面，
该按通道失败处理并写明是空壳页。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines import fallback as fb                      # noqa: E402
from engines import cn_sources as cn                    # noqa: E402

# 真实被降级时的样子：一个几百字节的跳转/校验外壳，没有任何结果结构
STUB_PAGE = (b'<html><head><meta http-equiv="refresh" content="0;url=/error.html">'
             b'</head><body>find something</body></html>')


@pytest.fixture(autouse=True)
def _clear():
    fb.LAST_HTTP_ERROR = ''
    yield
    fb.LAST_HTTP_ERROR = ''


@pytest.mark.parametrize('cls', [fb.BaiduHtmlEngine, fb.BingHtmlEngine,
                                 cn.BaiduSerpEngine, cn.SogouWeixinEngine,
                                 cn.SogouZhihuEngine, cn.BaiduXueshuEngine])
def test_stub_page_is_reported_as_channel_failure_not_zero_results(monkeypatch, cls):
    # cn_sources 里 `_http_get` 是 import 进来的自有绑定，两处都得打（只打一处会漏）
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: STUB_PAGE)
    monkeypatch.setattr(cn, '_http_get', lambda *a, **k: STUB_PAGE)
    got = cls().search('retrieval augmented generation', max_results=5)
    assert got is None, f'1.4KB 空壳页不该报成"取到了但没结果"：{got!r}'
    err = fb.LAST_HTTP_ERROR
    assert '空壳' in err or '风控' in err, f'要说得出是被降级了：{err!r}'
    assert str(len(STUB_PAGE)) in err, f'要把字节数报出来，便于和真页面（百万级）对照：{err!r}'


def test_floor_is_below_any_real_serp_page():
    """真实 SERP 页面实测 0.9M–1.4M 字节，阈值只要远低于它就不会误杀正常页。"""
    assert 1438 < fb.SERP_MIN_BYTES <= 50_000
