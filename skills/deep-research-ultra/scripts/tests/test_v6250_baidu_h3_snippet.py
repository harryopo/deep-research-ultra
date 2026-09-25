"""v6.25.0 回归：百度 SERP 改用哈希 class 后，按 div class="result…" 切块会漏结果、摘要全空。

实测来源（本机 2026-09-25，查询词「检索增强生成 RAG」，页面 1.13 MB）：

- 页面里真结果锚点是 8 个 `<h3 …><a href="http://www.baidu.com/link?url=…">`，
  旧路径只解析出 7 条——丢的那条容器 class 不以 `result` 开头（如百科卡片），
  旧 RESULT_PATTERN 只认 `class="result…"` 的 div，整块根本没被看见
- 20 个 `class="result…"` 的 div 里 8 个是 `result-molecule`（结果内的「相关搜索」子链接），
  它们贡献的是 `javascript:;` 与 `/s?wd=…` 两种伪链接
- 摘要两条正则（`content-right_`、`c-abstract`）**整页 0 命中**，摘要节点换成了
  `summary-text_15QGa` / `cos-line-clamp-2` 这类带构建哈希的 class
  → 解析出的 7 条结果 content 全为 0 字
- 后果可量化：`score.py` 的 `_score_accuracy(content='…')` 在 content 为空时直接回 30 分地板，
  `_score_relevance` 少掉 30% 的内容覆盖度分量——国内源因此更容易被判成噪声
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import fallback as fb


def _page(html: str) -> bytes:
    """补到空壳页阈值以上——真 SERP 页面是百万级，小 fixture 会被判成通道失败。"""
    from engines.fallback import SERP_MIN_BYTES
    return (html + '<!--' + 'x' * (SERP_MIN_BYTES + 1024) + '-->').encode('utf-8')


# 结构照抄实测页面：百科卡片的容器 class 不以 result 开头（实测 8 个真结果锚点里有 1 个
# 不在 class="result…" 的块内，旧路径因此只出 7 条）、摘要 class 带构建哈希、夹 molecule 噪声块
BAIDU_REAL_SHAPE = '''
<div id="content_left">
  <div id="content_left_inner">
    <div class="c-container new-pmd xbc-container">
      <div class="main-wrap">
        <h3 class="t _sc-title_10ku5_63 kg-title_a60kU tts-b-hl">
          <a href="http://www.baidu.com/link?url=AAA111" class="sc-link">检索增强生成(大模型前沿技术之一) - 百度百科</a>
        </h3>
        <div class="_paragraph_10ku5_2 md summary-text_15QGa cos-line-clamp-2">
          检索增强生成（RAG）把外部文档库当作证据&mdash;&mdash;生成前先检索，再把命中片段喂给模型
        </div>
      </div>
    </div>
  </div>
  <div class="result c-container xpath-log new-pmd">
    <h3 class="c-title t">
      <a href="http://www.baidu.com/link?url=BBB222">RAG(检索增强生成)技术全解析:2026年最新进展与落地实践-腾讯云</a>
    </h3>
    <span class="cos-color-text-tiny summary-gap_68jXq">
      <div class="summary-text_2AbcD cos-line-clamp-2">分块、编码、索引、微调四步落地，2026 年主流做法与踩坑清单</div>
    </span>
    <div class="result-molecule  new-pmd">
      <a href="javascript:;">手写</a>
      <a href="/s?wd=%E7%B4%A2%E5%BC%95&#x26;usm=4">索引</a>
    </div>
  </div>
  <div class="result c-container new-pmd">
    <h3 class="cosc-title cos-link t title_4QsBx">
      <a href="http://www.baidu.com/link?url=CCC333">从零开始学RAG:大模型检索增强生成技术教程!-CSDN博客</a>
    </h3>
    <div class="source-container-pc_6R70n">
      <div class="summary-text_9Zzz9 cos-line-clamp-2">从零搭建检索链路：向量库选型、召回重排与评测</div>
    </div>
  </div>
  <div id="content_bottom">
    <div class="footer"><p>百度反馈&nbsp;Help&nbsp;搜索&nbsp;设置&nbsp;用户反馈&nbsp;投诉&nbsp;版权&nbsp;联系电话&nbsp;更多相关内容入口集合页脚区域</p></div>
  </div>
</div>
'''.strip()


@pytest.fixture()
def results(monkeypatch):
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: _page(BAIDU_REAL_SHAPE))
    return fb.BaiduHtmlEngine().search('检索增强生成 RAG', max_results=10) or []


def test_每条真结果都被解析出来(results):
    """旧路径 8 条只出 7 条（class 不以 result 开头的卡片整块看不见），这里 3 条一条不许丢。"""
    urls = [r.url for r in results]
    assert urls == ['http://www.baidu.com/link?url=AAA111',
                    'http://www.baidu.com/link?url=BBB222',
                    'http://www.baidu.com/link?url=CCC333'], urls


def test_摘要不再是空的(results):
    """实测 7/7 条 content 为 0 字：摘要 class 带构建哈希，按名字写死的正则必然再次失效。"""
    for r in results:
        assert len(r.content or '') >= 10, f'{r.title[:20]!r} 摘要仍是空的：{r.content!r}'
    assert '外部文档库' in results[0].content
    assert '向量库选型' in results[2].content


def test_摘要里去掉了标签与实体(results):
    """摘要要能直接进账本：不许带标签残片，`&mdash;` 这类实体要解成字符。"""
    for r in results:
        assert '<' not in r.content and '>' not in r.content, r.content
    assert '&mdash;' not in results[0].content
    assert '—' in results[0].content


def test_伪链接与相关搜索子链接不进结果(results):
    """molecule 块里的 `javascript:;` 和 `/s?wd=` 是站内搜索壳，不是外部来源。"""
    for r in results:
        assert r.url.startswith('http://www.baidu.com/link?url='), r.url


def test_最后一条不会把页脚当摘要(results):
    """摘要窗口要有界：末条结果后面紧跟页脚，窗口不收口就会把页脚长句当成它的摘要。"""
    last = results[-1]
    assert '用户反馈' not in last.content and '页脚区域' not in last.content, last.content


def test_页面注释不混进摘要(monkeypatch):
    """实测复测（风控解除后的真页面，2026-09-25）：有一条结果的摘要开头是

    `<!--s-data:{"styles":{"struct-source":…` ——页面把结构化数据写成 HTML 注释塞在结果块里，
    注释被摘要窗口截断时收尾的 `>` 落在窗口外，`<[^>]+>` 这种"去标签"根本匹配不上，
    整段 JSON 就当成正文进了摘要，一路能进账本。
    """
    dangling = ('<!--s-data:{"styles":{"struct-source":{"color":"#222"},"struct-title":'
                '{"font-weight":"bold"}' + ',{"x":1}' * 900)   # 没有 -->，`>` 也一个没有
    # 塞进最后一条结果的窗口内（真页面就是这种位置：结果块内部的结构化数据注释）
    html = BAIDU_REAL_SHAPE.replace(
        '<div class="source-container-pc_6R70n">',
        dangling + '\n<div class="source-container-pc_6R70n">', 1)
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: _page(html))
    got = fb.BaiduHtmlEngine().search('检索增强生成 RAG', max_results=10) or []
    assert len(got) == 3, got
    for r in got:
        assert 's-data' not in r.content and '{' not in r.content, r.content[:80]
    assert '分块、编码' in got[1].content, got[1].content


def test_残缺标签不当摘要(monkeypatch):
    """同一次真页面复测里还有两条长这样：

    `<div data-module="abstract" data-click="{"clk_info…`、`<span class="cos-space-mr-3xs…`
    ——机制是 `_text_of()` 先删标签、**后**解实体：百度把摘要卡片整段以 `&lt;div …&gt;` 的转义形态
    写在页面里，实体一解就把标签原样吐回正文，再被"最长行"选中当成摘要。
    判据：解完实体还要再过一遍去标签，仍带 `<` 的候选行不是正文，不许当摘要。
    """
    escaped = ('&lt;div data-module="abstract" data-click="{"clk_info":{"srcid":259494},'
               'fc_vec":"1"},"tpl":"vrdata"}' )   # 整行没有 &gt;：真页面就是被窗口截断在这行中间
    html = BAIDU_REAL_SHAPE.replace(
        '从零搭建检索链路：向量库选型、召回重排与评测',
        escaped + '\n从零搭建检索链路：向量库选型、召回重排与评测')
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: _page(html))
    got = fb.BaiduHtmlEngine().search('检索增强生成 RAG', max_results=10) or []
    for r in got:
        assert '<' not in r.content and 'data-module' not in r.content, r.content[:80]
    assert '向量库选型' in got[-1].content, got[-1].content


def test_通道失败仍然返回_none(monkeypatch):
    """契约不变：空壳页（风控/需验证）仍判通道失败，不许退成 0 结果。"""
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: b'<html>OK</html>')
    assert fb.BaiduHtmlEngine().search('检索增强生成 RAG') is None


def test_改版预警仍能数出百度的结果块(monkeypatch):
    """check_serp_patterns 靠引擎的块正则数「页面有几块」，换成正则锚点后不许退成 None。"""
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: _page(BAIDU_REAL_SHAPE))
    import check_serp_patterns as chk
    spec = next(s for s in chk.SPECS if s['name'] == 'baidu-html')
    row = chk.check_one(spec, '检索增强生成 RAG')
    assert row['blocks'] == 3, row
    assert row['results'] == 3, row
