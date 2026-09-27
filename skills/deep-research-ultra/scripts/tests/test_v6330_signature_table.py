"""v6.33.0 回归：§14.3 那张签名表必须覆盖 ledger.py 的每个子命令。

SKILL.md §14.3 的注释原话是「证据账本（写命令签名照抄，不必再跑 --help）」，
冷启动那节也写着"命令照抄即可（十四节的签名表已列全）"。所以"在 SKILL.md 里出现过"
不算数——**得出现在这张照抄用的签名块里**才算 documented。

实测漂移：v6.21 加的 `link-identity` 与 v6.32 加的 `content-identity` 都只在正文散文里
出现过，签名块里没有。照着签名块抄命令的 Lead 不知道有这两条通道，
于是"跨标识符/跨主机判同"这条升级路等于不存在（claim 只能停在 pending）。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SKILL = Path(__file__).resolve().parents[2] / 'SKILL.md'
SCRIPTS_DIR = Path(__file__).resolve().parents[1]


def _signature_block() -> str:
    """取 §14.3 里那段 ledger.py 的 bash 签名块。"""
    text = SKILL.read_text(encoding='utf-8')
    m = re.search(r'### 14\.3.*?```bash(.*?)```', text, re.S)
    assert m, '找不到 §14.3 的签名块'
    start = m.group(1).index('ledger.py')
    block = m.group(1)[start:]
    nxt = re.search(r'### ', block)
    return block[:nxt.start()] if nxt else block


def _scripts_with_subcommands() -> dict:
    """扫全部 CLI 脚本，取各自的子命令清单（不止 ledger——同类缺陷要一次横扫）。"""
    out = {}
    for path in sorted(SCRIPTS_DIR.glob('*.py')):
        cmds = sorted(set(re.findall(r"cmd == '([a-z-]+)'",
                                     path.read_text(encoding='utf-8', errors='replace'))))
        if cmds:
            out[path.name] = cmds
    return out


def test_每个子命令都在签名块里():
    block = _signature_block()
    table = _scripts_with_subcommands()
    assert table, '一个带子命令的 CLI 都没扫到——扫描口径坏了，这条断言就会空转'
    missing = [f'{name} {cmd}' for name, cmds in table.items()
               for cmd in cmds if f'{name}" {cmd}' not in block]
    assert not missing, (
        f'§14.3 签名块缺 {missing}——这张表写着"照抄即可，不必再跑 --help"，'
        f'漏一条就等于这条能力不存在')


def test_effort_table_says_what_the_code_actually_enforces():
    """§Phase 1 的 effort 表：三列数字要等于代码强制值，另两列要标明由单独开关决定。

    实测 2026-09-27（`--plan-only --effort X`，四档各跑一次 + 直接读预设）：
    - 子问题上限 3 / 5 / 8 / 12。旧表写 "standard 4-6""deep 7-10"，
      而同一节又写着"想要 7-10 个子问题就要给 7-10 个维度"——真给 10 个维度跑 deep，
      实测被丢掉 2 个（社区口碑、演进时间线），照文档办事的 Lead 拿不到它要的树。
    - breadth 2 / 4 / 8 / 12（这一列本来就对）。
    - 反思轮次与 effort **无关**：`--reflect-rounds` 默认 1，四档都一样；
      专家团视角也不随 effort 变（`--perspectives` 不给就用 DEFAULT_PERSPECTIVES）。
      旧表把它们写成 effort 的分级效果（quick 0 轮 / deep 2-3 轮 + 2 轮对抗 /
      exhaustive red-team 多轮），照着表就不可能得到那些行为。
    """
    import plan
    from research import EFFORT_BREADTH  # 表里的 breadth 与该映射同源
    text = SKILL.read_text(encoding='utf-8')
    m = re.search(r'\| effort \| 子问题数.*?\n((?:\|.*\n)+)', text)
    assert m, '找不到 effort 表——表头改了名，这条断言就会空转'
    rows = {}
    for line in m.group(1).strip().splitlines():
        if line.strip().startswith('|--') or set(line.strip()) <= set('|- '):
            continue                        # 表头与数据行之间的分隔行
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        key = next((e for e in ('quick', 'standard', 'deep', 'exhaustive')
                    if e in cells[0]), cells[0])
        rows[key] = cells
    presets = plan.PlanGenerator.DEPTH_PRESETS
    caps = {k: presets[v]['max_sub_questions'] for k, v in
            (('quick', 'quick'), ('standard', 'standard'),
             ('deep', 'deep'), ('exhaustive', 'extreme'))}
    for effort, cap in caps.items():
        assert effort in rows, f'表里少了 {effort} 行'
        assert rows[effort][1] == f'≤{cap}', (
            f'{effort} 的子问题数列是 {rows[effort][1]!r}，代码上限是 {cap}'
            f'——写区间会让 Lead 按区间给维度，多出来的被丢弃')
        assert rows[effort][2] == str(EFFORT_BREADTH[effort]), (
            f'{effort} 的 breadth 列是 {rows[effort][2]!r}，代码是 '
            f'{EFFORT_BREADTH[effort]}')
    for kw in ('--reflect-rounds', '--perspectives'):
        assert kw in text, f'表旁没提 {kw}，读者会以为这两列随 effort 变'
    # 同一张表在 README 里还有一份（同类漂移要一次横扫，不是只修看见的那处）
    readme = (SKILL.parents[2] / 'README.md').read_text(encoding='utf-8')
    rm = re.search(r'\| 深度.*?\|.*?\n\|[-| ]+\n((?:\|.*\n)+)', readme)
    assert rm, 'README 的深度表不见了或表头改了名'
    rrows = {}
    for line in rm.group(1).strip().splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        rrows[cells[0]] = cells
    for depth, effort in (('quick', 'quick'), ('standard', 'standard'),
                          ('deep', 'deep'), ('extreme', 'exhaustive')):
        assert depth in rrows, f'README 深度表少了 {depth} 行'
        want = presets['extreme' if depth == 'extreme' else depth]
        got = rrows[depth]
        assert f'≤{want["max_sub_questions"]}' in got[2], (
            f'README {depth} 行子问题数写 {got[2]!r}，代码上限 '
            f'{want["max_sub_questions"]}')
        assert want['estimated_duration'] in got[-1], (
            f'README {depth} 行耗时写 {got[-1]!r}，代码预设是 '
            f'{want["estimated_duration"]!r}')
        assert '--reflect-rounds' in readme.split('### CRAAP')[0], \
            'README 把反思轮次列回表里都行——它由 --reflect-rounds 单独决定'


def test_签名块不为空且确实覆盖多数命令():
    """对照面：断言不许因为"块没解析到"而空转通过。"""
    block = _signature_block()
    table = _scripts_with_subcommands()
    total = sum(len(cmds) for cmds in table.values())
    hit = sum(1 for name, cmds in table.items()
              for c in cmds if f'{name}" {c}' in block)
    assert hit >= total - 1, f'签名块只覆盖 {hit}/{total} 条，解析或文档出了问题'
