"""v6.76：conflict 被引用时的提醒（warning，**不阻断**）——含一条钉住裁决的测试。

## 这次挖到的东西

实测（框架第 5 维「冲突处理」）：造一份 1 条 verified + 1 条 conflict 的账本，
报告把 **conflict 那条**当结论写出来 → `passed=True`、0 issues、可盖章交付。

但**这不是"漏检矛盾"**。`validate_report.py` 的注释写明原设计：

    conflict = 两源互斥、已如实并陈（冲突本身是结论，拦它等于禁止报告矛盾，方向反了）

所以允许引用 conflict 是对的。真正的洞更精确：`cited_claim_ids` 用
`(marked if '⚠' in line else unmarked)` 实现"已如实并陈"，而校验 2c 把 `conflict`
放进 `graded` —— 于是 **unmarked 的 conflict 既不阻断、也不产生任何提示**。
要求"如实并陈"写在注释里，**检查却漏了"有没有并陈"**。

## 我第一版做错了（钉在这里）

第一版把它做成 `issue`，结果拦红了已有测试
`test_cited_conflict_claim_is_allowed`：

    冲突本身是结论。拦掉 conflict 等于禁止报告矛盾，方向反了。

同一组里"待补证据"的用例都**显式传了 ⚠ 标记**，唯独 conflict 那个传无标记版本——
**它确立的行为就是"引用 conflict 无需额外标注"**。阻断会禁掉一个合法动作：
Lead 已在别处并陈矛盾、结论行不重复标一遍。

所以降为 warning。`test_it_must_never_become_a_gate` 就是这条裁决的钉子：
下一手看到"引用 conflict 竟能过门"很可能想升级成 issue，那会把一个洞换成另一个洞。

## 第一版实验也无效（记下来）

报告里手写 `[1]`，而账本里 conflict 那条的编号是 `[3]`（skeleton 排的），
校验门拒的是「引用 [1] 无法追溯」——那是编号问题。看到"被拦住了"就宣布防线有效，
是把实验设计的 bug 当成了系统行为。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))


def _run(script, *args):
    r = subprocess.run([sys.executable, str(S / script), *args], cwd=S,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout + r.stderr).strip()


def _fixture(tmp: Path):
    """1 verified（两源互证）+ 1 conflict（互斥未裁决）。"""
    L = tmp / 'ledger'
    L.mkdir()
    steps = [
        ('add-claim', '--text', '框架 A 的召回率高于框架 B', '--id', 'c_ok', '--topic', '效果'),
        ('add-source', '--claim-id', 'c_ok', '--url', 'https://example.org/p1',
         '--title', 'P1', '--tier', '1', '--craap', '80'),
        ('add-source', '--claim-id', 'c_ok', '--url', 'https://dl.acm.org/x',
         '--title', 'P1b', '--tier', '1', '--craap', '75'),
        ('set-status', '--claim-id', 'c_ok', '--status', 'verified', '--note', '两源互证'),
        ('add-claim', '--text', '框架 A 的召回率低于框架 B', '--id', 'c_cf', '--topic', '效果'),
        ('add-source', '--claim-id', 'c_cf', '--url', 'https://example.org/p2',
         '--title', 'P2', '--tier', '1', '--craap', '70'),
        ('set-status', '--claim-id', 'c_cf', '--status', 'conflict', '--note', '与 c_ok 矛盾，未裁决'),
    ]
    for a in steps:
        rc, out = _run('ledger.py', a[0], '--ledger', str(L), *a[1:])
        assert rc == 0, f'{a[0]} 失败：{out[:160]}'
    # 编号必须从 skeleton 读，不能手写——第一版实验就栽在这
    rc, out = _run('skeleton.py', '--ledger', str(L), '-o', str(tmp / 'skel.md'),
                   '--title', '冲突')
    assert rc == 0, out[:200]
    skel = (tmp / 'skel.md').read_text(encoding='utf-8')
    line = next(l for l in skel.splitlines() if 'c_ok' in l and '冲突' in l)
    return L, re.search(r'\[(\d+)\]', line).group(1), line


def _report(tmp: Path, num: str, bluf: str, tag: str):
    p = tmp / f'{tag}.md'
    p.write_text(
        f'# 冲突处理\n\n## 一页拍板\n\n{bluf}\n\n'
        f'## 执行摘要\n\n{bluf}\n\n'
        f'## 调研方法\n\n单次检索，两来源结论相反 [1]。\n\n'
        f'## 结论与建议\n\n据上节证据 [1]。\n\n'
        f'## 来源\n\n[1] https://example.org/p1\n[{num}] https://example.org/p2\n',
        encoding='utf-8')
    return p


def _validate(path, L):
    rc, out = _run('validate_report.py', '--report', str(path), '--ledger', str(L))
    d = json.loads(out)
    real = [i for i in (d.get('issues') or []) if '未申报' not in i]
    warns = d.get('warnings') or []
    return d, real, warns


# ---------------------------------------------------------------------------
# 提醒：引用 conflict 就要说一声
# ---------------------------------------------------------------------------

def test_citing_conflict_without_marker_still_warns(tmp_path):
    """矛盾被写成定论——读者看不出对立面。必须提醒。"""
    L, num, _ = _fixture(tmp_path)
    p = _report(tmp_path, num, f'采用框架 A，其召回率低于框架 B [{num}]。', 'b')
    d, real, warns = _validate(p, L)
    assert any('冲突' in w for w in warns), f'引用了 conflict 却没有任何提醒：{warns}'
    assert d['stats'].get('conflict_cited') == 1, d['stats']
    assert d['stats'].get('conflict_cited_unmarked') == 1, d['stats']


def test_citing_conflict_with_marker_still_warns(tmp_path):
    """如实并陈也要提醒一次——提醒的是"账本里还没裁决"，不是"你没标"。"""
    L, num, _ = _fixture(tmp_path)
    p = _report(tmp_path, num,
                f'⚠️ 来源冲突，未裁决：一说 A 高于 B [1]，一说 A 低于 B [{num}]。', 'a')
    d, real, warns = _validate(p, L)
    assert any('冲突' in w for w in warns), warns
    assert d['stats'].get('conflict_cited_unmarked') == 0, '带 ⚠ 的那行不该算未标注'


def test_not_citing_conflict_leaves_it_quiet(tmp_path):
    """账本里有 conflict 但报告没引用它 → 不该牵连出提醒。"""
    L, num, _ = _fixture(tmp_path)
    p = _report(tmp_path, num, '采用框架 A，其召回率高于框架 B [1]。', 'c')
    d, real, warns = _validate(p, L)
    assert not any('冲突' in w for w in warns), f'没引用 conflict 却报了提醒：{warns}'
    assert d['stats'].get('conflict_cited') == 0, d['stats']


# ---------------------------------------------------------------------------
# 裁决的钉子
# ---------------------------------------------------------------------------

def test_it_must_never_become_a_gate(tmp_path):
    """**这条是本文件存在的理由**，钉的是"不许升级成 issue"。

    第一版就是把它做成 issue，拦红了 `test_cited_conflict_claim_is_allowed`——
    它的 docstring 写着"冲突本身是结论，拦掉 conflict 等于禁止报告矛盾，方向反了"，
    而且同组里"待补证据"的用例都显式传了 ⚠ 标记，唯独 conflict 那个传无标记版本。

    阻断会禁掉一个合法动作：Lead 已在别处并陈矛盾、结论行不重复标一遍。
    下一手看到"引用 conflict 竟能过门"很可能想把它补成 issue——那等于把
    「漏提示」这个洞，换成「禁止报告矛盾」那个更大的洞。
    """
    L, num, _ = _fixture(tmp_path)
    p = _report(tmp_path, num, f'采用框架 A，其召回率低于框架 B [{num}]。', 'g')
    d, real, warns = _validate(p, L)
    assert not real, (
        f'引用 conflict 被判成 issue（阻断）了：{real}\n'
        '依据 test_cited_conflict_claim_is_allowed：'
        '"冲突本身是结论，拦它等于禁止报告矛盾，方向反了"')
    assert any('冲突' in w for w in warns), '可以放过，但不许悄悄放过——提醒必须在'


def test_conflict_stays_in_graded():
    """conflict 仍属于 graded（不算"未验证"），这是原设计，别动。"""
    src = (S / 'validate_report.py').read_text(encoding='utf-8')
    m = re.search(r"graded\s*=\s*\(([^)]*)\)", src)
    assert m, "找不到 graded = (...)"
    assert 'conflict' in m.group(1), (
        f'graded 不含 conflict：{m.group(1)}——'
        '把 conflict 移出 graded 会让它算未验证，那是另一个方向的改法，'
        '且会把"如实并陈矛盾"一起判成未验证')


def test_the_constraint_lives_in_skill_md_not_in_the_gate(tmp_path):
    """"必须并陈矛盾"这条约束落在文档，不落在机器门。

    机器强制会把合法动作一起禁掉，那比漏提示更糟。所以两处都要有：
    SKILL.md 写明写法要求，校验门给 warning。
    """
    md = (REPO / 'skills' / 'deep-research-ultra' / 'SKILL.md').read_text(encoding='utf-8')
    assert 'conflict' in md and '并陈' in md, \
        'SKILL.md 没写"引用 conflict 时正文必须如实并陈矛盾"——' \
        '机器不拦，这条约束就没有落点'