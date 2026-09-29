"""v6.40.0 回归：claim 要能带上"成立范围"，且不许在归并时被静默丢掉。

清单来源（2026-09-29 另一项目的调研流程复盘，`D:/ai/zhixing-reader/docs/research/`）：

- 问题 3：两路子 Agent 给出方向相反的结论，差别全藏在一个限定语里——一路说"没找到仅凭书单
  预测 OCEAN 的效度研究"，另一路引 Ng Annalyn 说"仅凭书目偏好+标签就能预测人格"。都属实，
  因为后者的标签是**读者自己打的**（user-generated），前者问的是"纯书单/平台 genre"。
  两边各自省略了同一个限定词，看起来就像互相打脸。
- 问题 4：子 Agent 报的数字混着"读到正文"与"只看到摘要"——OP-Bench 的 26.2%–61.1% 是
  2026 预印本非同行评议（它没说）；ContextEcho 的 ~80 token 是**代码会话**里的测量，
  迁移到"画像卡长度"属类比（它也没说）。

复盘给的动作是"每条结论后面跟一行成立范围"。但本包的 `add_claim` 是**白名单字段**：
分片里多写的键会在 merge 时被静默丢掉。所以这条必须走字段链
（分片 → add_claim → ledger.jsonl → skeleton 渲染），否则文档写一句空承诺。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger  # noqa: E402

import skeleton  # noqa: E402


@pytest.fixture()
def session(tmp_path):
    d = tmp_path / 'ledger'
    yield ResearchLedger(str(d)).init(), d


def _shard(d, name, claim):
    (d / name).write_text(json.dumps(
        {'claims': [claim], 'sources': []}, ensure_ascii=False), encoding='utf-8')


def test_add_claim_keeps_scope(session):
    L, _ = session
    entry = L.add_claim('仅凭书目偏好就能预测人格', topic='画像',
                        scope='样本=用户自打标签的 Goodreads 数据；非纯书单；2017 非同行评议')
    assert entry['scope'].startswith('样本='), entry


def test_merge_carries_scope_from_shard(session):
    L, d = session
    _shard(d, 'D1.json', {
        'id': 'c-s-01', 'text': '掉分 26.2%–61.1%', 'topic': '基准', 'status': 'pending',
        'scope': '预印本 2026，非同行评议；测量对象是长上下文任务'})
    L.merge(str(d))

    row = [c for c in L.claims() if c['id'] == 'c-s-01'][0]
    assert row['scope'] == '预印本 2026，非同行评议；测量对象是长上下文任务', row


def test_merge_without_scope_stays_empty(session):
    """正向对照：不带 scope 的老分片照常入账，字段是空串而不是 None 或崩。"""
    L, d = session
    _shard(d, 'D2.json', {'id': 'c-s-02', 'text': '没有成立范围的结论', 'topic': '基准'})

    L.merge(str(d))

    row = [c for c in L.claims() if c['id'] == 'c-s-02'][0]
    assert row['scope'] == '', row


def test_skeleton_prints_scope(session):
    """渲染：成立范围要跟着结论走，否则读者只剩一个裸百分比。"""
    L, d = session
    _shard(d, 'D3.json', {
        'id': 'c-s-03', 'text': '自评准确率 46.4%', 'topic': '自评', 'status': 'verified',
        'scope': '二手转述，未读原文'})
    L.merge(str(d))

    md = skeleton.build_skeleton(str(d), title='测试主题')

    assert '成立范围：二手转述，未读原文' in md, md[:800]


def test_skeleton_omits_label_when_no_scope(session):
    """没写成立范围时不许印一个空标签骗人。"""
    L, d = session
    _shard(d, 'D4.json', {'id': 'c-s-04', 'text': '普通结论', 'topic': '基准',
                          'status': 'verified'})
    L.merge(str(d))

    md = skeleton.build_skeleton(str(d), title='测试主题')

    assert '成立范围' not in md, md[:600]
