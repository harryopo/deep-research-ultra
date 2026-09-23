"""v6.15.5 回归：`add-source` 也要卡"点不回原文"，别让假溯源进账本占引用编号。

起因（X-D16）：清单原话是"export 没有 --filter，取不到『只带绝对 URL 且已挂源』的
干净子集"。前半句属实（export 只有 --format/--out），但实测下来该修的不是导出：

    ledger.py add-source --url '/link?url=abc123'   → rc=0，写进去了
    ledger.py add-source --url '见前面报告'          → rc=0，写进去了
    ledger.py status --topic 补贴                    → independent_sources=3, sufficient=True
    ledger.py export                                 → sources urls=['/link?url=abc123',
                                                        '见前面报告', 'https://gov.cn/a']
                                                        primary_index 1/2/3

`_is_traceable()`（站内相对链接、javascript:、口头指代一律不算来源）只挂在
`add_evidence` 和 `merge` 两条写入路径上，Lead 自己直写的 `add_source` 是第三条，漏了。
而 SKILL.md §报告骨架 明写附录登记表来自"source 条目全量"、编号取 `primary_index`
——所以一条点不开的字符串会拿到 [1] 号，报告必须把它列进引用登记表。
导出侧加 --filter 只是把脏数据藏起来，写入侧封口才是"export 给的就是干净子集"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger, _main  # noqa: E402

REL = '/link?url=abc123'
PROSE = '见前面报告'
GOOD = 'https://gov.cn/a'


@pytest.fixture()
def led(tmp_path):
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    c = L.add_claim('补贴撬动比 1:2.3', topic='补贴', status='pending')
    return L, c['id']


def _urls(L) -> list:
    return [e['url'] for e in L._all() if e.get('type') == 'source']


# ---------------------------------------------------------------- 写入侧封口
def test_relative_link_is_not_a_source(led):
    L, cid = led
    with pytest.raises(ValueError) as e:
        L.add_source(cid, REL)
    assert REL in str(e.value)                # 要点名是哪条，不能只说"不合法"
    assert _urls(L) == []


def test_prose_reference_is_not_a_source(led):
    L, cid = led
    with pytest.raises(ValueError):
        L.add_source(cid, PROSE)
    assert _urls(L) == []


def test_empty_url_is_still_refused(led):
    """原来单独有一句『source url 不能为空』，并入可点击性判定后不能漏。"""
    L, cid = led
    with pytest.raises(ValueError):
        L.add_source(cid, '   ')


def test_absolute_url_still_writes(led):
    """正向对照：别把真来源一起挡了。"""
    L, cid = led
    entry = L.add_source(cid, GOOD, title='政策原文', tier=1)
    assert entry['url'] == GOOD
    assert _urls(L) == [GOOD]


# ---------------------------------------------------------------- 实际危害
def test_junk_urls_do_not_inflate_independent_sources(led):
    """实测改前 independent_sources=3、sufficient=True：两条点不开的也算独立来源。"""
    L, cid = led
    for bad in (REL, PROSE):
        with pytest.raises(ValueError):
            L.add_source(cid, bad)
    L.add_source(cid, GOOD)

    s = L.status('补贴')
    assert s['independent_sources'] == 1
    assert s['sufficient'] is False           # 单源就是没够，别用假源凑成"充分"


def test_export_numbers_only_clickable_sources(led):
    """X-D16 的收口判据：export 的 primary_index 不再发给点不开的来源。"""
    L, cid = led
    with pytest.raises(ValueError):
        L.add_source(cid, REL)
    L.add_source(cid, GOOD)
    L.add_source(cid, 'https://news.cn/b', title='另一家报道')

    data = L.export_json()
    assert [s['primary_index'] for s in data['sources']] == [1, 2]
    assert all(s['url'].startswith('https://') for s in data['sources'])


# ---------------------------------------------------------------- CLI 回执
def test_cli_add_source_refuses_without_traceback(led, tmp_path, capsys):
    L, cid = led
    capsys.readouterr()

    rc = _main(['add-source', '--session', str(L.root),
                '--claim-id', cid, '--url', REL])

    buf = capsys.readouterr()
    assert rc == 2
    assert REL in buf.err
    assert 'Traceback' not in buf.out and buf.out.strip() == ''
    assert _urls(L) == []
