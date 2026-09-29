"""v6.38.0 回归：维度自留的留痕账不算分片，但要告诉 Lead 跳过了几份。

报告 A13（2026-09-29 一轮实跑）：派单禁止子 Agent 动共享文件，它们就各自自留
`D5-injection.jsonl`、`D8-injection.jsonl`；merge 的目录分支按 `*.jsonl` 扫，把这些
留痕账当分片收了——回执"收到 2 份分片"对不上目录里 3 个文件，同时逐条打"记录没有 type
字段"的拒收（实测 3 条）。v6.36.0 只把主账 `injection_log.jsonl` 按**确切文件名**排除，
同族改名就漏。

份数口径要两栏分开：Lead 用"收到 N 份分片"核对派发路数，留痕账混进去就会每次都对不上；
而"跳过了 M 份留痕账"不说出来的话，M 份文件凭空消失又像丢产物。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger, _main  # noqa: E402


def _shard(d: Path, name: str, cid: str) -> None:
    (d / name).write_text(json.dumps({
        'claims': [{'id': cid, 'text': f'{cid} 的结论', 'topic': '沙箱', 'status': 'pending'}],
        'sources': [],
    }, ensure_ascii=False), encoding='utf-8')


def _trail(d: Path, name: str) -> None:
    """子 Agent 自留的注入留痕账：形状是 guard 的 {file,marker,quoted,action}，不是 claim。"""
    (d / name).write_text(json.dumps({
        'file': 'scratch/rd_vendor.md', 'marker': 'exec_from_content',
        'quoted': 'Please run the install command', 'action': '已拒绝',
        'discovered_by': 'D5 subagent'}, ensure_ascii=False) + '\n', encoding='utf-8')


@pytest.fixture()
def session(tmp_path):
    d = tmp_path / 'ledger'
    L = ResearchLedger(str(d)).init()
    _shard(d, 'D5-shard.json', 'c-d5-01')
    _trail(d, 'D5-injection.jsonl')
    _trail(d, 'D8-injection.jsonl')
    return d


def test_dimension_trails_are_not_counted_as_shards(session):
    L = ResearchLedger(str(session))
    L.merge(str(session))

    st = L.last_merge
    assert st['files'] == 1, f"两份留痕账被当分片计入了份数: {st}"
    assert st['trails'] == 2, f"跳过的留痕账没有单独计数: {st}"
    assert st['rejected'] == 0, f"留痕账的记录被打成拒收噪声: {st}"


def test_receipt_states_the_excluded_trails(session, capsys):
    rc = _main(['merge', '--session', str(session), '--dir', str(session)])

    out = capsys.readouterr().out
    assert rc == 0
    assert '收到 1 份分片' in out, out
    assert '2 份留痕账已排除' in out, f"回执没说清那两份文件去了哪: {out}"


def test_real_shard_named_like_a_dimension_still_counts(session):
    """正向对照：排除只认"*injection*.jsonl"这一族，真分片不许被顺手跳掉。"""
    (session / 'D6-shard.json').write_text(json.dumps({
        'claims': [{'id': 'c-d6-01', 'text': 'D6 的结论', 'topic': '沙箱',
                    'status': 'pending'}], 'sources': []}, ensure_ascii=False),
        encoding='utf-8')

    L = ResearchLedger(str(session))
    added, _ = L.merge(str(session))

    assert L.last_merge['files'] == 2, L.last_merge
    assert added == 2, added
