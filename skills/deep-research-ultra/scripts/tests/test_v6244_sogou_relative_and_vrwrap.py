"""修我上一版引入的回归：相对跳转链接被当成伪链接丢掉了。

实测（本机直连搜狗微信）：10 个 txt-box 结果块都在，块里 h3/a 也都在，
但引擎回 0 条。原因是结果锚点写成 `href="/link?url=dn9a_-gY..."`——**相对路径**，
v6.24.1 那条"链接必须以 http(s):// 开头"的判据把它连同 `javascript:;` 一起丢了。
 javascript 伪链接该丢，真结果的相对跳转不该丢：正确做法是先按当前域名补全再判。

顺带一起修搜狗知乎：它的条目容器是 `<div class="vrwrap">`，
而引擎的块级模式写的是"class 含 results 的 div + 非贪婪到第一个 </div>"——
容器里第一个 </div> 来得很早，切出来的块是空壳，所以永远 0 条。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines import fallback as fb              # noqa: E402
from engines import cn_sources as cn            # noqa: E402

WEIXIN_PAGE = '''
<html><body><div class="news-box"><ul class="news-list">
  <li><div class="txt-box">
    <a class="img" href="/link?url=AAA&amp;type=2"><img src="/icon.png"/></a>
    <div class="info">
      <h3><a target="_blank" href="/link?url=BBB&amp;type=2">RAG 综述第一篇</a></h3>
      <p class="txt-info">这篇综述回顾了检索增强生成的主要路线。</p>
      <div class="s-p"><a class="account" href="/profile?vid=1">某个公众号</a></div>
    </div>
  </div></li>
  <li><div class="txt-box">
    <div class="info">
      <h3><a href="/link?url=CCC&amp;type=2">RAG 综述第二篇</a></h3>
      <p class="txt-info">第二篇的要点。</p>
    </div>
  </div></li>
</ul></div></body></html>
'''.strip()

ZHIHU_PAGE = '''
<html><body><div><div class="results">
  <div class="vrwrap"><div class="struct201102">
    <h3 class="vr-title " vrcid="title.1"><a href="/link?url=ZZZ">知乎上的回答标题</a></h3>
    <div class="vr-content"><p>这段是回答的正文摘要。</p></div>
    <div class="fz-mt space-txt-size">2024-05-01</div>
  </div></div>
  <div class="vrwrap"><div class="struct201102">
    <h3 class="vr-title " vrcid="title.2"><a href="https://www.zhihu.com/question/2">另一个问题</a></h3>
    <div class="vr-content"><p>另一段摘要。</p></div>
  </div></div>
</div></div></body></html>
'''.strip()


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    fb.LAST_HTTP_ERROR = ''
    yield
    fb.LAST_HTTP_ERROR = ''


def _page(html: str) -> bytes:
    from engines.fallback import SERP_MIN_BYTES
    return (html + '<!--' + 'x' * (SERP_MIN_BYTES + 1024) + '-->').encode('utf-8')


def test_weixin_relative_redirect_links_are_results(monkeypatch):
    monkeypatch.setattr(cn, '_http_get', lambda *a, **k: _page(WEIXIN_PAGE))
    got = cn.SogouWeixinEngine().search('retrieval augmented generation', max_results=5) or []
    assert len(got) == 2, f'两条相对跳转结果被当成伪链接丢了：{[r.url for r in got]}'
    assert got[0].title.startswith('RAG 综述第一篇')
    # 相对链接必须补全成可点的绝对地址，否则账本里的来源点不开
    assert got[0].url.startswith('https://weixin.sogou.com/link?url=BBB'), got[0].url


def test_javascript_anchor_is_still_not_a_result(monkeypatch):
    """补全之后仍要挡住伪链接：javascript:; 补出来也还是 javascript:;"""
    html = WEIXIN_PAGE.replace('/link?url=BBB', 'javascript:;')
    monkeypatch.setattr(cn, '_http_get', lambda *a, **k: _page(html))
    got = cn.SogouWeixinEngine().search('q', max_results=5) or []
    assert all('javascript' not in r.url.lower() for r in got), [r.url for r in got]


def test_zhihu_parses_vrwrap_items(monkeypatch):
    monkeypatch.setattr(cn, '_http_get', lambda *a, **k: _page(ZHIHU_PAGE))
    got = cn.SogouZhihuEngine().search('retrieval augmented generation', max_results=5) or []
    assert len(got) == 2, f'vrwrap 条目一条都没解析出来：{[r.title for r in got]}'
    assert got[0].title.startswith('知乎上的回答标题')
    assert got[0].url.startswith('https://'), got[0].url


def test_serp_titles_are_unescaped_before_entering_the_ledger(monkeypatch):
    """实测微信标题原样带着 `&mdash;` 回来——这种字符串会一路进到账本和报告正文里。"""
    html = WEIXIN_PAGE.replace('RAG 综述第一篇', 'RAG 综述&mdash;第一篇 &amp; 应用')
    monkeypatch.setattr(cn, '_http_get', lambda *a, **k: _page(html))
    got = cn.SogouWeixinEngine().search('q', max_results=5) or []
    title = got[0].title
    assert '&mdash;' not in title and '&amp;' not in title, title
    assert '—' in title and '&' in title, title
