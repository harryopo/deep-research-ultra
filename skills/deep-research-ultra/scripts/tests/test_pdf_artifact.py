"""X-D10 回归：下载下来的"PDF"必须先验明正身，不然写进账本就是假一手来源。

起因（另一次 effort=deep 实跑交回的清单）：`download_pdf()` 把 `_http_get` 返回的
任何字节直接写盘并返回路径——网络层/代理返回一张几百字节的 HTML 报错页、
下载被截断、甚至拿到另一篇论文的 PDF，全都算"成功"。
后续步骤拿它当全文读，账本里就留下一条指向无关文档的 verified 来源。
"""

from __future__ import annotations

import hashlib

import pytest

from engines.academic_fulltext import ArxivFulltextEngine, verify_pdf_artifact

PAPER = '2404.19756'


def _pdf(pages: int = 3, id_text: str = PAPER, size: int = 9000) -> bytes:
    """构造一段"像 PDF"的字节：魔数 + 页对象 + 尾部 %%EOF。"""
    body = (f'arXiv:{id_text} https://arxiv.org/abs/{id_text}'.encode('utf-8')
            + b' /Type /Page' * pages)
    pad = b'%00' * max(0, (size - len(body)) // 3)
    return b'%PDF-1.5\n' + body + pad + b'\n%%EOF\n'


# ---------------------------------------------------------------------------
# verify_pdf_artifact：字节层面的身份核验
# ---------------------------------------------------------------------------

def test_html_error_page_is_rejected():
    raw = b'<html><head><title>Attention Required! | Cloudflare</title></head></html>'
    r = verify_pdf_artifact(raw, PAPER)
    assert r['ok'] is False
    assert '不是 PDF' in r['reason']


def test_empty_response_is_rejected():
    r = verify_pdf_artifact(b'', PAPER)
    assert r['ok'] is False
    assert r['reason']


def test_tiny_pdf_is_rejected():
    r = verify_pdf_artifact(b'%PDF-1.5\n/Type /Page\n%%EOF\n', PAPER)
    assert r['ok'] is False
    assert '太小' in r['reason']


def test_truncated_pdf_is_rejected():
    r = verify_pdf_artifact(_pdf()[:-4], PAPER)
    assert r['ok'] is False
    assert '截断' in r['reason'] or '%%EOF' in r['reason']


def test_good_pdf_reports_size_hash_and_pages():
    raw = _pdf(pages=4)
    r = verify_pdf_artifact(raw, PAPER)
    assert r['ok'] is True, r['reason']
    assert r['bytes'] == len(raw)
    assert r['sha256'] == hashlib.sha256(raw).hexdigest()[:16]
    assert r['pages'] == 4


def test_different_paper_with_same_url_shape_is_caught(monkeypatch):
    """正文里找不到要的那篇的 arXiv ID —— 拿到的是另一篇。"""
    monkeypatch.setattr('engines.academic_fulltext._pdf_page_texts',
                        lambda raw: ['arXiv:9999.00001 Some Other Paper'])
    r = verify_pdf_artifact(_pdf(), PAPER)
    assert r['ok'] is False
    assert 'ID' in r['reason'] or '另一篇' in r['reason']


def test_matching_paper_id_is_accepted(monkeypatch):
    monkeypatch.setattr('engines.academic_fulltext._pdf_page_texts',
                        lambda raw: [f'arXiv:{PAPER}v1 [cs.LG] Title Here'])
    r = verify_pdf_artifact(_pdf(), PAPER)
    assert r['ok'] is True
    assert r['id_matched'] is True


def test_id_check_reports_undecidable_without_a_pdf_reader(monkeypatch):
    """没装 pypdf 时不许当成"核过了"：标 id_matched=None 并写清没核这一项。"""
    monkeypatch.setattr('engines.academic_fulltext._pdf_page_texts', lambda raw: None)
    r = verify_pdf_artifact(_pdf(), PAPER)
    assert r['ok'] is True                 # 结构合规，可用，但…
    assert r['id_matched'] is None
    assert '未核' in r['reason'] or '未装' in r['reason']


def test_id_check_is_skipped_when_no_expected_id(monkeypatch):
    called = []
    monkeypatch.setattr('engines.academic_fulltext._pdf_page_texts',
                        lambda raw: called.append(1) or [])
    r = verify_pdf_artifact(_pdf(), '')
    assert r['ok'] is True
    assert called == []                    # 没给 ID 就别硬编造比对


# ---------------------------------------------------------------------------
# download_pdf / fetch_latex 必须把不合格的字节挡住，不落盘
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine(monkeypatch):
    monkeypatch.setattr(ArxivFulltextEngine, '_rate_limit', lambda self: None)
    return ArxivFulltextEngine()


def test_download_pdf_rejects_html_and_writes_nothing(engine, monkeypatch, tmp_path):
    monkeypatch.setattr('engines.academic_fulltext._http_get',
                        lambda url, **kw: b'<html>rate limit</html>')
    out = tmp_path / 'p.pdf'
    assert engine.download_pdf(PAPER, str(out)) is None
    assert not out.exists()


def test_download_pdf_accepts_a_real_pdf(engine, monkeypatch, tmp_path):
    raw = _pdf()
    monkeypatch.setattr('engines.academic_fulltext._http_get', lambda url, **kw: raw)
    monkeypatch.setattr('engines.academic_fulltext._pdf_page_texts',
                        lambda b: [f'arXiv:{PAPER}v1'])
    out = tmp_path / 'p.pdf'
    assert engine.download_pdf(PAPER, str(out)) == str(out)
    assert out.read_bytes() == raw
    assert engine.last_download['pages'] >= 1


def test_fetch_latex_rejects_non_gzip(engine, monkeypatch):
    monkeypatch.setattr('engines.academic_fulltext._http_get',
                        lambda url, **kw: b'<html>no source</html>')
    assert engine.fetch_latex(PAPER) is None


def test_fetch_latex_accepts_gzip(engine, monkeypatch):
    monkeypatch.setattr('engines.academic_fulltext._http_get',
                        lambda url, **kw: b'\x1f\x8b\x08\x00' + b'\x00' * 100)
    r = engine.fetch_latex(PAPER)
    assert r and r['paper_id'] == PAPER
