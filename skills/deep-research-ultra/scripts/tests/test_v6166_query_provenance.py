"""v6.16.6 回归：引擎改写查询后，账本要记下**实际发出去的那条查询**。

起因（"AI 编码 Agent 的证据溯源做法"实跑后的离线复测）：

`SearchResult.query` 的字段注释写得很清楚——"命中此结果实际发出去的查询（引擎改写查询时
必须记，否则命中不可解释）"，github-deep-search 也确实照做了（长查询会被归一，见
`normalize_repo_query`）。但 `_write_ledger` 对每条证据统一写 Lead 的主题查询，引擎记下的
真实查询在入账那一刻被丢掉。

后果是这条：一个靠 `agent 的证据溯源做法 source` 命中的仓库，在账本里声称自己是靠
`AI 编码 Agent 的证据溯源做法 claim source 可追溯 引用对齐 防幻觉` 搜到的。
一个防幻觉工具在自己的元数据上造假——按账本复现检索时根本复现不出这批命中。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger  # noqa: E402

TOPIC = 'AI 编码 Agent 的证据溯源做法 claim source 可追溯 引用对齐 防幻觉'
ACTUAL = 'agent 的证据溯源做法 source'   # github-deep-search 归一后真正发出去的


class _R:
    def __init__(self, title, url, query=None):
        self.title, self.url = title, url
        self.content = title
        self.engine = 'github-deep-search'
        self.craap_score = {'tier': 3, 'total': 60}
        if query is not None:
            self.query = query


def _evidence(tmp_path, results, query=TOPIC):
    import research
    L = ResearchLedger(str(tmp_path / 'led')).init()
    research._write_ledger(L, results, None, query)
    path = tmp_path / 'led' / 'evidence.jsonl'
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]


def test_engine_recorded_query_is_what_gets_ledgered(tmp_path):
    """引擎记了真实查询 → 账本必须记那条，不能记主题查询。"""
    ev = _evidence(tmp_path, [_R('evidence-harness', 'https://github.com/x/h', query=ACTUAL)])
    assert len(ev) == 1
    assert ev[0]['query'] == ACTUAL, (
        f'账本记的是主题查询 {ev[0]["query"]!r}，不是实际发出的 {ACTUAL!r}——按账本无法复现检索')


def test_topic_query_is_used_when_engine_recorded_none(tmp_path):
    """多数引擎不改写查询、字段留空 → 回落到主题查询，不能留空。"""
    ev = _evidence(tmp_path, [_R('某页面', 'https://a.dev/p')])          # 无 query 属性
    assert ev[0]['query'] == TOPIC
    ev2 = _evidence(tmp_path, [_R('某页面', 'https://a.dev/q', query='')])  # 有空串
    assert ev2[0]['query'] == TOPIC


def test_dict_shaped_results_keep_their_recorded_query(tmp_path):
    """缓存里的 results 是 dict（test_ledger_hygiene 记录过这个形态），同样要保住溯源。"""
    rows = [{'title': '某仓库', 'url': 'https://github.com/x/y', 'content': 'c',
             'engine': 'github-deep-search', 'query': ACTUAL,
             'craap_score': {'tier': 3, 'total': 60}}]
    ev = _evidence(tmp_path, rows)
    assert ev[0]['query'] == ACTUAL
