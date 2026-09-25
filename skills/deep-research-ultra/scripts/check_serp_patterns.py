#!/usr/bin/env python3
"""SERP 改版预警：真抓一次页面，把「0 结果」的三种成因分开报。

为什么要有这个：HTML 抓取类引擎失效时，在 `--probe` 里只表现为"⚠️ 可调通但 0 结果"，
和"这个查询真没结果"长得一模一样。实测 Bing 那次就是这样静默失效的——结果块能切出 10 个，
标题模式 0 命中，于是整页有结果也回 0 条，没人发现，直到手工分层去查。

补测试夹具救不了这类问题（我照着正则写的夹具，只能证明正则匹配我想象中的页面），
所以这里做的是：**真取一次页面**，按"取到多少字节 / 切出多少结果块 / 解析出多少条"
三档判定。判定表：

    通道失败       一个字节都没取到
    改版嫌疑       块切出来了，但解析出的条数远低于块数（含 0 条）
    判不了         该引擎没有块级模式，拿不到"块数"这一档
    真没命中       页面里确实没有结果块

用法：
    python scripts/check_serp_patterns.py                      # 全部 HTML 抓取类源
    python scripts/check_serp_patterns.py --only bing-html
    python scripts/check_serp_patterns.py --peek baidu-xueshu  # 顺带看页面首段，判是不是验证页
退出码：出现「改版嫌疑」返回 2（可挂进发布前检查），否则 0。
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from engines import fallback as fb                      # noqa: E402
from engines.cn_sources import (BaiduSerpEngine, SogouWeixinEngine,   # noqa: E402
                                SogouZhihuEngine, BaiduXueshuEngine)

OK = 'ok'
CHANNEL_FAILED = 'channel_failed'      # 一个字节都没取到：网络/拦连/被风控
REDESIGN_SUSPECT = 'redesign_suspect'  # 块切得出、条解析不出（或只出一小半）
NO_HIT = 'no_hit'                      # 页面里确实没有结果块
UNKNOWN_SHAPE = 'unknown_shape'        # 该引擎没有块级模式，这一档判不了

ADVICE: Dict[str, str] = {
    OK: '正常出数据',
    CHANNEL_FAILED: '通道失败：先查网络/代理/风控，与解析器无关',
    REDESIGN_SUSPECT: ('上游改版嫌疑：页面确有自然结果、条目却大量丢失 —— 去核对该引擎的'
                       '标题/链接子模式（块级模式还活着）'),
    NO_HIT: ('页面里没有自然结果：换查询词重试，或该源被风控回了外壳页'
             '（热搜榜/输入法面板那类页面骨架，不是搜索结果）'),
    UNKNOWN_SHAPE: ('判不了：该引擎没有块级模式，分不清改版还是真没命中 —— '
                    '用 --peek 看页面首段（是不是验证页/空壳页）'),
}

STATUSES = (OK, CHANNEL_FAILED, REDESIGN_SUSPECT, NO_HIT, UNKNOWN_SHAPE)

MAX_RESULTS = 5            # 与引擎调用时的 max_results 一致，用来区分"截断"与"丢失"
DROP_RATIO = 3             # 条数 × 该系数仍小于块数 → 判大量丢失


def classify(bytes_len: int, blocks: Optional[int], results: int,
             cap: Optional[int] = None, has_content: Optional[bool] = None) -> str:
    """判定这一发属于哪种"没结果"。

    blocks 为 None＝该引擎没有块级模式；has_content 为 False＝页面里连自然结果的标记都没有
    （实测百度会返回热搜榜外壳页，块级模式吃到的是页面骨架，这时怪解析器就是误报）。
    """
    if bytes_len <= 0:
        return CHANNEL_FAILED
    if (blocks is not None and blocks >= 3 and results != cap
            and results * DROP_RATIO < blocks):
        return NO_HIT if has_content is False else REDESIGN_SUSPECT
    if blocks is None:
        return OK if results > 0 else UNKNOWN_SHAPE
    return OK if results > 0 else NO_HIT


# 每个引擎的 URL 照它自己 search() 里的拼法，不另起一套（拼错会得到一个假"通道失败"）；
# marker 是"这页确实有自然结果"的粗判据，用来把"被风控回外壳页"和"解析器过期"分开
SPECS: List[Dict] = [
    {'name': 'baidu-html', 'cls': fb.BaiduHtmlEngine,
     'url': lambda e, q: f"{e.SEARCH_URL}?" + urllib.parse.urlencode(
         {'wd': q, 'rn': '5', 'pn': '0', 'ie': 'utf-8'}),
     'impersonate': 'chrome124', 'marker': r'link\.url='},
    {'name': 'bing-html', 'cls': fb.BingHtmlEngine,
     'url': lambda e, q: f"{e.SEARCH_URL}?" + urllib.parse.urlencode(
         {'q': q, 'count': '5', 'first': '1', 'setlang': 'zh-CN'}),
     'marker': r'class="b_algo"'},
    {'name': 'baidu-serp', 'cls': BaiduSerpEngine,
     'url': lambda e, q: f"{e.SEARCH_URL}?" + urllib.parse.urlencode(
         {'wd': q, 'rn': '5', 'ie': 'utf-8'}),
     'impersonate': 'chrome124', 'marker': r'link\.url='},
    {'name': 'sogou-weixin', 'cls': SogouWeixinEngine,
     'url': lambda e, q: f"{e.SEARCH_URL}?" + urllib.parse.urlencode(
         {'type': '2', 'query': q, 'ie': 'utf-8'}),
     'impersonate': 'chrome124', 'marker': r'class="txt-box"'},
    {'name': 'sogou-zhihu', 'cls': SogouZhihuEngine,
     'url': lambda e, q: f"{e.SEARCH_URL}?" + urllib.parse.urlencode(
         {'query': q, 'ie': 'utf-8'}),
     'impersonate': 'chrome124', 'marker': r'vr-title'},
    {'name': 'baidu-xueshu', 'cls': BaiduXueshuEngine,
     'url': lambda e, q: f"{e.SEARCH_URL}?" + urllib.parse.urlencode(
         {'wd': q, 'ie': 'utf-8'}),
     'impersonate': 'chrome124'},
]


def _fetch(spec: Dict, query: str) -> tuple:
    eng = spec['cls']()
    kwargs = {'timeout': 25}
    if spec.get('impersonate'):
        kwargs['impersonate'] = spec['impersonate']
    fb.LAST_HTTP_ERROR = ''
    raw = fb._http_get(spec['url'](eng, query), **kwargs) or b''
    return eng, raw, fb.LAST_HTTP_ERROR


def check_one(spec: Dict, query: str) -> Dict:
    import re as _re
    eng, raw, http_err = _fetch(spec, query)
    html = fb._decode_html(raw) if raw else ''
    pat = getattr(eng, 'RESULT_PATTERN', None) or getattr(eng, 'ANCHOR_PATTERN', None)
    blocks = len(pat.findall(html)) if pat is not None else None
    marker = spec.get('marker')
    has_content = bool(_re.search(marker, html)) if marker else None
    got = eng.search(query, max_results=MAX_RESULTS)
    results = 0 if got is None else len(got)
    return {'engine': spec['name'],
            'status': classify(len(raw), blocks, results, cap=MAX_RESULTS,
                               has_content=has_content),
            'bytes': len(raw), 'blocks': blocks, 'results': results,
            'has_content': has_content, 'http_error': http_err}


def peek(spec: Dict, query: str, width: int = 700) -> str:
    """把页面首段原样打出来（去标签），用来判"是不是拿到一个验证页/空壳页"。"""
    import re as _re
    _, raw, err = _fetch(spec, query)
    if not raw:
        return f'（取到 0 字节）{err}'
    text = _re.sub(r'<script.*?</script>|<style.*?</style>', '',
                   fb._decode_html(raw), flags=_re.S | _re.I)
    text = _re.sub(r'<[^>]+>', ' ', text)
    return ' '.join(text.split())[:width]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='SERP 改版预警（真取页面，分类报）')
    ap.add_argument('--query', default='retrieval augmented generation')
    ap.add_argument('--only', default='', help='逗号分隔的引擎名，默认全跑')
    ap.add_argument('--gap', type=float, default=4.0,
                    help='相邻两发的间隔秒数（同一 SERP 主机连发会被限流）')
    ap.add_argument('--peek', default='', help='只打这个引擎的页面首段，不做判定')
    args = ap.parse_args(argv)

    wanted = {s.strip() for s in args.only.split(',') if s.strip()}
    specs = [s for s in SPECS if not wanted or s['name'] in wanted]

    if args.peek:
        spec = next((s for s in SPECS if s['name'] == args.peek), None)
        if spec is None:
            print(f'不认识引擎 {args.peek!r}，可选：'
                  + ', '.join(s['name'] for s in SPECS), file=sys.stderr)
            return 1
        print(peek(spec, args.query))
        return 0

    print(f'SERP 改版预警 ｜ 查询词 {args.query!r} ｜ {len(specs)} 个引擎')
    print('-' * 78)
    marks = {OK: '✅', CHANNEL_FAILED: '❌', REDESIGN_SUSPECT: '🔴',
             NO_HIT: '⚠️', UNKNOWN_SHAPE: '❓'}
    suspects = 0
    for i, spec in enumerate(specs):
        rep = check_one(spec, args.query)
        blocks = '—' if rep['blocks'] is None else rep['blocks']
        line = (f"{marks[rep['status']]} {rep['engine']:<14} 字节 {rep['bytes']:>7} ｜ "
                f"结果块 {blocks:>4} ｜ 解析出 {rep['results']} 条 ｜ {ADVICE[rep['status']]}")
        if rep['http_error']:
            line += f" ｜ {rep['http_error'][:50]}"
        print(line)
        if rep['status'] == REDESIGN_SUSPECT:
            suspects += 1
        if i < len(specs) - 1:
            time.sleep(args.gap)

    print('-' * 78)
    if suspects:
        print(f'🔴 {suspects} 个引擎"块切得出、条大量丢失"——先改它们的标题/链接子模式，'
              f'不要当成"这个主题没结果"')
        return 2
    print('没有改版嫌疑的引擎')
    return 0


if __name__ == '__main__':
    try:
        from console import force_utf8
        force_utf8()
    except Exception:
        pass
    sys.exit(main())
