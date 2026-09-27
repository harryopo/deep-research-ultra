"""子 Agent 派发要分波，不能一波全发——实测宿主会回 concurrency limit exceeded。

背景（2026-09-27 用户实跑反馈）：deep 档 breadth=8，SKILL.md 写的是"一次性并行 spawn、
一次 turn 发完"，账号侧并发上限直接被打回 `user concurrency limit exceeded`。
一句"发完"没有上限，等于让 Lead 在最深的档上必然踩雷；踩了之后没有降级动作，
整轮调研就停在那里。

所以这里锁三件事：
1. 有一个每波上限（WAVE_MAX），且它真的会咬到最深的档（否则这条规则形同虚设）；
2. `--plan-only` 的回执要把"分几波"打在 breadth 那一行——Lead 照抄回执，不会去翻正文；
3. SKILL.md 不许再出现无上限的"一次 turn 发完"，并且要写明超限后的降级动作。
"""
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SKILL = SCRIPTS.parent / 'SKILL.md'
sys.path.insert(0, str(SCRIPTS))


def _receipt(effort: str) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / 'research.py'), '并发上限回归主题',
         '--plan-only', '--effort', effort, '--dimensions',
         ','.join(f'维度{i}' for i in range(1, 13))],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(SCRIPTS))
    return (out.stdout or '') + (out.stderr or '')


def test_wave_cap_exists_and_bites_the_deepest_tier():
    import research
    assert research.WAVE_MAX >= 1, '每波上限至少 1，否则一条都发不出去'
    assert research.WAVE_MAX < max(research.EFFORT_BREADTH.values()), (
        f'WAVE_MAX={research.WAVE_MAX} 不小于最深档 breadth，'
        '这条上限永远不会生效——分波规则形同虚设')


def test_plan_receipt_shows_how_many_waves():
    text = _receipt('deep')
    m = re.search(r'建议 breadth（并行子主题数）: (\d+)', text)
    assert m, f'回执里没有 breadth 那一行，Lead 无从照抄分波：{text[:400]}'
    breadth = int(m.group(1))
    waves = -(-breadth // __import__('research').WAVE_MAX)
    assert f'每波 ≤{__import__("research").WAVE_MAX}' in text, \
        '回执只报并行数、不报每波上限，Lead 会照 breadth 一次全发'
    assert f'{waves} 波' in text, f'breadth={breadth} 应打印 {waves} 波'
    assert 'concurrency' in text, '回执没写撞上限后的降级动作'


def test_skill_doc_no_longer_tells_the_lead_to_fire_everything_at_once():
    text = SKILL.read_text(encoding='utf-8')
    for bad in ('一次性并行 spawn', '一次 turn 发完'):
        assert bad not in text, f'文档仍在让 Lead 一波全发（{bad}）'
    assert '分波' in text and '每波' in text, '文档没有分波派发的说法'
    assert 'user concurrency limit exceeded' in text, \
        '文档没提这个真实报错，Lead 撞上了也不知道该降波'
    import research
    assert f'每波 ≤{research.WAVE_MAX}' in text, (
        f'文档写的每波上限与 research.WAVE_MAX={research.WAVE_MAX} 不一致')
