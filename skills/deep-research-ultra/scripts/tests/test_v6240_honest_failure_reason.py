"""「引擎返回 None」被编成「依赖/服务未就绪」——原因不能靠猜。

实测（v6.23.1 全量 --probe，本机）：12 个不可用源里有 5 个的原因是这句
（sogou-zhihu / baidu-xueshu / duckduckgo / baidu-html / bing-html）。逐个查下来是三个不同问题：

1. baidu-html / bing-html：页面**取回来了**（HTTP 成功），但正则一条没解析出来，
   代码写 `return results if results else None` → 把"解析不出条目"上报成"通道失败"。
   调用链本来就区分 `None`（判引擎不可用、断路器计一次失败）与 `[]`（判 0 结果、计成功），
   是引擎没守住这个契约。
2. duckduckgo：`except Exception: return None` 把异常整个吞掉（本机确实没装 ddgs，
   于是那句猜测恰好"猜对了"——但它是猜，不是测出来的）。
3. probe 自己：前面两条都把原因丢光之后，`_failure_reason` 回落到写死的
   "依赖/服务未就绪"。用户看到这句会去 pip install，而真正的原因可能是反爬页或改版。

修的方向：能测出原因就把原因留下，测不出就照实说"未记录"，不许编。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines import fallback as fb                      # noqa: E402
import probe                                            # noqa: E402

# 百度 SERP 改版后的页面：HTTP 成功、体积也是真页面的量级（实测 0.87M–1.4M 字节），
# 但旧的 RESULT_PATTERN 一条都命中不了
UNPARSEABLE_BODY = ('<html><body><div class="new-layout">'
                    '<span>Something changed on this page</span>'
                    '<div class="footer">' + 'y' * 1_000_000 + '</div>'
                    '</div></body></html>')
UNPARSEABLE_SERP = UNPARSEABLE_BODY.encode('utf-8')
# 反爬页同样是真的取回了一整页（不是几百字节的跳转空壳——那属"通道失败"，见 v6243）
BLOCKED_PAGE = ('<html><head><title>Verify you are human</title></head><body>'
                + 'z' * 1_000_000 + '</body></html>').encode('utf-8')


@pytest.fixture(autouse=True)
def _clear_reason():
    fb.LAST_HTTP_ERROR = ''
    yield
    fb.LAST_HTTP_ERROR = ''


class _Engine:
    """最小的假引擎：没有 _client，也没留下任何 HTTP 失败记录。"""
    def get_name(self):
        return 'mystery'


# ------------------------------------------------ ① 抓到了页面 ≠ 通道失败
@pytest.mark.parametrize('cls', [fb.BaiduHtmlEngine, fb.BingHtmlEngine])
def test_unparseable_page_is_zero_results_not_channel_failure(monkeypatch, cls):
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: UNPARSEABLE_SERP)
    got = cls().search('test query', max_results=5)
    assert got == [], f'页面取回来了却没解析出条目，应报 0 结果而不是 None：{got!r}'


@pytest.mark.parametrize('cls', [fb.BaiduHtmlEngine, fb.BingHtmlEngine])
def test_blocked_page_is_also_a_live_channel(monkeypatch, cls):
    """反爬页同样是"通道活着、这条查询没拿到东西"——报 None 会让人去修网络。"""
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: BLOCKED_PAGE)
    got = cls().search('test query', max_results=5)
    assert got == [], got


@pytest.mark.parametrize('cls', [fb.BaiduHtmlEngine, fb.BingHtmlEngine])
def test_fetch_failure_still_reports_channel_down(monkeypatch, cls):
    """反过来不许糊：真取不到字节时必须回 None，让断路器记失败。"""
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: None)
    assert cls().search('test query', max_results=5) is None


# ------------------------------------------------ ② 吞异常要留下原因
def test_duckduckgo_records_the_swallowed_exception(monkeypatch):
    monkeypatch.setitem(sys.modules, 'ddgs', None)      # from ddgs import ... 必抛 ImportError
    got = fb.DuckDuckGoEngine().search('test query', max_results=5)
    assert got is None
    err = fb.LAST_HTTP_ERROR
    assert err, f'异常被吞了，原因没留下：{err!r}'
    assert 'Error' in err, f'要留下异常类别，让人一眼看出是哪种失败：{err!r}'
    assert 'duckduckgo' in err.lower() or 'ddgs' in err.lower(), \
        f'原因要点名是哪个包缺：{err!r}'


# ------------------------------------------------ ③ 猜不出就照实说猜不出
def test_probe_does_not_invent_a_dependency_reason():
    note_reason = probe._failure_reason(_Engine())
    assert '依赖/服务未就绪' != note_reason, '没有任何证据却断言"依赖/服务未就绪"'
    assert note_reason.startswith('未记录'), \
        f'第一句就该承认没原因，别让人以为已经查出来是缺依赖：{note_reason!r}'


def test_probe_reports_the_real_http_reason_when_present():
    fb.LAST_HTTP_ERROR = 'HTTP 403'
    assert '403' in probe._failure_reason(_Engine())
