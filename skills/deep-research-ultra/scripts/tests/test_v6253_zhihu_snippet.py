"""v6.25.3 回归：搜狗知乎的摘要取错了节点——统计行与点赞数被当成正文。

实测来源（本机 2026-09-25，查询词「大模型 智能体 检索增强」，页面 364 KB / 9 个条目，
副本存在 .research/gate-check/zhihu-real.html）：

- 真摘要在两种节点上：`<p class="star-wiki ">`（百科式条目）与
  `<div class="fz-mid space-txt base-ellipsis …">`（普通条目）
- `<p class="fz-mid space-txt text-lightgray">` 是**灰色统计行**
  （`274个回答 - 2145人关注 - 97.2万次浏览`），`fz-mid space-txt` 前缀与真摘要同款，
  只有 `text-lightgray` 能分开
- `star-wiki` 里还套着 `<span class="zan-box">686</span>`（点赞数）与
  `<em><!--red_beg-->检索增强<!--red_end--></em>`（搜狗的高亮标记注释）
- 旧实现取"条目块里第一个 `<p>`"，于是：统计行被当成正文入库；`star-wiki`/`div` 形态的真摘要
  整个错过。实测 5 条结果里 3 条摘要为空、1 条只有统计行。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import fallback as fb         # noqa: E402  （空壳页阈值要引用同一个常量）
from engines import cn_sources as cn   # noqa: E402  （_http_get 是 from-import 进来的，要打这一层的名字）
from engines.cn_sources import SogouZhihuEngine  # noqa: E402

ZHIHU_FIXTURE = '''
<div class="vrwrap">
  <h3 class="vr-title "><a href="/link?url=AAA" name="vs_f">什么是RAG：检索增强生成详解</a></h3>
  <p class="fz-mid space-txt text-lightgray" vrsid="otherLayoutP1.d787b89">274个回答 - 2145人关注 - 97.2万次浏览</p>
  <div class="img-flex " id="component_x"></div>
</div>
<div class="vrwrap">
  <h3 class="vr-title "><a href="/link?url=BBB" name="vs_f">大模型智能体 Agent 综述</a></h3>
  <p class="star-wiki " vrcid="baike.0a7c670"><span class="zan-box">686</span>
    ”RAG的尽头是Agent” —— RAG(<em><!--red_beg-->检索增强<!--red_end--></em>生成)是近期几个
    <em><!--red_beg-->大模型<!--red_end--></em>应用方向上最难下笔的一个,技术方案仍在快速迭代...
  </p>
  <span class="cite-date">2024-09-25</span>
</div>
<div class="vrwrap">
  <h3 class="vr-title "><a href="/link?url=CCC" name="vs_f">动态知识补充与检索增强</a></h3>
  <div class="fz-mid space-txt base-ellipsis cla-hide">为了解决这个问题，可以想到能否动态地将知识补充给大模型，
    使其能够回答更多问题呢？这就要提到检索增强的生成模型（RAG）</div>
  <span class="cite-date">2023-11-25</span>
</div>
<!-- ResultListViewEnd -->
'''.strip()


@pytest.fixture()
def results(monkeypatch):
    # 真 SERP 页面是百万级，小 fixture 会被 _stub_page 判成通道失败，所以要垫到阈值以上
    page = (ZHIHU_FIXTURE + '<!--' + 'x' * (fb.SERP_MIN_BYTES + 1024) + '-->').encode('utf-8')
    monkeypatch.setattr(cn, '_http_get', lambda *a, **k: page)
    return SogouZhihuEngine().search('大模型 智能体 检索增强', max_results=10) or []


def test_统计行不当摘要(results):
    """`274个回答 - 2145人关注` 是灰色统计行，进账本就是假证据。"""
    for r in results:
        assert '个回答' not in r.content and '次浏览' not in r.content, r.content


def test_真摘要取得到(results):
    by_url = {r.url.rsplit('=', 1)[-1]: r for r in results}
    assert '检索增强的生成模型' in by_url['CCC'].content, by_url['CCC'].content
    assert 'RAG的尽头是Agent' in by_url['BBB'].content, by_url['BBB'].content


def test_点赞数与高亮标记不混进摘要(results):
    by_url = {r.url.rsplit('=', 1)[-1]: r for r in results}
    wiki = by_url['BBB'].content
    assert 'zan-box' not in wiki and 'red_beg' not in wiki and '<' not in wiki, wiki
    assert not wiki.lstrip().startswith('686'), wiki


def test_三条都还在(results):
    """取摘要的改动不许把条目弄丢（标题锚点是相对路径，补全后仍是真结果）。"""
    assert len(results) == 3, [r.title for r in results]
