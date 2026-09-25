"""SERP 改版预警脚本的分类逻辑（离线可测，不联网）。

动机：bing-html 那次失效是"结果块能切出来、标题模式 0 命中"，在 --probe 里只表现为
"⚠️ 0 结果"——和"这个查询真没结果"长得一模一样，于是没人发现，直到手工逐台查才抓到。
需要的不是更多测试夹具（我照着正则写的夹具证明不了上游没改版），而是一个能周期性真抓
一次页面、把三种"0 结果"分开的检查器：

    通道失败   字节数 0
    改版嫌疑   结果块 > 0 但解析出 0 条     ← 这次 Bing 就是这个形状
    真没命中   页面里连结果块都没有
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_serp_patterns as csp                       # noqa: E402


def test_zero_bytes_is_channel_failure():
    assert csp.classify(bytes_len=0, blocks=0, results=0) == csp.CHANNEL_FAILED


def test_blocks_without_results_is_a_redesign_suspect():
    """这次 Bing 的形状：10 个结果块、0 条标题命中。必须单独成一类，不许混进"没命中"。"""
    assert csp.classify(bytes_len=98000, blocks=10, results=0) == csp.REDESIGN_SUSPECT


def test_no_blocks_at_all_is_a_plain_miss():
    assert csp.classify(bytes_len=98000, blocks=0, results=0) == csp.NO_HIT


def test_engine_without_block_pattern_cannot_be_judged():
    """blocks=None 是"这个引擎没有块级模式"，不许混进"页面里没有结果块"去自信下结论。"""
    assert csp.classify(bytes_len=330000, blocks=None, results=0) == csp.UNKNOWN_SHAPE
    assert '判不了' in csp.ADVICE[csp.UNKNOWN_SHAPE], csp.ADVICE[csp.UNKNOWN_SHAPE]


def test_partial_rot_is_a_suspect_too():
    """实测 baidu-html：7 个结果块只解析出 1 条。掉一大半也是改版信号，不许报"正常"。"""
    assert csp.classify(bytes_len=1136856, blocks=7, results=1, cap=5) == csp.REDESIGN_SUSPECT


def test_truncation_at_max_results_is_not_a_suspect():
    """块比请求条数多是正常的（引擎到 max_results 就停），不能误报成失效。"""
    assert csp.classify(bytes_len=100000, blocks=20, results=5, cap=5) == csp.OK


def test_no_organic_results_marker_says_so_instead_of_blaming_the_parser():
    """实测百度返回的是外壳页（热搜榜＋输入法面板），块级模式吃到了页面外壳。

    这种时候报"改版嫌疑"是误报：解析器没错，是这一页压根没有自然结果（风控）。
    误报一次的代价是以后没人信这个工具，所以内容标记没命中时要说"没有自然结果"。
    """
    assert csp.classify(bytes_len=870379, blocks=5, results=0, cap=5,
                        has_content=False) == csp.NO_HIT
    assert '外壳' in csp.ADVICE[csp.NO_HIT] or '风控' in csp.ADVICE[csp.NO_HIT]


def test_content_marker_present_keeps_the_redesign_verdict():
    """页面里确有自然结果、条目却一条没解析出来 —— 这才轮到怀疑解析器。"""
    assert csp.classify(bytes_len=870379, blocks=5, results=0, cap=5,
                        has_content=True) == csp.REDESIGN_SUSPECT


def test_results_win_over_everything_else():
    assert csp.classify(bytes_len=5000, blocks=3, results=3) == csp.OK


def test_redesign_suspect_says_which_stage_to_look_at():
    """分类要能指导动作：改版嫌疑要说"块切出来了，去看标题/链接子模式"。"""
    advice = csp.ADVICE[csp.REDESIGN_SUSPECT]
    assert '块级模式' in advice and '标题' in advice, advice
