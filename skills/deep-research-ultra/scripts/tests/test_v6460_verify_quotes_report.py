"""v6.46：报告正文里的引文同样要过逐字对账门；〔〕是"自造口径"，不是引文。

为什么补这一刀（实跑撞出来的）：v6.44 的门只读账本，报告正文由 Lead 手写，于是账本改对了、
报告里还是旧写法——一次实跑里账本 83/83 全过，报告正文却数出 45 段对不上抓取材料。
交付物是报告，不是账本，门必须量到真正交出去的那份文本。

另一半是命名约定：『』/「」＝逐字引文（必须命中原始材料），〔〕＝Lead 自己的措辞
（术语、归纳、查询词）。没有这条约定时，把转述加引号会被门一直拦，把转述去掉引号又会丢语义，
最后只能靠"加一句非原文"打补丁。两套引号识别（ledger 判同 / verify_quotes 对账）都必须不认〔〕。
"""
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import verify_quotes as vq  # noqa: E402

BODY = ('Background. Prior audits report that '
        'ChatGPT produced fabricated references at a rate of nineteen percent '
        'in biomedical问答 settings. Methods. None.')


def _write(path, text):
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text)


class ReportMode(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.raw = os.path.join(self.dir, 'raw')
        os.makedirs(self.raw)
        _write(os.path.join(self.raw, 'paper.txt'), BODY)
        self.led = os.path.join(self.dir, 'ledger')
        os.makedirs(self.led)

    def _report(self, lines):
        path = os.path.join(self.dir, 'report.md')
        _write(path, '\n'.join(lines) + '\n')
        return path

    def test_verbatim_report_quote_passes(self):
        rp = self._report(['# 报告', '',
                           '原文『ChatGPT produced fabricated references at a rate of nineteen'
                           ' percent in biomedical问答 settings』。'])
        res = vq.check_quotes(self.led, self.raw, report=rp)
        self.assertIsNone(res['error'])
        self.assertEqual(res['misses'], [])
        self.assertEqual(res['checked'], 1)

    def test_non_verbatim_report_quote_is_caught(self):
        rp = self._report(['# 报告', '',
                           '开头一句',
                           '原文「ChatGPT made up 19% of references in medicine」。'])
        res = vq.check_quotes(self.led, self.raw, report=rp)
        self.assertEqual(len(res['misses']), 1)
        self.assertEqual(res['misses'][0]['where'], 'report.md:4')

    def test_line_number_points_at_the_offending_line(self):
        rp = self._report(['A', 'B', 'C', 'D', 'E',
                           '原文『fabricated references at a rate of nineteen percent』',
                           'F', '原文「这条是编的写法 not in corpus at all」。'])
        res = vq.check_quotes(self.led, self.raw, report=rp)
        self.assertEqual([m['where'] for m in res['misses']], ['report.md:8'])

    def test_ledger_and_report_are_checked_in_one_pass(self):
        _write(os.path.join(self.led, 'ledger.jsonl'),
               json.dumps({'type': 'claim', 'id': 'c-1',
                           'text': '原文『a phrase absent from the corpus entirely』'},
                          ensure_ascii=False) + '\n')
        rp = self._report(['原文「also absent from the corpus」'])
        res = vq.check_quotes(self.led, self.raw, report=rp)
        self.assertEqual(res['checked'], 2)
        self.assertEqual(sorted(m['where'] for m in res['misses']), ['c-1', 'report.md:1'])

    def test_missing_corpus_still_fails_closed_in_report_mode(self):
        empty = os.path.join(self.dir, 'empty')
        os.makedirs(empty)
        rp = self._report(['原文「anything at all here」'])
        res = vq.check_quotes(None, empty, report=rp)
        self.assertIsNotNone(res['error'])
        self.assertEqual(res['checked'], 0)

    def test_cli_accepts_report_without_ledger(self):
        rp = self._report(['原文「not present in the corpus」'])
        self.assertEqual(vq.main(['--raw', self.raw, '--report', rp]), 1)

    def test_cli_fails_closed_when_there_is_nothing_to_check(self):
        _write(os.path.join(self.raw, 'ok.txt'), BODY)
        # 只有语料、没有待查文本：不能打印"全部逐字命中"
        self.assertEqual(vq.main(['--raw', self.raw]), 2)
        self.assertEqual(vq.main(['--raw', self.raw,
                                  '--ledger', os.path.join(self.dir, 'no-such-dir')]), 2)
        empt = os.path.join(self.dir, 'empty-ledger')
        os.makedirs(empt)
        self.assertEqual(vq.main(['--raw', self.raw, '--ledger', empt]), 2)


class OwnWordingMarker(unittest.TestCase):
    """〔〕＝自造口径：两套引号识别都不许把它当逐字引文。"""

    def test_verify_quotes_ignores_own_wording_brackets(self):
        self.assertEqual(vq.quoted_fragments('本报告的〔自动引用核验器的假阴性率〕未测'), [])

    def test_ledger_identity_ignores_own_wording_brackets(self):
        import ledger as L
        frags = []
        for pat in L._QUOTE_PATTERNS:
            frags += [m.group(1) for m in pat.finditer(
                '本报告的〔a verbatim-looking span of text that is only mine〕在这里')]
        self.assertEqual(frags, [])


if __name__ == '__main__':
    unittest.main()
