"""v6.17.3 回归：同一篇论文的多个版本，不得被数成两个独立来源。

实测（2026-09-24，OpenAlex 单次查询 `LLM agent hallucination source attribution`）：
  W4386501849 → http://arxiv.org/abs/2309.01219      Siren's Song in the AI Ocean...
  W4412158322 → https://doi.org/10.1162/coli.a.16    Siren’s Song in the AI Ocean...
同一篇综述的预印本与期刊版，域名一个是 arxiv.org、一个是 doi.org。
`Claim.get_sources()` 只按域名去重，于是两条 = 两个"独立来源" ≥ min_sources(2)
→ status=verified。同一次查询里 SciPy 那篇也以两个 URL 出现（期刊版 + 机构仓库版）。

这对一个以"claim→source 可追溯"为卖点的工具是最要命的假阳性：
自己引自己就能凑够交叉验证。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verify import CrossVerifier, Claim, Evidence  # noqa: E402


def _claim(*pairs):
    """pairs: (url, domain, title)"""
    c = Claim(id='c1', statement='LLM 幻觉综述指出检索对齐能降低幻觉')
    for url, domain, title in pairs:
        c.add_evidence(Evidence(source_url=url, source_domain=domain, source_title=title))
    return c


ARXIV = ('http://arxiv.org/abs/2309.01219', 'arxiv.org',
         "Siren's Song in the AI Ocean: A Survey on Hallucination in Large Language Models")
JOURNAL = ('https://doi.org/10.1162/coli.a.16', 'doi.org',
           "Siren’s Song in the AI Ocean: A Survey on Hallucination in Large Language Models")


def test_same_work_two_versions_counts_as_one_source():
    """同一篇论文的 arXiv 版 + 期刊版（标题只差弯/直引号）＝一个来源。"""
    c = _claim(ARXIV, JOURNAL)
    assert c.get_independent_source_count() == 1, (
        f'同一篇论文的两个版本被数成 {c.get_independent_source_count()} 个独立来源')


def test_same_work_two_versions_does_not_reach_verified():
    """升 verified 的门不许被"自己引自己"顶开。"""
    v = CrossVerifier().verify([], query='幻觉', claims=[_claim(ARXIV, JOURNAL)])
    assert not v.verified_claims, '同一篇论文的两个版本被判为已交叉验证'
    assert len(v.single_source_claims) == 1


def test_two_different_titles_still_count_two():
    """反向保护：不同论文（标题不同）仍算两个来源，别把门焊死。"""
    c = _claim(ARXIV,
               ('https://doi.org/10.9999/other', 'doi.org',
                'Faith in AI can narrow the futures individuals perceive'))
    assert c.get_independent_source_count() == 2
    v = CrossVerifier().verify([], query='幻觉', claims=[c])
    assert len(v.verified_claims) == 1, '两个真不同的来源仍该能升 verified'


def test_untitled_evidence_falls_back_to_domain():
    """没给标题的证据（常见于只带 URL 的引用）退回按域名判，不得因为标题空就把两域合并。"""
    c = _claim(('https://a.dev/p', 'a.dev', ''),
               ('https://b.dev/q', 'b.dev', ''))
    assert c.get_independent_source_count() == 2


def test_same_domain_same_url_still_one():
    """原行为不回退：同 URL 重复只算一次。"""
    c = _claim(ARXIV, ARXIV)
    assert c.get_independent_source_count() == 1


def test_verify_and_ledger_agree_on_what_counts_as_one_work():
    """同一件作品在两层得给同一个数——把这组对照钉住。

    验证层新加了 normalize_work_title（精确归一），账本/覆盖面层用
    similarity.is_same_content（指纹比对）。实测 8 组样本两层判定一致（含 OpenAlex
    真实返回的那对预印本/期刊版），所以暂不合并实现；但一致是**巧合还是约定**，
    只有把它写成对照表才守得住：任一层日后放宽或收紧，这里就会红。

    期望值逐条写明，不靠两层互算——先前版本写成 `assert 层A == 层B` 是空转的：
    两边都答 2 时它同样通过，什么都没测。
    """
    from similarity import is_same_content
    from verify import normalize_work_title as norm

    SIREN = ("Siren's Song in the AI Ocean: A Survey on Hallucination in "
             "Large Language Models")
    SIREN_VARIANT = ("\U0001f9dc Siren’s Song in the AI Ocean: A Survey on "
                     "Hallucination in Large Language Models")
    # (标题 A, 标题 B, 两层是否都应判为"同一件作品")
    CASES = [
        (SIREN, SIREN_VARIANT, True),        # OpenAlex 实测返回的一对
        (SIREN, 'Faith in AI can narrow the futures individuals perceive', False),
        ('Code as Agent Harness', 'Code as an Agent Harness', False),
        ('Retrieval Augmented Generation Survey',
         'Retrieval Augmented Generation: A Survey', False),
        ('LLM 证据溯源研究', 'LLM 证据溯源研究（下篇）', False),
        ('A Survey of X', 'A Survey of Y', False),
    ]
    for a, b, same in CASES:
        assert (norm(a) == norm(b)) is same, f'验证层判错：{a!r} vs {b!r}'
        assert is_same_content(a, b) is same, f'账本层判错：{a!r} vs {b!r}'
