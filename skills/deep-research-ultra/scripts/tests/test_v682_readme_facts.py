"""v6.82：README 的数字与链接必须与磁盘一致，且不许有 emoji。

## 为什么加这个

重写 README 时逐个对着磁盘核了一遍，发现它能**陈旧 41 个版本而无人发现**：

| 位置 | 原来写的 | 实测 |
|---|---|---|
| 页脚版本 | `v6.40.0 · 2026-09-29` | 陈旧 41 个版本 |
| 竞品表「四层 32 数据源」 | 32 | 34 |
| 「767 个用例」 | 767 | 1161 |
| 「76 个测试文件」 | 76 | 120 |
| 「19 份调研笔记」 | 19 | 5 |
| `YOUR_USERNAME` 占位符 | 6 处 | 全是死链 |

`test_v6410_source_count_pin.py` 已经钉住了 `共 N 个数据源` 那句，但**钉不到写在别处的数**
——竞品表里的「32 数据源」、测试节里的「767 个用例」都在它的判据之外。

**为什么这类数字特别容易烂**：它们分散在正文、表格、页脚、目录树里，没有单一来源。
这与 v6.71 那次"HANDOFF 里两处体量数字只同步了一处、陈旧 6 个版本"是同一类毛病，
也与「同一件事在四处各写一遍，靠记性同步就是会漏」是同一个道理。

## emoji 为什么也要钉

用户明确要求 README 不用 emoji。这条留着是因为表格里的 `✅`/`❌` 有真实歧义：
**同一列里 `✅` 到底是「有」还是「推荐」，取决于看的是哪一列**。换成文字后每格自明。
钉住它不是管审美，是防下一次有人顺手把 `✅` 加回来——那一加，歧义就跟着回来。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
README = REPO / 'README.md'
SKILL = REPO / 'skills' / 'deep-research-ultra' / 'SKILL.md'
SCRIPTS = REPO / 'skills' / 'deep-research-ultra' / 'scripts'


def _readme() -> str:
    return README.read_text(encoding='utf-8')


# ---------------------------------------------------------------------------
# 一、页脚版本不许落后
# ---------------------------------------------------------------------------

def test_footer_version_is_the_kernel_version():
    """页脚那行曾经停在 v6.40.0，而内核已经 41 个版本了。

    判据不只是"版本号相等"，还要**真的在页脚里**——正文任意位置出现版本号不算，
    否则改一处正文就能骗过这条测试。
    """
    m = re.search(r'^version: ([\d.]+)', SKILL.read_text(encoding='utf-8'), re.M)
    want = m.group(1)
    txt = _readme()
    tail = txt.strip().splitlines()[-3:]
    assert any(want in ln for ln in tail), (
        f'页脚没有内核版本 {want}（末三行：{tail}）——'
        '这条曾经烂了 41 个版本没人发现')


# ---------------------------------------------------------------------------
# 二、测试数：README 说的与 collect 出来的一致
# ---------------------------------------------------------------------------

def test_readme_test_count_matches_collection():
    """README 说 1161 项，就真的是 1161 项。

    用 collect 而不是抄 HANDOFF：HANDOFF 那个数本就是从 collect 得来的，
    拿它对照等于让两处互相担保。两处都不对时测试会安静通过。
    """
    txt = _readme()
    m = re.search(r'当前 \*\*(\d+) 项\*\*（内核 (\d+) \+ 壳 (\d+)）', txt)
    assert m, 'README 里找不到「当前 N 项（内核 a + 壳 b）」那句'
    total, kernel, shell = int(m.group(1)), int(m.group(2)), int(m.group(3))
    assert total == kernel + shell, f'{total} ≠ {kernel} + {shell}'

    # 用 sys.executable 而非 'python'，并且**路径必须绝对**。
    #
    # 第一版写的是 `['python', '-m', 'pytest', str(d), ...]`。单跑本文件时它是绿的，
    # 挂在 run_all_tests.py 下才红——因为 run_all_tests.py 用 `cwd=scripts` 调 pytest，
    # 子进程的相对基准变了。更糟的是失败形态是 `re.search` 返回 None 后
    # `m.group()` 抛 TypeError，报错完全指不到真正的原因（cwd），看着像随机失败。
    #
    # 这与 v6.51 那次「单跑任一套都是绿的，'绿'被两个测试根瓜分了」是同一类：
    # **只在特定调用方式下才复现的失败，必须按那种方式验**。
    import subprocess
    import sys
    collected = 0
    for d in (SCRIPTS / 'tests', REPO / 'tests'):
        assert d.is_absolute() and d.exists(), f'{d} 不是可用的绝对路径'
        out = subprocess.run(
            [sys.executable, '-m', 'pytest', str(d), '--collect-only', '-q'],
            cwd=str(REPO),                 # 与 run_all_tests.py 的 cwd 一致
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        mm = re.search(r'(\d+) tests? collected', out.stdout or '')
        assert mm, (
            f'{d.name} 收集不到用例（returncode={out.returncode}）。'
            f'stdout 末 300: {(out.stdout or "")[-300:]}\n'
            f'stderr 末 300: {(out.stderr or "")[-300:]}')
        collected += int(mm.group(1))
    assert total == collected, (
        f'README 写 {total} 项，磁盘实测收集 {collected} 项')


# ---------------------------------------------------------------------------
# 三、目录树里的文件数与数据源数
# ---------------------------------------------------------------------------

def test_tree_counts_match_disk():
    """目录树里写死的文件数（测试文件 / references / engines）必须对得上。

    原来写「76 个测试文件 / 767 用例 / 19 份调研笔记」，实测是 120 / 1161 / 5。
    这些数一个都没有别的测试钉着，所以能烂这么久。
    """
    txt = _readme()
    # 取包含 "tests/" 的那一个围栏块：README 里有多个 ``` 块（前两个是目录树，
    # 按顺序切容易切错位置——第一版就是这么切到别的块去了）
    blocks = re.findall(r'```[a-z]*\n(.*?)```', txt, re.S)
    tree = next((b for b in blocks if 'tests/' in b), txt)
    assert 'tests/' in tree, 'README 里找不到目录树那个代码块——它改名了？先看一眼再改测试'

    n_kernel = len(list((SCRIPTS / 'tests').glob('test_*.py')))
    n_shell = len(list((REPO / 'tests').glob('test_*.py')))
    n_refs = len(list((SKILL.parent / 'references').glob('*.md')))
    n_engines = len(list((SCRIPTS / 'engines').glob('*.py')))

    m = re.search(r'(\d+) 个测试文件 / (\d+) 个用例', tree)
    assert m, '目录树里找不到内核测试文件的「N 个测试文件 / M 个用例」'
    assert int(m.group(1)) == n_kernel, f'测试文件 {m.group(1)} ≠ 实测 {n_kernel}'

    m = re.search(r'(\d+) 份操作手册与配置指南', tree)
    assert m, '目录树里找不到 references 的份数'
    assert int(m.group(1)) == n_refs, f'references {m.group(1)} ≠ 实测 {n_refs}'

    m = re.search(r'(\d+) 个引擎模块', tree)
    assert m, '目录树里找不到引擎模块数'
    assert int(m.group(1)) == n_engines, f'engines {m.group(1)} ≠ 实测 {n_engines}'

    m = re.search(r'插件壳侧测试 (\d+) 个文件 / (\d+) 个用例', tree)
    assert m, '目录树里找不到插件壳侧测试数'
    assert int(m.group(1)) == n_shell, f'壳测试文件 {m.group(1)} ≠ 实测 {n_shell}'


def test_competitor_table_says_the_real_source_count():
    """竞品表里那个「四层 N 数据源」曾经停在 32，而注册表是 34。

    `test_v6410_source_count_pin.py` 钉的是 `共 N 个数据源` 那句**在 SKILL.md 抬头**，
    竞品表里这个同义但不同形的写法在它的判据之外——所以它能悄悄烂着。
    """
    skill = SKILL.read_text(encoding='utf-8')
    total = re.search(r'共 (\d+) 个数据源', skill).group(1)
    txt = _readme()
    hits = re.findall(r'四层 (\d+) 数据源', txt)
    assert hits, '竞品表里找不到「四层 N 数据源」'
    for h in hits:
        assert h == total, (
            f'竞品表写「四层 {h} 数据源」，注册表是 {total}——'
            '它是同一个数的另一种写法，不该由 `共 N 个数据源` 那条钉子管着')


# ---------------------------------------------------------------------------
# 四、死链与 emoji
# ---------------------------------------------------------------------------

def test_no_placeholder_urls():
    """`YOUR_USERNAME` 曾出现 6 处，链接全是坏的。

    GitHub 会把它们渲染成可点的死链，读者点进去得到 404——比没有链接更糟。
    """
    bad = re.findall(r'https://github\.com/[A-Z_]+/[^\s)\'"]+', _readme())
    assert not bad, f'README 里有占位符链接（点得开但全是 404）：{bad}'
    # 反向：真的链接必须指向存在的仓库名
    real = re.findall(r'https://github\.com/([a-zA-Z0-9_.-]+)/', _readme())
    assert 'YOUR_USERNAME' not in real, '还有 YOUR_USERNAME'


def test_no_emoji():
    """README 不用 emoji（用户明确要求）。

    判据把范围写死在一段区间里，避免 emoji 的代理对分类不全而漏判。
    真正的理由不是审美：表格里的 `✅` 与 `❌` 有歧义——同一列里 `✅` 到底是
    「有」还是「推荐」，取决于看的是哪一列。文字没有这个问题。
    """
    txt = _readme()
    hits = re.findall(r'[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]', txt)
    assert not hits, f'README 里还有 {len(hits)} 处 emoji：{sorted(set(hits))[:10]}'
    # 顺手钉住竞品表那几列必须用文字
    assert '| 子 Agent 并行 | 支持：' in txt, '竞品表该用「支持：」而不是对勾'
    assert '❌' not in txt and '✅' not in txt, '对勾/叉号回来了'


def test_table_rows_are_not_ambiguous_about_support():
    """竞品表每一格要么写「支持」/「不支持」/「有限」，要么写能力名，不许只留符号。"""
    txt = _readme()
    sec = txt.split('## 与竞品对比', 1)[1].split('\n## ', 1)[0]
    rows = [ln for ln in sec.splitlines() if ln.strip().startswith('|')]
    assert len(rows) >= 10, f'竞品表行数 {len(rows)}，表是不是散了'
    checked = 0
    for ln in rows[2:]:                      # 跳过表头与分隔行
        cells = [c.strip() for c in ln.strip().strip('|').split('|')]
        if len(cells) < 2:
            continue
        ours = cells[1]
        # 判据只针对**是/否型**的格。架构、报告格式这类是"描述型"格子，
        # 写"支持"反而不对——第一版把描述型也套进同一个判据，红了才发现。
        # 所以先看这一行的首格是不是能力名（是/否型都这么写），再要求我方那格有明确表态。
        label = cells[0].strip('*')
        if not any(k in label for k in ('并行', '专家团', '账本', 'MECE', 'CRAAP',
                                        '交叉验证', '反思', 'MCP', 'Skill',
                                        '中文', '费用', 'Mermaid')):
            continue
        checked += 1
        assert any(w in ours for w in ('支持', '不支持', '有限', '免费')), \
            f'这一格没写清是支持还是不支持：{ln.strip()[:70]}'
    assert checked >= 8, f'只检查到 {checked} 行——能力名清单该跟着表格一起更新'
