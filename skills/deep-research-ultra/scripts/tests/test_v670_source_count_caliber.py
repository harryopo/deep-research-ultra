"""v6.70.0：数据源数量的口径——**我的"修法"不如现状**，所以只补 README 缺口 + 钉住不退化。

## 又一次误判，方向是"我想改的东西本来就是对的"

体检 P1-6 写的是"宣称 34 个数据源 vs 本机实出 14 个（2.4× 落差）"，修法建议：

    宣传口径改为双数字——「34 个数据源 / 本机 probe 实测可用 N 个」，
    并让 index.html 的 N 由 --probe 输出自动生成（一行脚本 + CI 定期跑）

**但宣传页早就写着**（`index.html` 能力区末尾）：

    34 个源里 5 个要先配 key 或服务，其余 29 个开箱即用——**这个分配只取决于配置**，
    用 `--list` 查一次就是定数。至于某个源此刻到底还出不出数据，那是 `--probe` 的实测
    范围，**别拿静态数字当结论**。

也就是说：这个项目**没有**承诺 34 个都能出数据，它已经指明了 probe 是唯一判据。
而我建议的"CI 定期把可用数刷进 index.html"**恰好会破坏这个已经正确的设计**：
CI 机器的环境不等于用户机器，页面数字每天变，读者看到不一致只会更困惑——
**用一个会过期的静态数字去修一个不存在的问题。**

## 所以这版只做两件事

1. **README 补口径说明**——它确实缺（宣传页有，README 那个"34"是孤立数字）。
2. **钉住不退化**——防的是下一手（包括我自己）看到"34 vs 14 的落差"又去加自动刷新。

## 为什么会反复出现这类误判

同一个错误模式已经出现五次：体检三次 + S2 一次 + 这次。都是**先给现象一个解释，
再去验证**。这版把这个模式本身写进测试的 docstring，因为它比任何单条结论都更值得留。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]   # 仓库根（tests 下面还有 4 层）
SKILL_MD = REPO / 'skills' / 'deep-research-ultra' / 'SKILL.md'
README = REPO / 'README.md'
INDEX = REPO / 'index.html'


# ---------------------------------------------------------------------------
# 1. 三处都要说清 34 是什么
# ---------------------------------------------------------------------------

def test_readme_explains_what_34_means():
    """README 里那个"34"曾经是个孤立数字——宣传页有口径说明，README 没有。"""
    text = README.read_text(encoding='utf-8')
    assert '34 个数据源' in text
    m = re.search(r'34 是[^。]*。', text)
    assert m, 'README 没解释"34"的口径'
    assert '--probe' in m.group(0) or 'probe' in text[:1200], \
        '口径说明要把读者指向 probe（那是唯一能回答"今天出不出数据"的东西）'


def test_landing_page_keeps_its_caliber_note():
    """宣传页那句"别拿静态数字当结论"是这条的基石，不许被删。"""
    text = INDEX.read_text(encoding='utf-8')
    assert '别拿静态数字当结论' in text, \
        '宣传页那句口径说明不见了——它是"34 不等于可用数"的唯一声明'
    assert '--probe' in text and '--list' in text


def test_skill_md_does_not_promise_all_sources_are_usable():
    """SKILL.md 是 Lead 读的那份，不能出现"34 个源都能用"这种承诺。"""
    text = SKILL_MD.read_text(encoding='utf-8')
    bad = re.findall(r'34 个(?:数据源|源)(?:都|全部|均)', text)
    assert not bad, f'SKILL.md 里出现了可用性承诺：{bad}'


# ---------------------------------------------------------------------------
# 2. 防退化：别把动态数字写进静态页
# ---------------------------------------------------------------------------

def test_no_baked_in_probe_result_in_the_docs():
    """**这条防的正是我差点建议的那个方案。**

    把某次 `--probe` 的结果（如"本机 14 个可用"）写进 index.html/README：
    CI 机器的环境 ≠ 用户机器，上游状态每天变，页面数字会互相矛盾。
    静态页只能承诺可复算的东西（注册表口径），动态的交给 probe。
    """
    for path in (INDEX, README, SKILL_MD):
        text = path.read_text(encoding='utf-8')
        hits = re.findall(r'(?:本机|今日|今天)\s*\d+\s*个(?:可用|能出|出数)', text)
        assert not hits, (
            f'{path.name} 里写死了某次 probe 的结果：{hits}——'
            '那个数字取决于网络/凭据/上游状态，会过期。'
            '静态页只写注册表口径，动态的交给 --probe。')


def test_the_two_calibers_stay_distinguishable():
    """`--list`（配置就绪）与 `--probe`（真出数据）是两件事，文档要分开说。"""
    for path in (INDEX, README):
        text = path.read_text(encoding='utf-8')
        assert '--list' in text, f'{path.name} 没提 --list（配置就绪口径）'
        assert '--probe' in text, f'{path.name} 没提 --probe（真出数据口径）'


def test_audit_report_records_that_my_fix_was_worse():
    """体检 P1-6 的修法建议（CI 定期刷新可用数）会破坏已有设计，必须留下更正。

    错话留在文件里不更正，下一手会拿它当依据——这是这轮反复验证过的。
    """
    p = REPO / 'docs' / 'dev' / 'v6.62-系统体检报告.md'
    seg = p.read_text(encoding='utf-8')
    i = seg.find('### P1-6')
    assert i != -1, '体检报告里找不到 P1-6'
    block = seg[i:seg.find('### P1-7')]
    assert '更正' in block or '不如现状' in block or '不存在的问题' in block, \
        'P1-6 没写更正——那条"修法"会把静态页变成会过期的数字来源'
