"""v6.54 回归：对比/优化类报告形态（用户目标——报告质量：广泛、扎实、清晰）。

示例场景："调研与当前项目类似的开源方案，看能否优化本项目"——
1. 先做主体画像（内部调研：技术栈/架构），这是对比的基线；
2. 报告结构为对比而生：本项目基线 → 候选逐个（优劣）→ 对比矩阵 → 优化建议。
本文件钉住：骨架 compare 模式的结构、主题命名约定、文档层（SKILL.md/intent-types）
的对比撰写指引。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PLACEHOLDER = '【待写】'


def _compare_ledger(tmp_path):
    from ledger import ResearchLedger

    led = ResearchLedger(str(tmp_path / 'l')).init()
    c = led.add_claim('本项目当前使用 Flask 单体架构与 SQLite 存储', '本项目现状',
                      'verified', 'general', 0.9)
    led.add_source(c['id'], 'https://github.com/me/proj/blob/main/app.py', tier=1)
    for name in ('候选：RIOT', '候选：ThingsBoard'):
        cc = led.add_claim(f'{name} 维护活跃且许可证宽松', name, 'verified',
                           'general', 0.9)
        led.add_source(cc['id'], 'https://github.com/example/x', tier=1)
    cd = led.add_claim('维护状态维度的证据足够长可以当一行引用', '维护状态',
                       'verified', 'general', 0.9)
    led.add_source(cd['id'], 'https://example.org/d', tier=2)
    return led


def test_compare_skeleton_renders_baseline_candidates_matrix(tmp_path):
    from skeleton import build_skeleton

    _compare_ledger(tmp_path)
    md = build_skeleton(str(tmp_path / 'l'), title='T', intent='compare')
    assert '## 本项目现状（基线）' in md, '主体画像必须是第一节证据'
    assert '### 候选：RIOT' in md and '### 候选：ThingsBoard' in md
    assert '## 对比矩阵' in md
    assert '| 对比维度 | 本项目 | RIOT | ThingsBoard |' in md
    assert '## 对比维度证据' in md and '### 维护状态' in md
    assert '\n## 维护状态' not in md, '维度变成矩阵行，不再单独成节'


def test_compare_skeleton_without_baseline_warns(tmp_path):
    from ledger import ResearchLedger
    from skeleton import build_skeleton

    led = ResearchLedger(str(tmp_path / 'l')).init()
    c = led.add_claim('候选 X 维护活跃的整行证据文本', '候选：X', 'verified',
                      'general', 0.9)
    led.add_source(c['id'], 'https://example.org/x', tier=1)
    md = build_skeleton(str(tmp_path / 'l'), title='T', intent='compare')
    assert '对比缺基线' in md, '没有主体画像时必须点名警告'


def test_compare_matrix_cells_are_placeholders(tmp_path):
    from skeleton import build_skeleton

    _compare_ledger(tmp_path)
    md = build_skeleton(str(tmp_path / 'l'), title='T', intent='compare')
    row = [l for l in md.split('\n') if l.startswith('| 维护状态 |')][0]
    assert row.count(PLACEHOLDER) == 3, f'矩阵每格都是待写：{row}'


def test_default_mode_unchanged_by_compare(tmp_path):
    from skeleton import build_skeleton

    _compare_ledger(tmp_path)
    md = build_skeleton(str(tmp_path / 'l'), title='T')
    assert '## 对比矩阵' not in md, '默认（知识类）形态不受 compare 影响'
    assert '## 本项目现状' in md, '默认形态仍按主题分节'


# ============================================================
# 文档钉：主体画像步骤 + 对比撰写指引 + 优化建议四要素
# ============================================================

def test_skill_md_has_internal_research_step():
    skill = (Path(__file__).resolve().parents[2] / 'SKILL.md').read_text(encoding='utf-8')
    assert '主体画像' in skill, 'Phase 1 必须有内部调研（主体画像）步骤'
    assert '对比缺基线就是空对空' in skill


def test_skill_md_has_compare_writing_guide_and_suggestion_format():
    skill = (Path(__file__).resolve().parents[2] / 'SKILL.md').read_text(encoding='utf-8')
    assert '优化建议' in skill and '优先级' in skill, '优化建议要结构化'
    assert '--intent compare' in skill, '骨架入口要写进文档'


def test_intent_types_has_compare_report_shape():
    it = (Path(__file__).resolve().parents[2] / 'references' / 'intent-types.md'
          ).read_text(encoding='utf-8')
    assert '对比矩阵' in it, '决策选型类型要给出对比报告结构'
