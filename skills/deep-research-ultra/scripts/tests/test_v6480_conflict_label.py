"""v6.48：conflict 的标签要说"这条冲突有没有留过取舍"，不能一律写"待裁决"。

起因是实跑：第七轮把三组冲突按原文裁决完、把取舍写进账本并留了 note，
但报告骨架仍把每条 conflict 印成「⚠️ 冲突待裁决」——交付物于是对过程状态撒了谎：
读的人会以为 Lead 还没给结论，而账本里每一条都记着取舍依据。

约束加在判定表上，不加在文风上（同一套规则不许只改一半）：
- 有 note 的 conflict → 标签带出账本留痕，读者能直接看到"已给取舍、内容是什么"；
- 没有 note 的 conflict → 照实写「未裁决」；
- 状态汇总行不再断言"待裁决"，只报冲突条数。
status 本身不变（两侧来源仍旧互相矛盾，裁决是口径取舍，不是新的证据）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ledger import ResearchLedger  # noqa: E402
from skeleton import build_skeleton  # noqa: E402


@pytest.fixture()
def led(tmp_path):
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    ruled = L.add_claim('甲方说零造假，乙方说 17%-33%', '口碑', 'conflict', 'skeptic', 0.5)
    L.add_source(ruled['id'], 'https://doi.org/10.1000/a', title='甲', tier=1)
    L.set_status([ruled['id']], 'conflict',
                 note='第七轮裁决：对象与分母不同，不互斥、不外推')
    open_case = L.add_claim('提示诱发还是模型固有', '机理', 'conflict', 'skeptic', 0.4)
    L.add_source(open_case['id'], 'https://doi.org/10.1000/b', title='乙', tier=1)
    return L


def _only(md: str, needle: str) -> str:
    """取包含 needle 的那一行；取不到就把整份骨架摊出来，别让 StopIteration 当报错。"""
    hits = [l for l in md.splitlines() if needle in l]
    assert len(hits) == 1, f'找不到唯一含 {needle!r} 的行：{hits}\n---\n{md}'
    return hits[0]


def test_有留痕的冲突不再被印成待裁决(led):
    md = build_skeleton(str(led.root))
    line = _only(md, '零造假')
    assert '待裁决' not in line, line
    assert '不互斥、不外推' in line, line       # 取舍内容直接可见
    assert '来源冲突' in line, line


def test_没留痕的冲突照实写未裁决(led):
    md = build_skeleton(str(led.root))
    line = _only(md, '提示诱发')
    assert '未裁决' in line, line
    assert '来源冲突' in line, line


def test_汇总行不断言全部待裁决(led):
    md = build_skeleton(str(led.root))
    stat = _only(md, 'claims 2')
    assert '待裁决' not in stat, stat
    assert '来源冲突 2' in stat, stat
