"""v6.64.0：SKILL.md 的信息架构——手册搬走、约束前置，且不许出现两份。

背景（体检 P1-9）：SKILL.md 实测 1942 行 ≈27k tokens。问题是物理的，不是 Lead
不听话——**铁律在第 1234 行、禁止行为在第 1829 行**，都在全文最后三分之一。
上下文一长，最先被稀释的就是结尾；而约束恰恰是最不能被稀释的东西。

这次做了两件事，性质不同：
1. **搬走**（行数问题）：反爬/学术/GitHub/国内/评分五章用法手册、使用示例、
   代码结构清单、测试清单 ≈588 行 → `references/playbooks.md`。这些是"查手册时
   才看"的东西，不该每轮压着上下文。
2. **上移**（位置问题）：铁律 → §〇.6，禁止行为 → §〇.7，紧跟权限边界。
   这两节**不减一行**，只是换位置——搬走 588 行并不自动解决"Lead 漏读约束"。

所以本文件钉的是三条不变量：
- 铁律与禁止行为在**前 200 行**内出现（不是结尾）；
- 原章节位只剩指针，**没有第二份内容**（复制两份 = 两处都可能漏改）；
- playbooks.md 存在，且 SKILL.md 确实指向它（搬走了得找得到）。
"""
from __future__ import annotations

import re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = SKILL_ROOT / 'SKILL.md'
PLAYBOOKS = SKILL_ROOT / 'references' / 'playbooks.md'


def _md() -> str:
    return SKILL_MD.read_text(encoding='utf-8')


def _line_of(marker: str) -> int:
    """某一行落在文件第几行（1-based）；找不到返回 -1。"""
    for i, line in enumerate(_md().splitlines(), 1):
        if marker in line:
            return i
    return -1


# ---------------------------------------------------------------------------
# 约束必须在前面
# ---------------------------------------------------------------------------

def test_iron_rules_and_prohibitions_are_in_the_first_200_lines():
    """上移的全部意义就是这一条：位置比行数重要。"""
    md = _md()
    lines = md.splitlines()
    rules = next(i for i, l in enumerate(lines, 1) if l.startswith('## 〇.6'))
    bans = next(i for i, l in enumerate(lines, 1) if l.startswith('## 〇.7'))
    assert rules <= 200, f'铁律在第 {rules} 行——上下文一长就稀释没了'
    assert bans <= 200, f'禁止行为在第 {bans} 行'


def test_prohibitions_come_right_after_the_permission_boundary():
    """顺序也是约束：权限边界 → 铁律 → 禁止行为，中间不插别的东西。"""
    lines = _md().splitlines()
    pos = {}
    for i, l in enumerate(lines, 1):
        for key, marker in (('perm', '## 〇.五'), ('rules', '## 〇.6'),
                            ('bans', '## 〇.7')):
            if marker in l:
                pos.setdefault(key, i)
    assert set(pos) == {'perm', 'rules', 'bans'}, pos
    assert pos['perm'] < pos['rules'] < pos['bans'], pos


def test_the_rules_themselves_did_not_get_edited_while_moving():
    """上移只改位置。十一条铁律一条都不能少，也不能被改写成另一种说法。"""
    section = _md().split('## 〇.6', 1)[1].split('\n## ', 1)[0]
    items = re.findall(r'^\d+\.\s+\*\*(.+?)\*\*', section, re.M)
    assert len(items) == 11, f'铁律条数是 {len(items)}，应为 11：{items}'
    for name in ('澄清优先', 'MECE 拆解', '交叉验证', '引用可追溯', '诚实标注'):
        assert any(name in it for it in items), f'铁律「{name}」不见了'


def test_old_sections_are_stubs_not_duplicates():
    """复制两份比放一份更糟：两处都可能只改一处。

    所以原章节位必须只剩指针，正文唯一。"""
    md = _md()
    rules_block = md.split('## 〇.6', 1)[1].split('\n## ', 1)[0]
    bans_block = md.split('## 〇.7', 1)[1].split('\n## ', 1)[0]

    stub_rules = md.split('## 十二、核心原则', 1)[1].split('\n## ', 1)[0]
    stub_bans = md.split('## 十六、禁止行为', 1)[1].split('\n## ', 1)[0]

    assert '上移' in stub_rules, '原「十二」那节应留一行指路'
    assert '上移' in stub_bans, '原「十六」那节应留一行指路'
    # 指针节里不该再有正文：一条铁律、一个禁令都不许重复
    assert not re.search(r'^\d+\.\s+\*\*', stub_rules, re.M), '铁律被复制了一份'
    assert 'TaskCreate' not in stub_bans, '禁止行为被复制了一份'


def test_no_rule_row_is_lost_in_the_move():
    """逐条点名：上移过程中最容易丢的是列表里那几条。

    两节各查各的——凭据那条在 §〇.5 权限边界的表格里（"读取或外传 key/token"），
    不属于禁止行为节；混在一起查会得出"丢了"的假结论。"""
    md = _md()
    bans = md.split('## 〇.7', 1)[1].split('\n## ', 1)[0]
    perms = md.split('## 〇.五', 1)[1].split('\n## ', 1)[0]

    for kw in ('待办', 'TaskCreate', '绑卡', '单源结论', '静默降级'):
        assert kw in bans, f'禁止行为里丢了「{kw}」这一条'
    for kw in ('凭据', '破坏', '植入', '越权写', '越级裁决'):
        assert kw in perms, f'权限边界里丢了「{kw}」这一类'


# ---------------------------------------------------------------------------
# 搬走的东西要搬得干净、找得到
# ---------------------------------------------------------------------------

def test_playbooks_exists_and_holds_the_moved_manuals():
    assert PLAYBOOKS.exists(), '手册搬走了却没有落盘处'
    text = PLAYBOOKS.read_text(encoding='utf-8')
    for title in ('反爬', '学术全文', 'GitHub', '国内内容源', '推荐度评分'):
        assert title in text, f'playbooks 里少了「{title}」'


def test_skill_md_points_at_the_playbooks():
    md = _md()
    assert md.count('references/playbooks.md') >= 5, (
        '被搬走的章节至少要各留一处指路，否则 Lead 不知道去哪儿查')


def test_signature_table_stays_in_skill_md():
    """唯一从 playbooks 拿回来的东西：账本签名表。

    它写着"照抄即可，不必再跑 --help"，是每轮手边要抄的那一份——
    搬进手册等于让 Lead 每写一条 claim 都去翻文件。
    """
    md = _md()
    m = re.search(r'### 14\.3.*?```bash(.*?)```', md, re.S)
    assert m, '账本签名表不见了——它是执行时要抄的那一份'
    assert 'ledger.py' in m.group(1)
    assert 'link-identity' in m.group(1), (
        '签名表少了 link-identity（v6.21 加的通道，曾因漏登记而等于不存在）')


def test_skill_md_got_shorter():
    """搬走的量要真的体现在行数上，否则这轮重构等于没做。"""
    total = len(_md().splitlines())
    assert total <= 1500, f'SKILL.md 仍有 {total} 行（搬之前 1942）'
