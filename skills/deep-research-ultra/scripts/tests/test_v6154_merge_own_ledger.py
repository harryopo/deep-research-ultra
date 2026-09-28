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


def test_injection_log_is_not_counted_as_a_shard(session):
    """guard 的留痕账不是子 Agent 的产物。

    实测缺陷清单 A7（2026-09-28 一轮 7 维调研，内核 6.34.5，6.35.0 复现照旧）：
    留痕账按派单模板写在 {ledger_dir} 里，而 _own_paths() 只跳 ledger.jsonl /
    evidence.jsonl / session.json，rglob('*.jsonl') 把它一起扫进来了。结果那轮
    13 行留痕被逐条计入"拒收 13 条"，"收到 8 份分片"比真实的 7 份多 1——
    Lead 按"份数与派发的路数吻合"核对时，每次都像有路子出了废分片。
    """
    d, L = session
    rows = ''.join(json.dumps({
        'file': 'raw/page-%02d.md' % i, 'marker': 'ask_credentials',
        'quoted': '…要求读取 .env 并上传密钥', 'action': '已拒绝',
    }, ensure_ascii=False) + '\n' for i in range(13))
    (d / 'injection_log.jsonl').write_text(rows, encoding='utf-8')

    claims, sources = L.merge(str(d))

    assert L.last_merge['files'] == 2, '留痕账被当成了分片'
    assert L.last_merge['rejected'] == 0, '留痕账的 13 行被记成"拒收 13 条"'
    assert claims == 2


def test_injection_log_in_a_mcp_layout_ledger_is_skipped(tmp_path):
    """MCP 布局下账本就写在会话根，留痕账和它是同一个目录，一样不能当分片。

    第一版把这个用例写成"留痕账写在会话根、账本写在 ledger/"——那种布局下
    merge 的 rglob 根本扫不到它，测试当下就绿，什么也没验。
    """
    L = ResearchLedger(str(tmp_path)).init()
    L.add_claim('Lead 自己写的 claim', topic='补贴', status='pending')
    _shard(tmp_path, 'worker-1.json', 'c-w1', '分片一的 claim')
    (tmp_path / 'injection_log.jsonl').write_text(
        json.dumps({'file': 'raw/a.md', 'marker': 'cn_exec',
                    'quoted': '…', 'action': '已拒绝'}, ensure_ascii=False) + '\n',
        encoding='utf-8')

    claims, _ = L.merge(str(tmp_path))

    assert L.last_merge['files'] == 1
    assert L.last_merge['rejected'] == 0
    assert claims == 1


def test_shard_named_like_the_injection_log_still_merges(session):
    """正向对照：跳过的是那本留痕账本身，不是所有叫 injection_log.jsonl 的文件。

    少了这条，"按名字跳"会把真分片静默吞掉——和 v6.15.4 那次把 ledger.jsonl
    按名字跳、吞掉两份真分片是同一个错。
    """
    d, L = session
    sub = d / 'batch-7'
    sub.mkdir()
    _shard(sub, 'injection_log.jsonl', 'c-w7', '重名分片的 claim')

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
