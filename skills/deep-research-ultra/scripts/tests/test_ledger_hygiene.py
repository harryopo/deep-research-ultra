"""X-D4 回归：搜索结果不是 claim，merge 不得把噪声收进主账本。

起因（另一次 effort=deep 实跑，4 session / 23 子问题）：
- `research.py --ledger` 给每条搜索结果建一条 claim，文本就是页面标题，
  于是 `shbnq422/cv (⭐5)` 这种空仓库、搜狗微信的培训班广告都成了"论断"；
- 站内相对链接（`/link?url=...`）成了"来源"，根本点不回原文；
- 子 Agent 自报 claim 合计约 391 条，merge 后变 602 条——差额几乎全是上面两类噪声，
  而它们进了覆盖率与报告引用统计。

还有一条是写这批测试时才发现的：`merge` 对缺 status 的记录默认给 `verified`，
等于合并动作可以自己批准自己的结论。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger  # noqa: E402


class _R:
    """最小搜索结果替身（字段与 SearchResult 一致）。"""

    def __init__(self, title, url, engine='sogou-weixin', tier=3, craap=40):
        self.title, self.url = title, url
        self.content = title
        self.engine = engine
        self.craap_score = {'tier': tier, 'total': craap}


def _write(L, results, query='主题', **kw):
    import research
    return research._write_ledger(L, results, None, query, **kw)


# ---------------------------------------------------------------------------
# ① 落盘的是证据，不是 claim
# ---------------------------------------------------------------------------

def test_search_results_land_as_evidence_not_claims(tmp_path):
    L = ResearchLedger(str(tmp_path / 'led')).init()
    _write(L, [_R('LangChain 入门 - 某某培训班', 'https://x.dev/a'),
               _R('shbnq422/cv (⭐5)', 'https://github.com/shbnq422/cv')])
    assert L.claims() == [], '引擎抓回的页面标题不是论断，不能自动进 claim 表'
    ev = list(_lines(tmp_path / 'led' / 'evidence.jsonl'))
    assert [e['url'] for e in ev] == ['https://x.dev/a', 'https://github.com/shbnq422/cv']


def test_auto_claim_is_opt_in_and_keeps_legacy_behaviour(tmp_path):
    L = ResearchLedger(str(tmp_path / 'led')).init()
    _write(L, [_R('某论文标题', 'https://a.dev/p')], auto_claim=True)
    assert len(L.claims()) == 1, '--auto-claim 显式要了就得给（老流程不能悄悄断）'


def test_untraceable_urls_are_not_recorded_as_evidence(tmp_path):
    """站内相对链接（/link?url=...）点不回原文，记进账本只会伪装成可溯源。"""
    L = ResearchLedger(str(tmp_path / 'led')).init()
    _write(L, [_R('培训班广告', '/link?url=abc123'), _R('真来源', 'https://a.dev/p')])
    ev = list(_lines(tmp_path / 'led' / 'evidence.jsonl'))
    assert [e['url'] for e in ev] == ['https://a.dev/p']


def test_result_can_be_a_plain_dict_too(tmp_path):
    """引擎有时回对象、有时回 dict（缓存里的 results 就是 dict）；
    取字段只认一种形态会把整批结果静默吞掉——实测过一次：4 条全报写入失败。"""
    L = ResearchLedger(str(tmp_path / 'led')).init()
    rows = [{'title': '某个页面', 'url': 'https://a.dev/p', 'content': 'c',
             'craap_score': {'tier': 2, 'total': 60}}]
    assert _write(L, rows)['evidence'] == 1


# ---------------------------------------------------------------------------
# ② merge 的卫生
# ---------------------------------------------------------------------------

def test_merge_does_not_reingest_evidence_records(tmp_path):
    src = tmp_path / 'sub'
    L = ResearchLedger(str(src)).init()
    _write(L, [_R('某个页面标题', 'https://a.dev/p')])
    main = ResearchLedger(str(tmp_path / 'main')).init()
    added_c, added_s = main.merge(str(src))
    assert (added_c, added_s) == (0, 0), '证据记录不是 claim，不能被 merge 收编'
    assert main.claims() == []


def test_merge_never_mints_verified_from_a_missing_status(tmp_path):
    src = tmp_path / 'sub'
    src.mkdir()
    _dump(src / 'claims.jsonl', [
        {'type': 'claim', 'id': 'c-1', 'text': '未经交叉验证的说法'},
    ])
    main = ResearchLedger(str(tmp_path / 'main')).init()
    main.merge(str(src))
    got = main.claims()[0]
    assert got['status'] == 'pending', f"合并动作不能自己批准结论：{got['status']}"


def test_merge_rejects_sources_without_an_absolute_url(tmp_path):
    src = tmp_path / 'sub'
    src.mkdir()
    _dump(src / 'ledger.jsonl', [
        {'type': 'claim', 'id': 'c-1', 'text': '结论', 'status': 'pending'},
        {'type': 'source', 'claim_id': 'c-1', 'url': '/link?url=abc', 'title': '广告'},
        {'type': 'source', 'claim_id': 'c-1', 'url': 'https://real.dev/p', 'title': '真源'},
    ])
    main = ResearchLedger(str(tmp_path / 'main')).init()
    added_c, added_s = main.merge(str(src))
    assert added_c == 1
    assert added_s == 1, '相对链接来源必须拒收，否则账本假装可溯源'
    assert main.last_merge['rejected'] == 1


def test_merge_reports_added_deduped_rejected(tmp_path):
    src = tmp_path / 'sub'
    src.mkdir()
    rows = [{'type': 'claim', 'id': 'c-1', 'text': 'A', 'status': 'pending'},
            {'type': 'claim', 'id': 'c-1', 'text': 'A', 'status': 'pending'},
            {'type': 'source', 'claim_id': 'c-1', 'url': 'mailto:x', 'title': '怪'}]
    _dump(src / 'ledger.jsonl', rows)
    main = ResearchLedger(str(tmp_path / 'main')).init()
    main.merge(str(src))
    st = main.last_merge
    assert (st['claims'], st['deduped'], st['rejected']) == (1, 1, 1), st


# ---------------------------------------------------------------------------
# ③ 命令行入口（parser 在 main() 里构造，所以走 --help 端到端取文案）
# ---------------------------------------------------------------------------

def _cli_help():
    import subprocess
    out = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent
                                             / 'research.py'), '--help'],
                         capture_output=True, text=True, encoding='utf-8',
                         cwd=str(Path(__file__).resolve().parent.parent))
    assert out.returncode == 0, out.stderr[-400:]
    return out.stdout


def test_auto_claim_flag_exists_and_says_what_it_costs():
    """旋钮不加解释，使用者就会照抄示例把它打开——文案必须说清默认关闭的理由。"""
    help_text = _cli_help()
    assert '--auto-claim' in help_text
    # usage 行也列了这个旗标，要看的是选项区（最后一次出现）后面的说明
    desc = help_text.rsplit('--auto-claim', 1)[-1][:400]
    assert ('标题' in desc or '噪声' in desc), desc
    assert '默认关闭' in desc, desc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _lines(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            yield json.loads(line)


def _dump(path: Path, rows):
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows),
                    encoding='utf-8')
