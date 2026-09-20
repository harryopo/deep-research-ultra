"""X-D15 回归：报告必须有机器戳，不然"我过了校验门"只是一句话。

起因（另一次 effort=deep 实跑，当事人自己认领）：Lead 在写不出报告时，落了一份
带占位内容、并自称「校验门 passed」的 report.md——因为根本没跑校验。
"诚实标注"这条铁律拦不住不跑工具的人。所以把成本抬起来：
戳只能由 validate_report.py 在校验通过后盖上，且戳里带正文指纹；
交付前跑一次 --verify-stamp，没有戳/戳对不上 = 没校验过。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ledger import ResearchLedger
from validate_report import _main

STAMP_RE = re.compile(r'^<!--\s*drux:validated\b.*-->\s*$', re.M)

GOOD = '''# 报告
## 执行摘要
结论A [1] 与结论B [2]。
## 调研范围与方法
多源检索。
## 结论与建议
结论良好。
## 来源
[1] 来源1 https://arxiv.org/0
[2] 来源2 https://arxiv.org/100
'''


@pytest.fixture()
def env(tmp_path):
    """一份能过校验门的报告 + 一个挂了独立来源的账本。"""
    led = ResearchLedger(str(tmp_path / 'ledger')).init()
    c1 = led.add_claim('结论A', '主题A', 'verified', 'general', 0.9)
    c2 = led.add_claim('结论B', '主题A', 'verified', 'general', 0.8)
    for i in range(3):
        led.add_source(c1['id'], f'https://arxiv.org/{i}', tier=1)
        led.add_source(c2['id'], f'https://arxiv.org/{i + 100}', tier=1)
    report = tmp_path / 'report.md'
    report.write_text(GOOD, encoding='utf-8')
    return report, str(tmp_path / 'ledger')


def _stamp(report, ledger_dir):
    return _main(['--report', report, '--ledger', ledger_dir, '--stamp'])


def _verify(report, ledger_dir=None):
    argv = ['--verify-stamp', '--report', report]
    if ledger_dir:
        argv += ['--ledger', ledger_dir]
    return _main(argv)


def _body(report):
    return STAMP_RE.sub('', report.read_text(encoding='utf-8'))


def _edit_body_keep_stamp(report, suffix):
    """改正文但把原有的戳原地留着——这才是"盖完戳又动手"的真实形状。"""
    text = report.read_text(encoding='utf-8')
    stamp = STAMP_RE.search(text)
    new = _body(report).strip() + suffix
    if stamp:
        new += '\n\n' + stamp.group(0).strip() + '\n'
    report.write_text(new, encoding='utf-8')


# ---------------------------------------------------------------------------
# 盖戳
# ---------------------------------------------------------------------------

def test_passing_report_gets_exactly_one_stamp(env):
    report, led = env
    assert _stamp(str(report), led) == 0
    assert len(STAMP_RE.findall(report.read_text(encoding='utf-8'))) == 1


def test_failing_report_never_gets_a_stamp(env):
    """不过门就不许有戳——否则"跑过一次校验"和"随便写的报告"长得一样。"""
    report, led = env
    report.write_text(_body(report).replace('## 来源', '## 附录'), encoding='utf-8')
    assert _stamp(str(report), led) != 0
    assert not STAMP_RE.search(report.read_text(encoding='utf-8'))


def test_restamping_replaces_the_old_one(env):
    report, led = env
    _stamp(str(report), led)
    _stamp(str(report), led)
    text = report.read_text(encoding='utf-8')
    assert len(STAMP_RE.findall(text)) == 1, '重复盖戳会把正文越拖越长'
    assert 'drux:validated' in text


# ---------------------------------------------------------------------------
# 验戳
# ---------------------------------------------------------------------------

def test_untouched_stamped_report_verifies(env):
    report, led = env
    assert _stamp(str(report), led) == 0
    assert _verify(str(report), led) == 0


def test_no_stamp_is_not_validated(env, capsys):
    report, led = env
    assert _verify(str(report), led) != 0
    assert '未校验' in capsys.readouterr().out


def test_editing_the_body_after_stamping_is_detected(env, capsys):
    """戳之后偷偷加一句没来源的话——这正是当初的失效方式。"""
    report, led = env
    _stamp(str(report), led)
    _edit_body_keep_stamp(report, '\n补一句没有来源的断言。')
    assert _verify(str(report), led) != 0
    assert '正文' in capsys.readouterr().out


def test_restamping_after_an_edit_clears_it_again(env):
    """改完重跑 --stamp 必须放行：戳会跟着新正文走，不会把作者锁死。"""
    report, led = env
    _stamp(str(report), led)
    _edit_body_keep_stamp(report, '\n补一句没有来源的断言。')
    assert _stamp(str(report), led) == 0
    assert _verify(str(report), led) == 0


def test_handwritten_stamp_is_rejected(env, capsys):
    """手抄一行戳骗不过：指纹必须对得上正文。"""
    report, led = env
    report.write_text(_body(report) + '\n<!-- drux:validated v=6.11 body=sha256:deadbeef '
                      'claims=99 sources=99 -->\n', encoding='utf-8')
    assert _verify(str(report), led) != 0
    out = capsys.readouterr().out      # readouterr() 会清空缓冲，只许取一次
    assert '伪造' in out or '不符' in out or '手抄' in out


def test_ledger_drift_after_stamping_is_detected(env, capsys):
    """盖完戳再把 claim 降级或往里塞 pending：账本指纹会变。"""
    report, led = env
    assert _stamp(str(report), led) == 0
    ResearchLedger(led).add_claim('事后塞进来的结论', '主题A', 'pending', 'general', 0.3)
    assert _verify(str(report), led) != 0
    assert '账本' in capsys.readouterr().out


def test_verify_without_ledger_only_checks_the_body(env):
    """没带 --ledger 时不许假装查过账本：正文通过就返回通过，但账本那半没查。"""
    report, led = env
    assert _stamp(str(report), led) == 0
    ResearchLedger(led).add_claim('事后塞进来的结论', '主题A', 'pending', 'general', 0.3)
    assert _verify(str(report)) == 0


# ---------------------------------------------------------------------------
# 文档：交付步骤必须写着"先验戳"
# ---------------------------------------------------------------------------

def test_skill_md_requires_the_stamp_before_delivery():
    md = (Path(__file__).resolve().parents[2] / 'SKILL.md').read_text(encoding='utf-8')
    assert '--verify-stamp' in md
    assert '未校验' in md or '没戳' in md
