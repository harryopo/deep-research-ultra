"""v6.71：补上 HANDOFF 体量数字的钉子（两处，只被同步过一处）。

发现方式：v6.71 同步体量时 `run_all_tests.py` 的真实结果是 1106，
而 HANDOFF 里有**两处**体量数字——行 10「全量 N 项」与行 117
「**N 项**＝内核 X＋壳 Y」。替换只命中前者，后者仍写着 1056。
翻历史：从 v6.69（真实值 1089）起它就没再动过，**陈旧了 6 个版本**。

**为什么没人发现**：`test_landing_page_facts` 钉的是 index.html 的数字，
没人钉 HANDOFF。而本项目最在意的就是"数字可溯源"——宣传页上的数字有人守，
交接文档上的没有，这不算守住。

## 判定为什么用精确模式，而不是"扫所有 ≥1000 的数字+项"

扫数字会把**历史引用**当成当前声明：文中还有 `894 项时代产物`、
`1018 项存量测试`、`1089 项写死在宣传页上`，全是 v6.69 的真实数字、现在都是历史。
把它们判成"陈旧"会逼着后人去改历史陈述——那比陈旧本身更糟。

所以只认两种**声明形状**：`全量 N 项` 与 `**N 项**＝内核 X＋壳 Y`。
`1089 项测试` 两条都不匹配，历史引用因此天然豁免。

另一个教训更朴素：同一件事在两个文件里各有一份数字时，"改一处"几乎必然漏另一处。
与其靠记性，不如让两处都被测试读到。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parents[1]
HANDOFF = REPO / '.ai' / 'HANDOFF.md'

# 「全量 1106 项」——必须是这个形状才算当前声明
P_TOTAL = re.compile(r'全量\s*\*{0,2}(\d{3,5})\*{0,2}\s*项')
# 「**1106 项**＝内核 1056＋壳 50」——`项` 后面还有 **，第一版漏了这段没匹配上
P_SPLIT = re.compile(
    r'\*{0,2}(\d{3,5})\s*\*{0,2}\s*项\s*\*{0,2}\s*[＝=]\s*内核\s*(\d{3,5})'
    r'\s*[＋+]\s*壳\s*(\d{1,4})')


def _collected_total() -> int:
    """按 pytest 实际收集数算，与 run_all_tests.py 同一口径。"""
    out = subprocess.run(
        [sys.executable, '-m', 'pytest', str(SCRIPTS / 'tests'),
         str(REPO / 'tests'), '--collect-only', '-q', '--no-header'],
        capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    m = re.findall(r'(\d+) tests? collected', out)
    if m:
        return int(m[-1])
    n = len(re.findall(r'::', out))
    assert n > 1000, f'收集数没算出来（pytest 输出异常）：{out[-300:]}'
    return n


def test_handoff_total_matches_disk():
    """HANDOFF 的「全量 N 项」必须是磁盘上的真实收集数。

    刻意扫**全部出现位置**而不是钉某一行：钉行号的话，下次谁把这段挪个位置，
    钉子就悄悄失效了——正是它本该防的那类漂移。
    """
    total = _collected_total()
    text = HANDOFF.read_text(encoding='utf-8')
    found = [int(m.group(1)) for m in P_TOTAL.finditer(text)]
    assert found, 'HANDOFF 里找不到「全量 N 项」那句'
    stale = sorted({n for n in found if n != total})
    assert not stale, (
        f'HANDOFF 里的全量测试数是 {stale}，磁盘实测 {total}。'
        '同一件事在两处各有一份数字时，"改一处"几乎必然漏另一处——'
        '这次就漏了 6 个版本（v6.69→v6.71 一直是旧数）。')


def test_handoff_split_is_self_consistent_and_current():
    """`N 项＝内核 X＋壳 Y` 三个数必须自洽，且等于真实收集数。"""
    total = _collected_total()
    text = HANDOFF.read_text(encoding='utf-8')
    m = P_SPLIT.search(text)
    assert m, 'HANDOFF 里找不到「N 项**＝内核 X＋壳 Y」那句（注意 项 与 ＝ 之间还有 **）'
    said, kernel, shell = (int(g) for g in m.groups())
    assert kernel + shell == said, (
        f'自相矛盾：{said} ≠ {kernel} + {shell}（内核 {kernel} ＋壳 {shell}）')
    assert said == total, (
        f'这句里的 {said} 项与磁盘实测 {total} 不符'
        f'（应为内核 {kernel}＋壳 {shell}＝{kernel + shell}，实测 {total}）')


def test_both_places_are_actually_checked():
    """自检：这两个测试真的各自覆盖了一处，缺一个就红。

    写测试时最容易出的错是"看起来测了、其实某处没人看"。
    这里把断言摊开数一遍——两处声明各被一个断言覆盖，少一处就断。
    """
    text = HANDOFF.read_text(encoding='utf-8')
    total_said = {int(m.group(1)) for m in P_TOTAL.finditer(text)}
    split_said = {int(m.group(1)) for m in P_SPLIT.finditer(text)}
    assert total_said, '「全量 N 项」形状没找到——test_handoff_total_matches_disk 会空断言'
    assert split_said, '「N 项**＝内核 X＋壳 Y」形状没找到——split 测试会空断言'