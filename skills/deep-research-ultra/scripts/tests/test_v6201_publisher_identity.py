"""v6.20.1 回归：网址里写着同一个 DOI / 页面 ID 就是已知 DOI 后缀时，算同一制品。

实跑 2026-09-24（端到端调研，93 条 claim）：33 条派子 Agent 换官方通道真复核，
14 条判 PASS 却仍升不了档，键长这样——

  反查 https://link.springer.com/article/10.1007/s11192-013-1089-2
  来源 https://doi.org/10.1007/s11192-013-1089-2          → 同串 DOI，一个在路径里

  反查 https://aclanthology.org/2023.emnlp-main.398(.pdf)
  来源 https://doi.org/10.18653/v1/2023.emnlp-main.398     → 页面 ID 即 DOI 后缀
                                                          （ACL 公告的固定前缀）

内容已经读过、字面已经对上，只因为"两条网址的 host+path 不同"被判成不同制品。
这类同一性是**从网址文本就能推出**的，不需要解析跳转——不认就等于逼 Lead 放弃真实反查，
或者干脆放弃升级（本轮 19 条最后只能留在 pending 里标作线索）。

反向约束：放宽只能放宽到"抄得出来的常量映射"。Nature/AAAI/PMC 的落地页 URL 里
不含 DOI 也不含已知前缀，仍算不同制品（不许为了放行去猜 host 规律）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import _artifact_key  # noqa: E402


def test_doi_in_publisher_path_is_one_artifact():
    doi = '10.1007/s11192-013-1089-2'
    keys = {_artifact_key(f'https://doi.org/{doi}'),
            _artifact_key(f'https://link.springer.com/article/{doi}'),
            _artifact_key(f'https://link.springer.com/article/{doi}?sorting=newest')}
    assert len(keys) == 1, f'路径里写着同一个 DOI 却判成 {len(keys)} 个制品: {keys}'


def test_acl_anthology_page_id_maps_to_its_doi():
    a = _artifact_key('https://aclanthology.org/2023.emnlp-main.398')
    b = _artifact_key('https://aclanthology.org/2023.emnlp-main.398.pdf')
    c = _artifact_key('https://doi.org/10.18653/v1/2023.emnlp-main.398')
    assert a == b == c, f'ACL 页面与其 DOI 判成不同制品: {a} | {b} | {c}'


def test_doi_shaped_path_does_not_hijack_arxiv_or_github():
    """arXiv / GitHub 已有各自的键，不许被 DOI 规则抢走（否则 v6.19.0 的修复退化）。"""
    assert _artifact_key('https://arxiv.org/abs/2312.10997') == 'arxiv:2312.10997'
    assert _artifact_key('https://github.com/chrisyangsong/citegate') == \
        _artifact_key('https://api.github.com/repos/chrisyangsong/citegate/readme')


def test_unknown_host_without_doi_is_not_merged():
    """落地页里没有 DOI、也不在已知前缀表里 → 仍是不同制品，不许猜。"""
    a = _artifact_key('https://doi.org/10.1038/s41598-023-41032-5')
    b = _artifact_key('https://www.nature.com/articles/s41598-023-41032-5')
    assert a != b, '把"看着像"当成"推得出"，反查凭据就成了猜谜'
    assert _artifact_key('https://example.org/posts/421') == \
        _artifact_key('https://example.org/posts/421/')


def test_stackexchange_api_view_and_page_are_one_question():
    """SE 的官方 API 视图与网页是同一个问题：问题号就是身份，slug 是装饰。

    实跑 2026-09-24 两条 LaTeX 校验的 claim 卡在这：
      来源 https://tex.stackexchange.com/questions/8332/undefined-citation-warnings
      反查 https://api.stackexchange.com/2.3/questions/8332?site=tex&filter=withbody
    两条通道由 SE 自己保证等价（换 slug 它自己 302 回去），判不成同一制品没有道理。
    """
    a = _artifact_key('https://tex.stackexchange.com/questions/8332/undefined-citation-warnings')
    b = _artifact_key('https://api.stackexchange.com/2.3/questions/8332'
                      '?site=tex&filter=withbody')
    c = _artifact_key('https://tex.stackexchange.com/questions/8332/another-slug')
    assert a == b == c, f'同一个问题判成多个制品: {a} | {b} | {c}'
    d = _artifact_key('https://tex.stackexchange.com/questions/43276/unused')
    assert a != d, '不同问题号被判成同一制品'
    e = _artifact_key('https://apple.stackexchange.com/questions/8332/x')
    assert a != e, '跨站点同问题号并成了同一制品'


def test_docs_page_and_its_markdown_source_are_one_artifact():
    """文档站的渲染页与其 `.md` 源是同一份内容（实跑：智谱文档 1 条卡在这）。"""
    a = _artifact_key('https://docs.bigmodel.cn/cn/guide/tools/web-search')
    b = _artifact_key('https://docs.bigmodel.cn/cn/guide/tools/web-search.md')
    assert a == b, f'同一页的 .md 源与渲染页判成两个制品: {a} | {b}'
    c = _artifact_key('https://docs.bigmodel.cn/cn/guide/tools/other')
    assert a != c, '不同页面被扩展名归一并成了同一制品'


def test_publisher_page_still_cannot_back_a_different_doi():
    """判等放宽到路径后，反查打在另一篇文章上仍要被拒。"""
    led_src = _artifact_key('https://doi.org/10.1007/s11192-013-1089-2')
    other = _artifact_key('https://link.springer.com/article/10.1007/s11192-0999-9999-9')
    assert led_src != other, '同站不同 DOI 被判成同一制品，反查可以张冠李戴'
