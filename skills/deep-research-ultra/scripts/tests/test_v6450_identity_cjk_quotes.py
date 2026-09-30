"""v6.44 实跑第五轮撞到的缺陷：`content-identity` 不认 `『』` 这对引号。

同一包里的引文识别分叉了：
- `verify_quotes.py`（v6.44）与 SKILL.md 派单模板都把 `『…』` 定为"逐字引文"的标记；
- `ledger.py` 的 `_QUOTE_PATTERNS` 只列了 `「」`、`“”`、`"`、反引号，没有 `『』`。

后果（2026-09-30 真件）：NCC 三条 claim 带着 80 字以上的 `『…』` 正文逐字段，
`content-identity` 回"原文里没有 ≥20 字的逐字片段，转述不能当判同凭据"——
判同失败 → 档 B 反查被拒 → 明明 Europe PMC 文章页与 PubMed 两侧都写着同一句话，还是升不上去。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import ResearchLedger, _quote_spans  # noqa: E402

FRAGMENT = 'Inter-rater agreement was excellent (κ = 0.91; 95% CI, 0.86–0.96)'
ANCHOR = 'https://europepmc.org/articles/PMC13506236'
TARGET = ('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
          '?db=pubmed&id=42640622&rettype=abstract&retmode=text')
BODIES = {
    ANCHOR: 'Background. ' + FRAGMENT + '. Overall, 165 of 300 references contained an inaccuracy.',
    TARGET: 'PubMed record. ' + FRAGMENT + '. The primary outcome was any hallucination.',
}
# 两侧正文都得长过 MIN_IDENTITY_BODY，短了会被当空壳拒
BODIES = {k: (v + ' 填充正文长度。' * 60) for k, v in BODIES.items()}


def _led(tmp_path, text):
    led = ResearchLedger(str(tmp_path / 'ledger')).init()
    c = led.add_claim(text, 'NCC', 'pending')
    led.add_source(c['id'], ANCHOR)
    return led, c


def test_中文双角括号里的逐字段要被认出来():
    spans = _quote_spans('正文原文『' + FRAGMENT + '』说明了一致性')
    assert spans, '『』是本包规定的逐字引文标记，认不出来等于把逐字引文当转述'
    assert FRAGMENT.lower() in spans[0]


def test_两套引文识别不许分叉():
    """verify_quotes 认的括号，判同也得认——否则一处说"这是逐字"，另一处说"没有引文"。"""
    from verify_quotes import quoted_fragments
    for open_, close in (('『', '』'), ('「', '」'), ('“', '”')):
        text = open_ + 'x' * 40 + close
        assert quoted_fragments(text), f'verify_quotes 不认 {open_}'
        assert _quote_spans(text), f'content-identity 不认 {open_}'


def test_带中文双角引号的claim能判同(tmp_path):
    led, c = _led(tmp_path, '正文原文『' + FRAGMENT + '』说明了评审一致性')
    n = led.content_identity([c['id']], ANCHOR, TARGET, body_of=lambda u: BODIES.get(u, ''))
    assert n == 1, '两侧正文都含这句逐字段，应当判同'


def test_全是转述时仍然拒绝判同(tmp_path):
    led, c = _led(tmp_path, '该研究报告了很好的一致性水平，具体数字未记')
    assert led.content_identity([c['id']], ANCHOR, TARGET,
                                body_of=lambda u: BODIES.get(u, '')) == 0


def test_判同之后档B反查能升级(tmp_path):
    led, c = _led(tmp_path, '正文原文『' + FRAGMENT + '』说明了评审一致性')
    assert led.content_identity([c['id']], ANCHOR, TARGET,
                                body_of=lambda u: BODIES.get(u, '')) == 1
    assert led.verify_primary([c['id']], TARGET, method='pubmed_efetch') == 1
    got = [x for x in led.export_json()['claims'] if x['id'] == c['id']][0]
    assert got['status'] == 'verified'
    assert got.get('verify_method') == 'pubmed_efetch'
