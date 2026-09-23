"""X-D13：子 Agent 会往 Lead 那份待办列表里写条目，派发模板必须堵住这条路。

实测（本宿主，deep-research-ultra 实际派发用的 subagent_type=general-purpose）：
  1) 该类型子 Agent 的工具清单里有 TaskCreate / TaskUpdate / TaskList；
  2) 让子 Agent 建一条带唯一标记的任务，返回 ID #56，主 Agent 这边 TaskList 当场看到同一条；
  3) 返回体里没有任何 owner/归属字段——分不清哪条是谁写的。
Explore 类型没有这些工具，所以"子 Agent 都碰不到"的说法不成立，得按实际派发类型算。

后果：breadth 路并行、每路子 Agent 自觉记个"1) 检索 2) 落盘"的待办，Lead 的进度视图
就被 N×3 条别人的条目刷满，而 skill 的 Phase 状态全靠 Lead 那份列表对外汇报进度。
"""

from __future__ import annotations

from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[2] / 'SKILL.md'

# 子 Agent 能写待办的工具名，各宿主叫法不同，逐个列出来才算堵死
TASK_TOOL_NAMES = ('TaskCreate', 'TaskUpdate', 'TodoWrite')
PROHIBITION_WORDS = ('不要', '不得', '禁止', '不许')


def _md() -> str:
    return SKILL_MD.read_text(encoding='utf-8')


def _subagent_template() -> str:
    """截"子 Agent 提示词模板"后第一个围栏块——Lead 是整块复制粘贴的。

    约束没写进这块就等于没发给子 Agent；写在别处的正文它一个字都看不到。
    """
    after = _md().split('**子 Agent 提示词模板**', 1)[1]
    return after.split('```', 2)[1]


def _ban_section() -> str:
    """十六、禁止行为 那一节：补查等临时派发不一定复用模板，规矩得在这份总清单里。"""
    after = _md().split('## 十六、禁止行为', 1)[1]
    nxt = [i for i in (after.find('\n## '), after.find('\n---')) if i > 0]
    return after[:min(nxt)] if nxt else after


def _lines_naming_task_tools(block: str):
    return [ln for ln in block.splitlines()
            if any(tool in ln for tool in TASK_TOOL_NAMES)]


def test_template_tells_subagent_not_to_touch_the_task_list():
    hits = _lines_naming_task_tools(_subagent_template())
    assert hits, ('模板里没点名待办/任务工具，子 Agent 会照常往里写条目'
                  '（实测它确实有 TaskCreate）')
    assert any(any(w in ln for w in PROHIBITION_WORDS) for ln in hits), \
        f'点名了工具但没有禁止用语：{hits}'


def test_template_says_why_because_the_list_is_shared_with_lead():
    block = _subagent_template()
    hits = _lines_naming_task_tools(block) + [
        ln for ln in block.splitlines() if '待办' in ln or '任务清单' in ln]
    assert any('Lead' in ln and ('共享' in ln or '同一份' in ln) for ln in hits), (
        '没写"这份列表与 Lead 共享"，后来人会把这条约束当多余删掉')


def test_ban_list_carries_the_rule_for_ad_hoc_dispatch():
    section = _ban_section()
    hits = [ln for ln in section.splitlines()
            if '待办' in ln or '任务清单' in ln or any(t in ln for t in TASK_TOOL_NAMES)]
    assert hits, '补查等临时派发的子 Agent 不走那份模板，禁止清单里得有同一条'
    assert any(any(w in ln for w in PROHIBITION_WORDS) for ln in hits), \
        f'禁止清单里只是提到，没写成禁止：{hits}'


def test_positive_control_the_extractor_found_the_real_template():
    """上面三条都是断言"不存在"，这条钉住"截到的是那块"，否则红绿都可能截错地方。"""
    block = _subagent_template()
    assert '--format json --no-plan' in block, '截出的不是子 Agent 模板那块'
    assert '"status": "pending"' in block
    assert '{ledger_dir}/{slug}.json' in block
