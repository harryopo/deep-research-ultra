"""v6.39.0 回归：每维度 claim 上限要能调，但默认仍是 12。

报告 A19 / B-3（2026-09-29 一轮实跑）：8 个维度全部正好 12 条＝撞上限，D2/D6/D7 各自回报
"还有料没记"。上限本意是防"分母撑大、分子不涨"（实测 deep 档 8×12 条覆盖率 0.89，
standard 档 5×32 条同样两人逐字回验只剩 0.46），但在证据密集的维度上它变成了静默截断。

取舍不能由工具替 Lead 做死：判据保留（超上限必须点名），**数值放开成参数**。
默认值不动——把默认调高等于把这条产能红线撤了，而红线是量出来的。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger, _main  # noqa: E402


def _shard(d: Path, name: str, n: int) -> None:
    claims = [{'id': f'{name[:2]}-{i:02d}', 'text': f'第 {i} 条结论',
               'topic': '上限', 'status': 'pending'} for i in range(1, n + 1)]
    (d / name).write_text(json.dumps({'claims': claims, 'sources': []},
                                     ensure_ascii=False), encoding='utf-8')


@pytest.fixture()
def session(tmp_path):
    d = tmp_path / 'ledger'
    ResearchLedger(str(d)).init()
    return d


def test_default_cap_still_warns_at_13(session, capsys):
    """默认不许漂：第 13 条仍然点名超上限。"""
    _shard(session, 'D1-a.json', 13)

    ResearchLedger(str(session)).merge(str(session))

    err = capsys.readouterr().err
    assert '超每维度上限 12 条' in err, err


def test_raised_cap_lets_16_through_without_warning(session, capsys):
    """显式调到 16 时，13-16 条不再被当成超标。"""
    _shard(session, 'D1-b.json', 16)

    L = ResearchLedger(str(session))
    claims, _ = L.merge(str(session), claim_cap=16)

    assert claims == 16, claims
    err = capsys.readouterr().err
    assert '超每维度上限' not in err, err


def test_lowered_cap_warns_earlier(session, capsys):
    """反向也要成立：调低到 8 时，第 9 条就该被点名——证明数值真在起作用，不是摆设。"""
    _shard(session, 'D1-c.json', 10)

    ResearchLedger(str(session)).merge(str(session), claim_cap=8)

    err = capsys.readouterr().err
    assert '超每维度上限 8 条' in err, err
    assert '收到 10 条' in err, err


def test_cli_flag_accepts_a_number_and_rejects_junk(session, capsys):
    _shard(session, 'D1-d.json', 14)

    rc = _main(['merge', '--session', str(session), '--dir', str(session),
                '--claim-cap', '20'])
    assert rc == 0, capsys.readouterr().out

    rc2 = _main(['merge', '--session', str(session), '--dir', str(session),
                 '--claim-cap', '很多'])
    assert rc2 == 2, '非数字的上限必须报错退出，不能静默按默认跑'
    assert '--claim-cap' in capsys.readouterr().err
