"""SERP 解析必须丢掉非 http 的链接：`javascript:;` 不是结果。

实测（2026-09-25，本机直连百度 SERP）：baidu-html 五条结果里第一条是
title='手写'、url='javascript:;'——页面模板里的一个交互锚点被当成搜索结果。
这类条目进了账本就是"某条论断的来源是一个 javascript 伪链接"，
比 0 结果糟得多：0 结果会被判"这个源今天没用"，垃圾条目却会被当成证据用下去。

必应同理（它的结果块里也有站内功能锚点）。修法是一条判据：链接必须以 http(s):// 开头。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines import fallback as fb                      # noqa: E402

BAIDU_FIXTURE = '''
<div class="result c-container new-pmd" id="1">
  <a href="javascript:;" class="c-showurl">手写</a>
</div>
<div class="result c-container new-pmd" id="2">
  <h3 class="t"><a href="http://www.baidu.com/link?url=AbCdEf" target="_blank">
     Retrieval-Augmented Generation for Large Language Models: A Survey</a></h3>
  <span class="content-right_2s-H4">综述回顾了 RAG 范式</span>
</div>
<div class="result c-container new-pmd" id="3">
  <a href="/s?wd=javascript%3A">站内占位</a>
  <a href="https://arxiv.org/abs/2312.10997">RAG 论文原文</a>
</div>
<div id="content_bottom">footer</div>
'''.strip()

BING_FIXTURE = '''
<ol id="b_results">
  <li class="b_algo"><link rel="stylesheet" href="/rp/a.css"/>
    <h2 class=""><a href="javascript:void(0)">反馈</a></h2><p>占位</p></li>
  <li class="b_algo"><h2 class=""><a href="https://arxiv.org/abs/2312.10997">
      RAG survey</a></h2><p>摘要</p></li>
</ol>
'''.strip()


def _page(html: str) -> bytes:
    """夹具要撑到真页面的量级（百万级字节），否则会被"空壳页"判据先拦掉——那是另一条测试。"""
    from engines.fallback import SERP_MIN_BYTES
    return (html + '<!--' + 'x' * (SERP_MIN_BYTES + 1024) + '-->').encode('utf-8')


@pytest.mark.parametrize('cls,fixture,expect_url', [
    (fb.BaiduHtmlEngine, BAIDU_FIXTURE, 'http://www.baidu.com/link?url=AbCdEf'),
    (fb.BingHtmlEngine, BING_FIXTURE, 'https://arxiv.org/abs/2312.10997'),
])
def test_non_http_anchors_are_not_results(monkeypatch, cls, fixture, expect_url):
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: _page(fixture))
    got = cls().search('retrieval augmented generation', max_results=5) or []
    urls = [r.url for r in got]
    assert all(u.startswith('http') for u in urls), f'伪链接被当成结果：{urls}'
    assert not any('javascript' in u.lower() for u in urls), urls
    assert expect_url in urls, f'真结果被一起丢了：{urls}'


def test_baidu_keeps_only_the_real_result_rows(monkeypatch):
    """百度那条 /s?wd=... 站内链接也不该混进来（它是搜索页自身，不是外部来源）。"""
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: _page(BAIDU_FIXTURE))
    urls = [r.url for r in fb.BaiduHtmlEngine().search('q', max_results=5) or []]
    assert all('baidu.com/link?url=' in u or 'arxiv.org' in u for u in urls), urls
    assert not any(u.startswith('/s?') for u in urls), urls
