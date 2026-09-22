"""v6.15.3 回归：CLI status 出固定信封 {"topics":…,"totals":…}。

起因（X-D7）：`ledger.py status --session <dir>` 直接把按主题聚合的字典打出去，
顶层键就是主题名——机器解析方（Lead / MCP 工具）既拿不到全局合计，也没法把
"主题键"和"元信息键"分开；主题恰好叫 topics/total 时更是直接撞车。

处理边界要说清楚：**只改 CLI 出口，不改 ResearchLedger.status() 的返回类型**。
status() 的 topic-map 有四个进程内消费者，其中 validate_report 的发布门按
`data['stats']` 迭代主题，动它会把校验门一起改坏；CLI 才是给人和机器解析的那一层。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger, _main  # noqa: E402


@pytest.fixture()
def led(tmp_path):
    """两条主题、四种状态的账本；已验证那条挂两个不同域的独立来源。"""
    L = ResearchLedger(str(tmp_path)).init()
    v = L.add_claim('A 政策已落地', topic='补贴', status='verified')
    L.add_claim('B 补贴口径存疑', topic='补贴', status='conflict')
    L.add_claim('C 技术路线未定', topic='技术', status='pending')
    L.add_claim('D 待补证据', topic='技术', status='supplementing')
    L.add_source(v['id'], 'https://gov.cn/a', title='政策原文', tier=1)
    L.add_source(v['id'], 'https://x.com/b', title='另一家报道', tier=3)
    return L


def _status_json(tmp_path):
    buf_out, buf_err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = buf_out, buf_err
    try:
        rc = _main(['status', '--session', str(tmp_path)])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert rc == 0
    return json.loads(buf_out.getvalue())


def test_cli_status_wraps_topics_in_a_fixed_envelope(tmp_path, led):
    data = _status_json(tmp_path)

    assert set(data) == {'topics', 'totals'}
    assert set(data['topics']) == {'补贴', '技术'}


def test_cli_status_totals_aggregate_every_topic(tmp_path, led):
    totals = _status_json(tmp_path)['totals']

    assert totals == {
        'topics': 2,
        'claims': 4,
        'verified': 1,
        'conflict': 1,
        'supplementing': 1,
        'pending': 1,
        'coverage': 0.25,
        'sufficient_topics': 1,
        'insufficient_topics': ['技术'],
    }


def test_cli_status_topic_flag_still_returns_that_topic_flat(tmp_path, led):
    """只问一个主题时不必套信封——--topic 的语义本来就是"给我这一条"。"""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = _main(['status', '--session', str(tmp_path), '--topic', '补贴'])
    finally:
        sys.stdout = old
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data['claims'] == 2 and data['verified'] == 1


def test_cli_status_unknown_topic_is_an_error_not_an_empty_object(tmp_path, led):
    """`--topic 打错` 原本回 rc=0 + {}，和"这个主题一条 claim 都没有"长得一样。

    主题名只可能来自 claim，所以查不到就是用错了名字——同 v6.15.2 修掉的
    merge 静默 0 条，属同一类"看起来成功了"。
    """
    buf_out, buf_err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = buf_out, buf_err
    try:
        rc = _main(['status', '--session', str(tmp_path), '--topic', '没这个主题'])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert rc == 2
    assert buf_out.getvalue().strip() == ''
    err = buf_err.getvalue()
    assert '没这个主题' in err
    assert '补贴' in err and '技术' in err   # 得把现有主题列出来，不然还是猜


def test_status_api_return_type_is_unchanged(led):
    """正向对照兼防越界：进程内 status() 仍是主题字典，别顺手改成信封。

    validate_report 的发布门按 data['stats'] 迭代主题（validate_report.py:195），
    reflect/report/export_md 同形——改了会把校验门一起改坏。
    """
    api = led.status()
    assert 'topics' not in api and 'totals' not in api
    assert set(api) == {'补贴', '技术'}
    assert api['补贴']['claims'] == 2
