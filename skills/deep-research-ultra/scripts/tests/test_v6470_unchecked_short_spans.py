"""v6.47：低于长度阈值的引号段要**报出来**，不能被回执说成"全部逐字命中"。

判据本身不变（短段仍不参与逐字判定，见 v6.44 的 `test_短引文不参与对账`——短标签命中不了语料
是常态，判它 MISS 会把门变成噪音）。变的是回执：`『』/「」` 这对括号在文档里承诺的是"逐字"，
与长度无关；门只看得到 ≥15 字的那一部分，就得把"另一部分没看"说出来。

实跑依据：本轮账本里数出 35 段 4–14 字的中文术语写着 `『』`（『支撑性』『已接地所以无造假』这类），
它们既不是原文、也从来没被对账过——只在门点名过的 8 段被修掉后，剩下的靠人手扫才看得见。
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import verify_quotes as vq  # noqa: E402

LONG = 'Reference Hallucination Scale (0-3): score 0 = fully accurate and 1 = partially'


def _mk(tmp_path, claims):
    raw = tmp_path / 'raw'
    raw.mkdir(parents=True)
    io.open(raw / 'body.txt', 'w', encoding='utf-8').write(
        'Some body text. ' + LONG + ' end of body sentence that is long enough to be checked.')
    led = tmp_path / 'ledger'
    led.mkdir(parents=True)
    with io.open(led / 'ledger.jsonl', 'w', encoding='utf-8') as f:
        for cid, text in claims:
            f.write(json.dumps({'type': 'claim', 'id': cid, 'text': text,
                                'topic': 't', 'status': 'pending'}, ensure_ascii=False) + '\n')
    return str(raw), str(led)


def test_长段照旧判定而短段计入未对账(tmp_path):
    raw, led = _mk(tmp_path, [
        ('c-1', '原文『' + LONG + '』与『支撑性』『已接地所以无造假』'),
    ])
    res = vq.check_quotes(led, raw)
    assert res['misses'] == [], res['misses']       # 长段逐字命中
    assert res['checked'] == 1
    assert res['unchecked'] == ['支撑性', '已接地所以无造假']


def test_短段仍然不当成逐字判据(tmp_path):
    """不判它 MISS——判据不变，只是要说"没查"。"""
    raw, led = _mk(tmp_path, [('c-2', '原文『完全捏造』四字标签')])
    res = vq.check_quotes(led, raw)
    assert res['misses'] == [] and res['checked'] == 0
    assert res['unchecked'] == ['完全捏造']


def test_回执不许把未对账段说成全部命中(tmp_path, capsys):
    raw, led = _mk(tmp_path, [('c-3', '原文『' + LONG + '』与『支撑性』')])
    rc = vq.main(['--ledger', led, '--raw', raw])
    out = capsys.readouterr().out
    assert rc == 0
    assert '未对账 1 段' in out, out
    assert '全部逐字命中' not in out, '还有没看的引号段时不许报"全部命中"'


def test_没有短段时才报全部命中(tmp_path, capsys):
    raw, led = _mk(tmp_path, [('c-4', '原文『' + LONG + '』')])
    rc = vq.main(['--ledger', led, '--raw', raw])
    out = capsys.readouterr().out
    assert rc == 0 and '全部逐字命中' in out and '未对账' not in out


def test_发布门把未对账段列为警告而不是沉默(tmp_path):
    """两侧都要断言：有短段→出警告；没短段→不出。只测一边，空实现也能绿。"""
    from validate_report import validate_report

    def run(claims, name):
        raw, led = _mk(tmp_path / name, claims)
        md = ('# 报告\n\n## 执行摘要\n\n摘要内容足够短。\n\n'
              '## 1. 子问题\n\n### 1.1 关键发现\n\n原文引用见账本 [1]。\n\n'
              '### 1.2 来源\n\n| # | 来源 | URL | Tier |\n|---|---|---|---|\n'
              '| 1 | 某文 | file:///' + os.path.relpath(raw, tmp_path).replace('\\', '/') +
              '/body.txt | 1 |\n')
        rep = validate_report(md, ledger_dir=led, raw_dir=raw)
        return rep

    with_short = run([('c-1', '原文『' + LONG + '』与『支撑性』')], 'has-short')
    no_short = run([('c-2', '原文『' + LONG + '』')], 'no-short')
    assert with_short.stats.get('quote_unchecked') == 1
    assert no_short.stats.get('quote_unchecked') == 0
    assert any('短引文未对账' in w for w in with_short.warnings), with_short.warnings
    assert not any('短引文未对账' in w for w in no_short.warnings), no_short.warnings
