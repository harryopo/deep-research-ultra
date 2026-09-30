"""v6.42 端到端实跑第五轮（补正文）暴露的缺陷：报告里标着「逐字」的引文其实对不上原文。

本轮我自己写了 11 条"正文逐字"的 claim，逐字校验查出 **6 处对不上**，成因三类：
- 字符形态：正文是 `Scale (0–3)`（en dash）、`κ = 0.91`、`GPTZero’s`（弯引号），我手打成了 `-`、`kappa`、`'`；
- 我自己加的分隔符：目录项之间加了 ` / `，正文里根本没有；
- **内容级**：摘要说「74.5% view peer review as ineffective」，正文限定的是"抓不到元数据错误"且分母是 n=94。

前两类是抄写错误，第三类最危险——它长得像引文，实际是转述。
所以这条门只做一件事：账本里每个『...』段必须能在抓回的原始材料里**逐字**命中，命中不了就退非零。
判据用真件里的实际字符形态（en dash、κ）构造，不用我编的理想样例。
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verify_quotes import check_quotes, load_corpus  # noqa: E402

# 真件字符形态：Europe PMC 全文里是 en dash 与希腊字母 κ
NCC_TRUE = ('scored using a modified Reference Hallucination Scale (0\u20133): score 0 = fully '
            'accurate, 1 = minor error/citation inaccuracy, 2 = major error/citation inaccuracy, '
            '3 = completely fabricated')
KAPPA_TRUE = 'Inter-rater agreement was excellent (\u03ba = 0.91; 95% CI, 0.86\u20130.96).'


def _corpus(tmp_path, text=NCC_TRUE + ' ' + KAPPA_TRUE):
    raw = tmp_path / 'raw'
    raw.mkdir(exist_ok=True)
    io.open(raw / 'ncc.txt', 'w', encoding='utf-8').write(text)
    return raw


def _ledger(tmp_path, claims):
    led = tmp_path / 'ledger'
    led.mkdir(exist_ok=True)
    with io.open(led / 'ledger.jsonl', 'w', encoding='utf-8') as f:
        for cid, text in claims:
            f.write(json.dumps({'type': 'claim', 'id': cid, 'text': text,
                                'topic': 't', 'status': 'pending'}, ensure_ascii=False) + '\n')
    return led


def test_逐字命中时通过(tmp_path):
    raw, led = _corpus(tmp_path), _ledger(tmp_path, [
        ('c-1', '原文『' + NCC_TRUE[:80] + '』说明了分级')])
    res = check_quotes(str(led), str(raw))
    assert res['misses'] == [], res['misses']
    assert res['checked'] >= 1


def test_en_dash_与连字符的差必须报MISS(tmp_path):
    """我自己踩过的第一个坑：把 (0–3) 打成 (0-3)。"""
    raw, led = _corpus(tmp_path), _ledger(tmp_path, [
        ('c-2', '原文『Reference Hallucination Scale (0-3): score 0 = fully accurate』')])
    res = check_quotes(str(led), str(raw))
    assert len(res['misses']) == 1
    assert res['misses'][0]['where'] == 'c-2'


def test_kappa_写成kappa必须报MISS(tmp_path):
    raw, led = _corpus(tmp_path), _ledger(tmp_path, [
        ('c-3', '原文『Inter-rater agreement was excellent (kappa = 0.91; 95% CI, 0.86-0.96).』')])
    res = check_quotes(str(led), str(raw))
    assert res['misses'], 'κ 被写成 kappa、en dash 被写成连字符，正是要抓的形态'


def test_多文件语料任一命中即可(tmp_path):
    raw = _corpus(tmp_path)
    io.open(raw / 'other.txt', 'w', encoding='utf-8').write('一句完全无关的正文内容，长度超过十五个字。')
    led = _ledger(tmp_path, [('c-4', '原文『一句完全无关的正文内容，长度超过十五个字』')])
    assert check_quotes(str(led), str(raw))['misses'] == []


def test_短引文不参与对账(tmp_path):
    raw, led = _corpus(tmp_path), _ledger(tmp_path, [('c-5', '原文『完全捏造』四字标签')])
    res = check_quotes(str(led), str(raw))
    assert res['checked'] == 0 and res['misses'] == []


def test_空白折叠后仍算命中(tmp_path):
    """PDF/HTML 抽出来的正文换行很多，规范化空白是允许的，改字符不是。"""
    raw = _corpus(tmp_path, text='a long verbatim sentence   with\nextra   whitespace inside it')
    led = _ledger(tmp_path, [('c-6', '原文『a long verbatim sentence with extra whitespace inside it』')])
    assert check_quotes(str(led), str(raw))['misses'] == []


def test_没有可比对材料时不许报通过(tmp_path):
    """fail-closed：raw 目录空 = 无从判断，不能当成"引文都对"。"""
    empty = tmp_path / 'raw_empty'
    empty.mkdir()
    led = _ledger(tmp_path, [('c-7', '原文『' + NCC_TRUE[:60] + '』')])
    res = check_quotes(str(led), str(empty))
    assert res['error'] and res['checked'] == 0


def test_validate_report_带raw时把MISS列为issue(tmp_path):
    raw, led = _corpus(tmp_path), _ledger(tmp_path, [
        ('c-8', '原文『Reference Hallucination Scale (0-3): score 0 = fully accurate』')])
    report = tmp_path / 'report.md'
    io.open(report, 'w', encoding='utf-8').write('\n'.join([
        '# 主题', '', '## 执行摘要', '一句话结论。', '',
        '## 调研方法', '方法说明若干字。', '',
        '## 结论与建议', '结论若干字。', '',
        '## 来源', '', '| 编号 | Tier | 标题 | URL |', '|---|---|---|---|',
        '| [1] | 1 | 文 | https://europepmc.org/articles/PMC1 |', '',
        '证据行 原文『Reference Hallucination Scale (0-3): score 0 = fully accurate』 ⚠️',
    ]))
    with io.open(led / 'ledger.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'type': 'source', 'claim_id': 'c-8',
                            'url': 'https://europepmc.org/articles/PMC1',
                            'title': '文', 'tier': 1}, ensure_ascii=False) + '\n')
    p = subprocess.run([sys.executable, '-X', 'utf8',
                        str(Path(__file__).resolve().parents[1] / 'validate_report.py'),
                        '--report', str(report), '--ledger', str(led), '--raw', str(raw)],
                       capture_output=True, text=True, encoding='utf-8')
    assert p.returncode == 1, p.stdout[-600:]
    assert '逐字' in p.stdout or '逐字' in p.stderr, (p.stdout[-500:], p.stderr[-300:])
