"""2026-09-30 v6.42 端到端实跑（4 路子 Agent / 67 claim / 17 verified）交回的缺陷。

17 条 verified 里有 3 条是子 Agent 自己标成待办登记的条目
（c-d1-19「【未复核】【待办】以…」、c-d1-20、c-d3-12「【待办 claim，禁止当结论用】…」）：
它们手上确实有 ≥2 个不同域名的来源，于是机械档 A 把「待办登记」升成了「已验证结论」，
skeleton 就把它们当结论渲染进报告（不带 ⚠️）。

判据一句话：一条 claim 自己声明"没核实过"，就不可能被交叉验证判成"已核实"。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import ResearchLedger  # noqa: E402

ABS_URL = 'https://arxiv.org/abs/2509.20364'
PDF_URL = 'https://arxiv.org/pdf/2509.20364'


def _led(tmp_path):
    return ResearchLedger(str(tmp_path / 'ledger')).init()


def _two_host_sources(L, cid):
    L.add_source(cid, ABS_URL)
    L.add_source(cid, 'https://doi.org/10.1234/whatever')


# 子 Agent 实际写过的两种形态，一种紧挨括号、一种在括号里带说明
TODO_TEXTS = [
    '【未复核】【待办】以全文抓取补 0-3 量表各级判据，本轮未做',
    '【待办 claim，禁止当结论用】(A) 三仓库均无使用证据；本轮未安装、未运行',
]


@pytest.mark.parametrize('text', TODO_TEXTS)
def test_todo_claim_is_not_promoted_by_set_status(tmp_path, capsys, text):
    from ledger import _main
    L = _led(tmp_path)
    c = L.add_claim(text, 'D1', 'pending')
    _two_host_sources(L, c['id'])
    _main(['set-status', '--session', str(L.root),
           '--claim-id', c['id'], '--status', 'verified',
           '--note', '交叉验证 2 独立来源'])
    got = [x for x in L.export_json()['claims'] if x['id'] == c['id']][0]
    assert got['status'] == 'pending', '自己标了待办的条目不该被升成 verified'
    assert not got.get('promoted_at')


@pytest.mark.parametrize('text', TODO_TEXTS)
def test_refusal_names_the_claim_and_the_way_out(tmp_path, capsys, text):
    from ledger import _main
    L = _led(tmp_path)
    c = L.add_claim(text, 'D1', 'pending')
    _two_host_sources(L, c['id'])
    capsys.readouterr()
    _main(['set-status', '--session', str(L.root),
           '--claim-id', c['id'], '--status', 'verified'])
    err = capsys.readouterr().err
    assert c['id'] in err, '要点名是哪条被拒，不能只给一个总数'
    assert '待办' in err and ('核实' in err or '去掉' in err), \
        '拒绝理由要教 Lead 下一步怎么做'


def test_the_rest_of_the_batch_is_not_collateral_damage(tmp_path, capsys):
    """一条待办不该把同批的正当升级一起挡掉——Lead 是按维度成批升级的。"""
    from ledger import _main
    L = _led(tmp_path)
    ok = L.add_claim('论文原文说 X（逐字引文）', 'D1', 'pending')
    todo = L.add_claim(TODO_TEXTS[0], 'D1', 'pending')
    for cid in (ok['id'], todo['id']):
        _two_host_sources(L, cid)
    _main(['set-status', '--session', str(L.root),
           '--claim-id', f"{ok['id']},{todo['id']}", '--status', 'verified'])
    claims = {x['id']: x for x in L.export_json()['claims']}
    assert claims[ok['id']]['status'] == 'verified'
    assert claims[todo['id']]['status'] == 'pending'


def test_verify_primary_channel_is_closed_too(tmp_path, capsys):
    """档 B（一手来源 + 反查）走的是同一个出口，不能留第二个口子。"""
    L = _led(tmp_path)
    c = L.add_claim(TODO_TEXTS[0], 'D1', 'pending')
    L.add_source(c['id'], ABS_URL)
    assert L.verify_primary([c['id']], PDF_URL, method='fulltext-read') == 0
    got = [x for x in L.export_json()['claims'] if x['id'] == c['id']][0]
    assert got['status'] == 'pending'
    assert not got.get('verify_method')


def test_demoting_a_todo_claim_still_works(tmp_path):
    """只拦「升成 verified」；把待办条目降回 pending 是合规动作。"""
    L = _led(tmp_path)
    c = L.add_claim(TODO_TEXTS[0], 'D1', 'pending')
    assert L.set_status([c['id']], 'pending', note='维持待办') == 1


def test_clean_claim_still_upgrades(tmp_path):
    L = _led(tmp_path)
    c = L.add_claim('论文原文说 X（逐字引文）', 'D1', 'pending')
    _two_host_sources(L, c['id'])
    assert L.set_status([c['id']], 'verified', note='交叉验证 2 独立来源') == 1
