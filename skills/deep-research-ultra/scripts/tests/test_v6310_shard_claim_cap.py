"""v6.31.0 回归：一份分片的 claim 数要看得见地超限，且文档与代码同一个数。

实跑量出来的产能账（同一套判据、同样两名复核员）：

| 轮次 | effort | 维度 | claim 总数 | 每维度 | 覆盖率 |
|------|--------|------|-----------|--------|--------|
| 2026-09-24 | deep | 8 | 93 | ≈12 | 0.89 |
| 2026-09-26 | standard | 5 | 158 | ≈32 | 0.46 |

覆盖率塌下去不是因为证据变差，是因为**每维度写进账本的条数超出了 Lead 一轮内能逐字回验的量**——
每多一条没核验的 claim，分母就大一分，而分子只按"真验过"涨。所以：
1. 派单模板要给死每维度上限（防）；
2. `merge` 在归并回执里点名超标的分片（查）——Lead 看到才能决定是砍条数还是补核验，
   而不是等发布门把覆盖率打下来才发现。

上限值由代码给常量、文档引用它，两边不许各写一个数（有测试钉住）。
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import SKILL_MD, ResearchLedger  # noqa: E402

CAP = ResearchLedger.SHARD_CLAIM_CAP


def _shard(d: Path, name: str, n: int) -> None:
    claims = [{'id': f'c-x-{i:02d}', 'text': f'第 {i} 条事实，带逐字引文「原文 {i}」',
               'topic': '上限测试', 'status': 'pending'} for i in range(1, n + 1)]
    sources = [{'claim_id': c['id'], 'url': f'https://example.com/{i}',
                'title': 't', 'tier': 2} for i, c in enumerate(claims)]
    (d / name).write_text(json.dumps({'claims': claims, 'sources': sources},
                                     ensure_ascii=False), encoding='utf-8')


@pytest.fixture()
def session(tmp_path):
    d = tmp_path / 'ledger'
    d.mkdir()
    ResearchLedger(str(d)).init()
    return d


def _merge(d: Path) -> None:
    ResearchLedger(str(d)).merge(str(d))


def test_超标分片要在回执里点名(session, capsys):
    """该发生的必须真发生：13 条要报警，而且点名到文件。"""
    _shard(session, 'D1.json', CAP + 1)
    _merge(session)
    err = capsys.readouterr().err
    assert 'D1.json' in err and '超' in err, f'没点名超标分片：{err!r}'
    assert str(CAP + 1) in err, '回执要带上实际条数，Lead 才知道差多少'


def test_条数不许被静默丢弃(session):
    """报警不是砍条数：13 条仍全部入账，怎么处置由 Lead 决定。"""
    _shard(session, 'D1.json', CAP + 1)
    led = ResearchLedger(str(session))
    led.merge(str(session))
    assert len(led.claims()) == CAP + 1


def test_上限内不误报(session, capsys):
    _shard(session, 'D2.json', CAP)
    _merge(session)
    err = capsys.readouterr().err
    assert 'D2.json' not in err, f'刚好达标的分片被误报：{err!r}'


def test_重跑_merge_也要继续点名(session, capsys):
    """上限量的是"这个维度写了多少条"，不是"这次新增几条"。

    实测反例：本会话首次 merge 后账本已有 158 条，再跑一次 merge 时 5 份分片全走
    去重通道（回执"新增 claim 0 条，去重 436 条"），按新增计数就一声不响——
    Lead 重跑一次反而看不见超标。
    """
    _shard(session, 'D3.json', CAP + 3)
    _merge(session)                       # 首次：入账
    capsys.readouterr()
    _merge(session)                       # 重跑：全部去重
    err = capsys.readouterr().err
    assert 'D3.json' in err and '超' in err, f'重跑 merge 丢了超标告警：{err!r}'


def test_skill_md_写的上限与代码同一个数():
    """文档里"每维度 ≤N 条"的 N 必须等于代码常量——两边各写一个数就一定会漂。"""
    text = SKILL_MD.read_text(encoding='utf-8')
    nums = [int(m) for m in re.findall(rf'每维度\s*≤\s*(\d+)\s*条', text)]
    assert nums, 'SKILL.md 里没有"每维度 ≤N 条 claim"这条派单约束'
    assert set(nums) == {CAP}, f'SKILL.md 写了 {nums}，代码常量是 {CAP}'
