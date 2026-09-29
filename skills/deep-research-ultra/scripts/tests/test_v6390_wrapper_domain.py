"""v6.39.0 回归：包装域名不许把不同原站压成一个域。

实测（2026-09-29 端到端实跑，D3 分片）：搜狗的跳转壳把原站藏在子域里——
`https://zhihu.sogou.com/link?url=…`（知乎文章）、`https://weixin.sogou.com/link?url=…`
（微信公众号文章）。`verify.CrossVerifier.get_domain` 取"最后两段"，两者都变成 `sogou.com`，
于是账本里"独立域名数"把一篇知乎与一篇微信记成同一个来源：中文侧的跨源计数系统性偏低，
D3 因此有几条明明有两个不同原站却卡在"来源不足"。

这不是放水方向（不会把同域两篇抬成两个源），但它让中文证据永远凑不满档 A，
所以修法是**把跳转壳按原站子域分桶**，同壳不同原站不再合并，同原站仍算一个。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verify import CrossVerifier  # noqa: E402

ZHIHU_SHELL = 'https://zhihu.sogou.com/link?url=hedJjaC291OfPyaFZYFLI4KQWvqt63NBpzkf3ig7YnltM'
ZHIHU_SHELL_2 = 'https://zhihu.sogou.com/link?url=hedJjaC291OfPyaFZYFLI4KQWvqt63NBc1E5DYxfLYa3h'
WEIXIN_SHELL = 'https://weixin.sogou.com/link?url=dn9a_-gY295K0Rci_xozVXfdMkSQTLW6cwJThYulHEtV'


def test_wrapper_shells_of_different_origins_are_not_one_domain():
    """知乎壳与微信壳是两个原站，不许都记成 sogou.com。"""
    a = CrossVerifier.get_domain(ZHIHU_SHELL)
    b = CrossVerifier.get_domain(WEIXIN_SHELL)

    assert a != b, f"两个不同原站的跳转壳被压成了同一个域: {a} == {b}"
    assert 'zhihu' in a and 'weixin' in b, (a, b)


def test_same_origin_shells_still_count_as_one():
    """正向对照：同一个原站的两篇仍是 1 个域——修这条缺陷不是去抬独立来源数。"""
    assert CrossVerifier.get_domain(ZHIHU_SHELL) == CrossVerifier.get_domain(ZHIHU_SHELL_2)


def test_ordinary_subdomains_still_collapse():
    """非跳转壳的子域照旧归到注册域，别把修法用宽。"""
    assert CrossVerifier.get_domain('https://zh.wikipedia.org/wiki/RAG') == 'wikipedia.org'
    assert CrossVerifier.get_domain('https://www.example.com/a') == 'example.com'


def test_independence_decision_uses_the_split():
    """档 A 判据跟着变：知乎壳 + 微信壳 = 两个独立来源；两个知乎壳 = 一个。"""
    v = CrossVerifier.__new__(CrossVerifier)   # 只用纯函数，不需要构造完整验证器
    assert v.is_independent_source(ZHIHU_SHELL, WEIXIN_SHELL) is True
    assert v.is_independent_source(ZHIHU_SHELL, ZHIHU_SHELL_2) is False
