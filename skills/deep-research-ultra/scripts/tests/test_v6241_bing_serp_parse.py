"""必应 SERP 解析：标题模式必须容忍 h2 上的属性与块内注入的 <link> 簇。

实测（2026-09-25，本机直连 cn.bing.com）：
- RESULT_PATTERN 能切出 10 个 `li class="b_algo"` 结果块；
- TITLE_PATTERN 却 0/10 命中，因为引擎写的是 `<h2><a ...>`，而页面现在是 `<h2 class=""><a ...>`；
- 而且每个结果块开头插了一串 `<link rel="stylesheet">`（Bing 的按块内联样式），
  所以锚点前还有别的标签，模式不能假设"块一开头就是 h2"。

结果就是引擎明明取到了满页结果，却回 0 条——在 v6.24.0 之前这还会被说成"引擎不可用"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines import fallback as fb                      # noqa: E402

# 从真实页面缩出来的两条结果：块内先有 <link> 簇，h2 带 class
BING_FIXTURE = '''
<ol id="b_results" class="">
  <li class="b_algo" data-id iid=SERP.5334>
    <link rel="stylesheet" href="/rp/abc.br.css" type="text/css"/>
    <link rel="stylesheet" href="/rp/def.br.css" type="text/css"/>
    <h2 class=""><a href="https://arxiv.org/abs/2312.10997" h="ID=SERP,51">
      Retrieval-Augmented Generation for Large Language Models: A Survey</a></h2>
    <div class="b_twi">
      <p class="b_lineclamp2">This survey reviews retrieval-augmented generation techniques.</p>
    </div>
  </li>
  <li class="b_algo" data-id iid=SERP.5335>
    <link rel="stylesheet" href="/rp/ghi.br.css" type="text/css"/>
    <h2 class=""><a href="https://github.com/langchain-ai/langchain" h="ID=SERP,52">langchain-ai/langchain</a></h2>
    <div><p>The LangChain framework.</p></div>
  </li>
</ol>
'''

# 老版标记（h2 无属性）：改了不许把旧形状弄丢
BING_LEGACY_FIXTURE = '''
<ol id="b_results">
  <li class="b_algo"><h2><a href="https://example.com/one">第一条结果</a></h2>
      <p>摘要一</p></li>
</ol>
'''


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: BING_FIXTURE.encode('utf-8'))


def test_bing_parses_results_from_current_markup():
    got = fb.BingHtmlEngine().search('retrieval augmented generation', max_results=5)
    assert got and len(got) == 2, f'页面里有两条结果，一条都没解析出来：{got!r}'
    assert got[0].url == 'https://arxiv.org/abs/2312.10997'
    assert 'Retrieval-Augmented Generation' in got[0].title
    assert got[1].url.endswith('langchain')


def test_bing_title_is_clean_of_entities_and_tags():
    got = fb.BingHtmlEngine().search('q', max_results=5)
    assert '<' not in got[0].title and '\n' not in got[0].title.strip(), repr(got[0].title)


def test_bing_still_parses_legacy_markup(monkeypatch):
    monkeypatch.setattr(fb, '_http_get',
                        lambda *a, **k: BING_LEGACY_FIXTURE.encode('utf-8'))
    got = fb.BingHtmlEngine().search('q', max_results=5)
    assert got and got[0].title == '第一条结果', got
