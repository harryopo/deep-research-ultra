"""v6.50 回归：三个门盲区，全部来自 v6.49 端到端实跑的系统性审计。

盲区一：引文对账可被一个参数关掉
------------------------------------------------
`validate_report` 里那句 `if raw_dir and rep is not None:`——不传 `--raw`
就完全跳过引文逐字对账。注释写的理由是"许多调研只留摘要级证据"，
但这个前提把两类东西混在了一起：

    · 只到摘要层的 claim        → 该没有逐字引文，不该被要求
    · 声称写了逐字引文的 claim  → 必须有材料能验，否则就是空头承诺

实测（v6.49 审计）：账本里放一条**完全捏造**的引文（"这是一段完全捏造的引文，
从未出现在任何抓取材料里"），补足两个不同域来源让其它检查全部通过，
不传 `--raw` → `✅ 已盖防伪戳`。整条引文对账机制能被一个可选参数关闭。

修法：`raw_dir` 缺失时不再是"不判"，而是"账本里有逐字引文就必须报错"——
查不了材料就不能声称核过，这与 `verify_quotes` 对"无材料"的既有口径一致
（它已经会返回 error 并说"没查过不等于查过了没问题"，只是门没把那个 error
接到不传 `--raw` 的这条路上）。

盲区二：空节报告过门
------------------------------------------------
`_section_missing()` 只看标题行做子串匹配，于是
`## 执行摘要` / `## 调研方法` / `## 结论与建议` / `## 来源`
四个标题下面**一个字都没有**的报告，`passed=True`、issues 为空。
实测确认：这不是推断，是跑出来的。

修法：必需章节改为"标题存在 **且** 该节有实质正文"，空节报 issue。

盲区三：孤证无处可查
------------------------------------------------
`ledger.py status` 只按主题报总数与coverage，不逐条指出
"哪些 claim 只挂了一个注册域、只差一个跨域来源就能升 verified"。
v6.49 实跑里 Lead 是人工翻 82 条 claim、逐个查域，才判断出该派D3X/D2X 两轮
交叉补强——本该是工具报出来的一件事。

修法：`status --needs-cross` 输出逐条孤证清单（claim id / 主题 / 已有域 /
差什么），把"该补交叉"从人的判断变成机械输出。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger  # noqa: E402


# ============================================================
# 工具：孤证检测
# ============================================================

def _seed(tmp_path, rows):
    """rows: [(claim_id, topic, status, [urls...])]"""
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    for cid, topic, status, urls in rows:
        L.add_claim(f'claim {cid}', topic=topic, status=status, claim_id=cid)
        for u in urls:
            L.add_source(cid, u, title='t')
    return L


def test_needs_cross_lists_single_domain_claims(tmp_path):
    L = _seed(tmp_path, [
        ('c-1', '理论', 'pending', ['https://arxiv.org/abs/2401.1']),
        ('c-2', '理论', 'pending', ['https://arxiv.org/abs/2401.2',
                                    'https://aclanthology.org/2024.x/']),
    ])
    got = L.needs_cross_verification()
    ids = {g['claim_id'] for g in got}
    assert ids == {'c-1'}, got
    assert got[0]['domains'] == ['arxiv.org']
    assert 'aclanthology.org' not in got[0]['domains']


def test_needs_cross_skips_verified_and_multi_domain(tmp_path):
    L = _seed(tmp_path, [
        ('c-v', '理论', 'verified', ['https://arxiv.org/abs/1']),
        ('c-m', '理论', 'pending', ['https://arxiv.org/abs/2',
                                    'https://doi.org/10.1/x']),
    ])
    assert L.needs_cross_verification() == []


def test_needs_cross_treats_same_work_two_channels_as_single(tmp_path):
    """档 B 的一手反查（/abs 与 /pdf 同论文）不算两个域——按域计数但要说明。"""
    L = _seed(tmp_path, [
        ('c-p', '理论', 'pending', ['https://arxiv.org/abs/2401.12345',
                                    'https://arxiv.org/pdf/2401.12345']),
    ])
    got = L.needs_cross_verification()
    assert len(got) == 1
    assert got[0]['domains'] == ['arxiv.org'], '同域两通道应折叠成一个域'


def test_needs_cross_reports_how_many_more_domains_needed(tmp_path):
    L = _seed(tmp_path, [('c-1', 'T', 'pending', ['https://arxiv.org/abs/1'])])
    got = L.needs_cross_verification()
    assert got[0]['need_more_domains'] >= 1


def test_needs_cross_ignores_empty_source_claims(tmp_path):
    L = _seed(tmp_path, [('c-0', 'T', 'pending', [])])
    assert L.needs_cross_verification() == []


# ---------------------------------------------------------------- 域归一：不能自己另立一套
def test_needs_cross_treats_api_subdomain_as_same_domain(tmp_path):
    """api.github.com + github.com 是同一份制品的两个入口，不是两个来源。

    v6.50 初版在 needs_cross_verification 里另写了一个只剥 www. 的粗筛，
    把 api.github.com 当独立域，于是这类同源配对被误判成"已跨域"——
    孤证清单会虚报解除。门禁口径只有 `_registered_domain` 一套。
    """
    one = tmp_path / 'one'
    L = _seed(one, [
        ('c-api', 'T', 'pending', ['https://api.github.com/repos/owner/repo']),
    ])
    assert len(L.needs_cross_verification()) == 1, '单源仍是孤证'

    both = tmp_path / 'both'
    L2 = _seed(both, [
        ('c-both', 'T', 'pending', ['https://api.github.com/repos/owner/repo',
                                    'https://github.com/owner/repo']),
    ])
    got = L2.needs_cross_verification()
    assert len(got) == 1, '仓库页 + REST API 折叠成一个域，仍是孤证'
    assert got[0]['domains'] == ['github.com'], got


def test_needs_cross_treats_registry_subdomain_as_same_domain(tmp_path):
    L = _seed(tmp_path, [
        ('c-npm', 'T', 'pending', ['https://registry.npmjs.org/@scope/pkg',
                                   'https://npmjs.com/package/@scope/pkg']),
    ])
    assert L.needs_cross_verification() == []


def test_needs_cross_still_separates_genuinely_different_hosts(tmp_path):
    """归一不能过头：openalex 与 crossref 是真的两个库。"""
    L = _seed(tmp_path, [
        ('c-two', 'T', 'pending', ['https://api.crossref.org/works/10.1/x',
                                  'https://api.openalex.org/works/W1']),
    ])
    assert L.needs_cross_verification() == []


# ============================================================
# 静默无操作：比报错危险
# ============================================================

def test_set_status_rejects_string_claim_ids(tmp_path):
    """`set_status('c-d1-08', ...)` 传字符串会按字符迭代，一个都匹配不上。

    实测返回 0、不报错、账本纹丝不动——Lead 会以为改好了。
    v6.50.1 补那次 cross-verification 时真的踩了：以为 note 写进去了，
    复读账本才发现根本没有。现在直接拒。
    """
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    cid = L.add_claim('原始论断', topic='T')['id']
    with pytest.raises(TypeError) as e:
        L.set_status(cid, status='verified', note='x')
    assert '列表' in str(e.value)
    # 账本没被动过
    c = [x for x in L.export_json()['claims'] if x['id'] == cid][0]
    assert c['status'] == 'pending'


def test_set_status_accepts_single_element_list(tmp_path):
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    cid = L.add_claim('原始论断', topic='T')['id']
    n = L.set_status([cid], status='verified', note='交叉验证 2 来源')
    assert n == 1
    c = [x for x in L.export_json()['claims'] if x['id'] == cid][0]
    assert c['status'] == 'verified'


# ============================================================
# 盲区一：不传 --raw 时，声称逐字的 claim 必须拦
# ============================================================

FABRICATED = ('某论文原文说『这是一段完全捏造的引文，从未出现在任何抓取材料里，'
              '用来验证门的盲区』')


def _make_ledger(tmp_path):
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    L.add_claim(FABRICATED, topic='T', status='verified', claim_id='c-1')
    L.add_source('c-1', 'https://arxiv.org/abs/2401.12345', title='P1')
    L.add_source('c-1', 'https://aclanthology.org/2024.eacl-long.5/', title='P2')
    return L


def _report():
    return (
        '# T\n\n## 执行摘要\n\n摘要带引用 [1]。\n\n'
        '## 调研方法\n\n方法带引用 [1]。\n\n'
        '## 结论与建议\n\n结论需要引用支撑 [1]，这里多写一点让它过长度阈值，'
        '再补一句确保不短。\n\n'
        '## 来源\n\n| 编号 | Tier | 标题 | URL |\n|---|---|---|---|\n'
        '| [1] | 1 | P | https://arxiv.org/abs/2401.12345 |\n'
    )


def test_gate_blocks_fabricated_quote_when_raw_missing(tmp_path):
    """v6.49 实测：不传 --raw 时，这条捏造引文一路盖戳。"""
    from validate_report import validate_report
    L = _make_ledger(tmp_path)
    rpt = tmp_path / 'report.md'
    rpt.write_text(_report(), encoding='utf-8')
    r = validate_report(rpt.read_text(encoding='utf-8'),
                        ledger_dir=str(L.root))
    assert not r.passed, '无 raw 材料 +账本有逐字引文，必须拦'
    assert any('引文' in i or '--raw' in i for i in r.issues), r.issues


def test_gate_allows_claims_without_verbatim_marks_when_raw_missing(tmp_path):
    """纯摘要级 claim（没有逐字标记）不该被逼着提供材料。"""
    from validate_report import validate_report
    L = ResearchLedger(str(tmp_path / 'ledger')).init()
    L.add_claim('该论文研究了规划能力的两维结构', topic='T',
                status='verified', claim_id='c-1')
    L.add_source('c-1', 'https://arxiv.org/abs/2401.12345', title='P1')
    L.add_source('c-1', 'https://aclanthology.org/2024.eacl-long.5/', title='P2')
    rpt = tmp_path / 'report.md'
    rpt.write_text(_report(), encoding='utf-8')
    r = validate_report(rpt.read_text(encoding='utf-8'), ledger_dir=str(L.root))
    assert not any('--raw' in i for i in r.issues), r.issues


def test_gate_still_runs_quote_check_when_raw_given(tmp_path):
    """给了材料就必须真查——这条不能被新逻辑误伤。"""
    from validate_report import validate_report
    L = _make_ledger(tmp_path)
    rpt = tmp_path / 'report.md'
    rpt.write_text(_report(), encoding='utf-8')
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'a.txt').write_text('完全无关的内容', encoding='utf-8')
    r = validate_report(rpt.read_text(encoding='utf-8'),
                        ledger_dir=str(L.root), raw_dir=str(raw))
    assert r.stats.get('quote_misses', 0) >= 1, r.stats


# ============================================================
# 盲区二：空节报告必须拦
# ============================================================

EMPTY_REPORT = '# T\n\n## 执行摘要\n\n## 调研方法\n\n## 结论与建议\n\n## 来源\n'


def test_empty_sections_are_rejected():
    from validate_report import validate_report
    r = validate_report(EMPTY_REPORT)
    assert not r.passed
    assert any('空' in i or '缺' in i for i in r.issues), r.issues


def test_non_empty_report_still_passes_text_only():
    from validate_report import validate_report
    md = (
        '# T\n\n## 执行摘要\n\n摘要内容 [1]。\n\n'
        '## 调研方法\n\n方法内容 [1]。\n\n'
        '## 结论与建议\n\n结论内容 [1]。\n\n'
        '## 来源\n\n| 编号 | 标题 | URL |\n|---|---|---|\n'
        '| [1] | P | https://arxiv.org/abs/1 |\n'
    )
    r = validate_report(md)
    assert not any('空节' in i for i in r.issues), r.issues


def test_heading_only_filler_is_not_a_section_body():
    """节里只有另一个标题行不算有正文。"""
    from validate_report import validate_report
    md = (
        '# T\n\n## 执行摘要\n\n### 子标题而已\n\n'
        '## 调研方法\n\n方法 [1]\n\n'
        '## 结论与建议\n\n结论 [1]\n\n'
        '## 来源\n\n| 编号 | 标题 | URL |\n|---|---|---|\n'
        '| [1] | P | https://arxiv.org/abs/1 |\n'
    )
    r = validate_report(md)
    assert any('空' in i for i in r.issues), r.issues
