"""v6.15.4 回归：账本自己不算"子 Agent 分片"，归并回执才数得对。

起因（X-D5）：SKILL.md §归并 让人跑
    ledger.py merge --session {ledger_dir} --dir {ledger_dir}
两个参数同一个目录，而 merge 的目录分支是 `rglob('*.jsonl') + rglob('*.json')`——
`ledger.jsonl` 就在里面。实测一份"1 个真分片 + 账本里已有 1 条 claim"的会话目录：

    合并完成：收到 2 份分片，新增 claim 1 条，source 0 条，去重 1 条，拒收 0 条

"收到 2 份"里那份是账本自己。数据没坏（去重挡住了），但回执数字是给 Lead 核对用的：
文档写着"必须看到 收到 N 份分片 与子 Agent 自报数吻合"，而 N 恒比真实分片多 1，
按吻合判据每次都要"对不上"。会话越大，自己复读自己的"去重 N 条"也越虚。

同一目录分支还顺手扫 `evidence.jsonl`：循环里 `if f.name == self.EVIDENCE: continue`
跳过得对，但 `stats['files']` 已经把它算进去了——同一个错的另一半。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger, _main  # noqa: E402


def _shard(d: Path, name: str, cid: str, text: str) -> None:
    """按文档规定的容器形状写一份子 Agent 分片。"""
    (d / name).write_text(json.dumps({
        'claims': [{'id': cid, 'text': text, 'topic': '补贴', 'status': 'pending'}],
        'sources': [],
    }, ensure_ascii=False), encoding='utf-8')


@pytest.fixture()
def session(tmp_path):
    """一个"已经开过工"的会话目录：账本里有 1 条 claim，旁边躺着 2 份真分片。"""
    d = tmp_path / 'ledger'
    L = ResearchLedger(str(d)).init()
    L.add_claim('Lead 自己写的 claim', topic='补贴', status='pending')
    _shard(d, 'worker-1.json', 'c-w1', '分片一的 claim')
    _shard(d, 'worker-2.json', 'c-w2', '分片二的 claim')
    return d, L


def test_merge_counts_only_real_shards_not_the_ledger_itself(session):
    d, L = session
    claims, sources = L.merge(str(d))

    assert claims == 2                              # 两份分片各 1 条
    assert L.last_merge['files'] == 2               # 不是 3：ledger.jsonl 不算分片


def test_existing_ledger_claim_survives_the_merge(session):
    """正向对照：跳过账本不等于把账本清了。"""
    d, L = session
    L.merge(str(d))

    texts = [c['text'] for c in L.claims()]
    assert texts.count('Lead 自己写的 claim') == 1
    assert '分片一的 claim' in texts


def test_evidence_file_is_not_counted_as_a_shard(session):
    d, L = session
    (d / 'evidence.jsonl').write_text(
        json.dumps({'type': 'evidence', 'claim_id': 'c-w1', 'url': 'https://gov.cn/a'},
                   ensure_ascii=False) + '\n', encoding='utf-8')

    L.merge(str(d))

    assert L.last_merge['files'] == 2               # evidence 不是结论，也不是分片
    assert L.last_merge['rejected'] == 0


def test_shards_in_a_subdir_still_count(session, tmp_path):
    """反向护栏：别为了跳账本把递归扫描砍了。"""
    d, L = session
    sub = d / 'batch-2'
    sub.mkdir()
    _shard(sub, 'worker-3.json', 'c-w3', '子目录里的分片')

    L.merge(str(d))

    assert L.last_merge['files'] == 3
    assert any(c['text'] == '子目录里的分片' for c in L.claims())


def test_a_subdir_shard_named_like_the_ledger_still_merges(session, tmp_path):
    """跳过的是"这个账本自己那个文件"，不是所有叫 ledger.jsonl 的文件。

    第一版按文件名跳，把 tests/test_ledger_hygiene.py 里两份真分片静默吞掉了——
    修回执数字修成丢数据，是更坏的结果。
    """
    d, L = session
    sub = d / 'batch-9'
    sub.mkdir()
    _shard(sub, 'ledger.jsonl', 'c-w9', '重名分片的 claim')

    claims, _ = L.merge(str(d))

    assert claims == 3
    assert any(c['text'] == '重名分片的 claim' for c in L.claims())


def test_cli_receipt_names_the_real_shard_count(session, capsys):
    d, L = session
    rc = _main(['merge', '--session', str(d), '--dir', str(d)])

    out = capsys.readouterr().out
    assert rc == 0
    assert '收到 2 份分片' in out
    assert '收到 3 份分片' not in out
