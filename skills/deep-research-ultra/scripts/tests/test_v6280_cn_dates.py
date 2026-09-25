"""v6.28.0 回归：国内源的摘要与日期。

实测来源（本机 2026-09-25，查询词「大模型 私有化部署 成本」，逐源单发、间隔 5 秒）：

| 源 | published_date | 摘要 | 时效维 |
|----|--------------|------|--------|
| baidu-serp | 0/5 | **0/5** | 全是 40.0 地板 |
| sogou-weixin | 0/5 | 5/5 | 全是 40.0 |
| sogou-zhihu | 0/5 | 5/5 | 全是 40.0 |
| bing-html | 0/5 | 5/5 | 4 条 40.0 |
| baidu-html | 0/3 | 3/3 | 2 条 90（日期恰好被写进摘要才救回来） |

两条根因：
1. `BaiduSerpEngine._parse_baidu_results` 用的还是 v6.25 已证明整页 0 命中的
   `content-right_` / `c-abstract` 两条正则；而且它把标题列表和摘要列表**按位置配对**
   （`snippets[i]`），一条没有摘要就会让后面全部错位——第 N+1 条的摘要会挂到第 N 条标题上。
2. 页面把日期写在结果块里（`2025年9月19日…`、`<span class="cite-date">2024-12-10</span>`、
   `3天前`），没人取进 `published_date`；`score._score_currency` 只能从 content 里兜底抓绝对日期，
   相对日期（天前/小时前/昨天）抓不到 → 时效维落 40 分地板，"时效新闻"这类查询就没有排序依据。
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import cn_sources as cn          # noqa: E402
from engines import fallback as fb            # noqa: E402
from engines.fallback import _cn_date_of      # noqa: E402


# ---------------------------------------------------------------- 日期解析
@pytest.mark.parametrize('text,expect', [
    ('2026年4月2日RAG技术全解析', '2026-04-02'),
    ('发布时间：2025-09-19 10:00', '2025-09-19'),
    ('2026/1/5 更新', '2026-01-05'),
    ('2024-12-10', '2024-12-10'),
    ('没有日期的文本', ''),
    ('商代甲骨文 1899 年', ''),            # 早于 2000 年的不算发布日期
])
def test_绝对日期解析(text, expect):
    assert _cn_date_of(text) == expect, text


@pytest.mark.parametrize('text,delta_days', [('刚刚', 0), ('今天', 0), ('昨天', 1),
                                             ('3天前', 3), ('2小时前', 0), ('5周前', 35)])
def test_相对日期按今天算(text, delta_days):
    today = dt.date.today()
    assert _cn_date_of(text, today=today) == (today - dt.timedelta(days=delta_days)).isoformat()


def test_日期解析遇到脏输入不炸():
    for bad in (None, '', 123, {'a': 1}, '2026年13月40日'):
        assert _cn_date_of(bad) in ('', '2026-01-01') or len(_cn_date_of(bad)) == 10


# ---------------------------------------------------------------- baidu-serp 摘要
def _page(html: str) -> bytes:
    return (html + '<!--' + 'x' * (fb.SERP_MIN_BYTES + 1024) + '-->').encode('utf-8')


# 第 2 条故意没有摘要：旧的位置配对会把第 3 条的摘要挂到第 2 条上
BAIDU_SERP_PAGE = '''
<div id="content_left">
  <div class="result c-container new-pmd">
    <h3 class="t"><a href="http://www.baidu.com/link?url=S1">私有化部署成本测算</a></h3>
    <div class="summary-text_15QGa">按卡时与并发估算：70B 模型单卡 A800 起步约 3.2 万元/月</div>
  </div>
  <div class="result c-container new-pmd">
    <h3 class="t"><a href="http://www.baidu.com/link?url=S2">没有摘要的一条</a></h3>
  </div>
  <div class="result c-container new-pmd">
    <h3 class="t"><a href="http://www.baidu.com/link?url=S3">DeepSeek 私有化实践</a></h3>
    <div class="summary-text_9Zzz9">2025年9月19日千亿级参数模型的部署对显存与并发提出更高要求</div>
  </div>
  <div id="content_bottom">页脚</div>
</div>
'''.strip()


@pytest.fixture()
def serp(monkeypatch):
    monkeypatch.setattr(cn, '_http_get', lambda *a, **k: _page(BAIDU_SERP_PAGE))
    return cn.BaiduSerpEngine().search('大模型 私有化部署 成本', max_results=5) or []


def test_baidu_serp_取到摘要(serp):
    """实测 5/5 条 content 为空：摘要正则整页 0 命中。"""
    by = {r.url.rsplit('=', 1)[-1]: r for r in serp}
    assert '按卡时与并发估算' in by['S1'].content, by['S1'].content
    assert by['S2'].content == '' or '按卡时' not in by['S2'].content, by['S2'].content


def test_baidu_serp_摘要不许串位(serp):
    """位置配对（snippets[i]）会让缺摘要的那条借用下一条的摘要。"""
    by = {r.url.rsplit('=', 1)[-1]: r for r in serp}
    assert '千亿级参数' in by['S3'].content, by['S3'].content
    assert '千亿级' not in by['S2'].content, by['S2'].content


def test_baidu_serp_日期进_published_date(serp):
    by = {r.url.rsplit('=', 1)[-1]: r for r in serp}
    assert by['S3'].published_date == '2025-09-19', by['S3'].published_date


# ---------------------------------------------------------------- 知乎 / 百度降级
ZHIHU_PAGE = '''
<div class="vrwrap">
  <h3 class="vr-title"><a href="/link?url=Z1">大模型部署成本分析</a></h3>
  <div class="fz-mid space-txt base-ellipsis">问答社区里关于私有化部署的讨论，先看卡价与并发</div>
  <span class="cite-date">2024-12-10</span>
</div>
<!-- ResultListViewEnd -->
'''.strip()


def test_zhihu_日期从结果块进字段(monkeypatch):
    monkeypatch.setattr(cn, '_http_get', lambda *a, **k: _page(ZHIHU_PAGE))
    r = (cn.SogouZhihuEngine().search('大模型 部署', max_results=3) or [])[0]
    assert r.published_date == '2024-12-10', r.published_date
    assert '卡价与并发' in r.content, r.content


def test_baidu_html_日期进字段(monkeypatch):
    html = ('<div id="content_left"><div class="c-container new-pmd">'
            '<h3 class="t"><a href="http://www.baidu.com/link?url=B1">满血版部署</a></h3>'
            '<div class="summary-text_15QGa">2025年9月19日DeepSeek满血版作为千亿级参数的大模型</div>'
            '</div><div id="content_bottom"></div></div>')
    monkeypatch.setattr(fb, '_http_get', lambda *a, **k: _page(html))
    r = (fb.BaiduHtmlEngine().search('大模型 部署', max_results=3) or [])[0]
    assert r.published_date == '2025-09-19', r.published_date
