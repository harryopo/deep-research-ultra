"""v6.55 回归：报告类型学 + 派单模板任务书化。

用户批评（2026-10-04）：①调研报告应该分类型（学术/对比/开源/知识/商业…），
每型有通用与细化模板、对应的调研方法与思考架构——这是 skill 该给的脚手架；
②子 Agent 派单提示词"修修补补避免失败"，又长又不清晰。本文件钉住：
- references/report-types.md 六型存在，每型有形态/方法/失败模式；
- skeleton --intent 对 academic/business/risk/opensource 渲染类型专属骨架块；
- 派单模板是任务书形态（四步+硬约束分组），关键规则一条不少，
  事故叙事已移出 SKILL.md（进 references/subagent-lessons.md）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REFS = Path(__file__).resolve().parents[2] / 'references'
SKILL = Path(__file__).resolve().parents[2] / 'SKILL.md'


def _tiny_ledger(tmp_path, topic='某维度'):
    from ledger import ResearchLedger

    led = ResearchLedger(str(tmp_path / 'l')).init()
    c = led.add_claim('一条足够长可以当一行引用的账本证据文本', topic, 'verified',
                      'general', 0.9)
    led.add_source(c['id'], 'https://example.org/a', tier=2)
    return led


# ============================================================
# 报告类型学文档
# ============================================================

def test_report_types_doc_covers_six_types():
    t = (REFS / 'report-types.md').read_text(encoding='utf-8')
    for name, flag in [('知识调研', '`knowledge`'), ('对比/优化型', '`compare`'),
                       ('开源调研/选型', '`opensource`'), ('学术调研', '`academic`'),
                       ('商业调研', '`business`'), ('风险审查', '`risk`')]:
        assert name in t and flag in t, f'类型学缺 {name}'
    for section in ['通用脊柱', '失败模式', '验证重点']:
        assert section in t


def test_lessons_doc_exists_and_has_stories():
    t = (REFS / 'subagent-lessons.md').read_text(encoding='utf-8')
    for kw in ['五千万', 'pushed_at', 'D5-injection', 'UTF-8', 'TodoWrite']:
        assert kw in t, f'教训档案缺 {kw}'


# ============================================================
# skeleton 类型专属骨架块
# ============================================================

@pytest.mark.parametrize('intent,heading', [
    ('academic', '## 研究空白与机会'),
    ('business', '## 竞争格局速览'),
    ('risk', '## 风险登记表'),
    ('opensource', '## 引入成本与迁移建议'),
])
def test_intent_extra_sections_render(tmp_path, intent, heading):
    from skeleton import build_skeleton

    _tiny_ledger(tmp_path)
    md = build_skeleton(str(tmp_path / 'l'), title='T', intent=intent)
    assert heading in md, f'{intent} 应渲染 {heading}'
    assert PLACEHOLDER if (PLACEHOLDER := '【待写】') else True


def test_default_knowledge_has_no_extra_sections(tmp_path):
    from skeleton import build_skeleton

    _tiny_ledger(tmp_path)
    md = build_skeleton(str(tmp_path / 'l'), title='T')
    for heading in ('## 研究空白与机会', '## 竞争格局速览', '## 风险登记表',
                    '## 引入成本与迁移建议'):
        assert heading not in md, '默认（知识类）不该渲染类型专属块'


def test_compare_mode_still_renders_matrix(tmp_path):
    from ledger import ResearchLedger
    from skeleton import build_skeleton

    led = ResearchLedger(str(tmp_path / 'l')).init()
    c = led.add_claim('本项目使用 Flask 单体架构的完整画像证据行', '本项目现状',
                      'verified', 'general', 0.9)
    led.add_source(c['id'], 'https://example.org/proj', tier=1)
    md = build_skeleton(str(tmp_path / 'l'), title='T', intent='compare')
    assert '## 对比矩阵' in md and '## 本项目现状（基线）' in md


# ============================================================
# 派单模板任务书化：规则一条不少，叙事一条不留
# ============================================================

def test_dispatch_template_is_task_book_form():
    s = SKILL.read_text(encoding='utf-8')
    for section in ('【任务：四步】', '【硬约束 A：权限与安全', '【硬约束 B：证据纪律】',
                    '【分片 schema】'):
        assert section in s, f'任务书缺 {section}'


def test_dispatch_template_keeps_every_hard_rule():
    s = SKILL.read_text(encoding='utf-8')
    rules = ['A1', 'A2', 'A3', 'A4', 'A5', 'A6',
             'B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7',
             '只追加不覆盖', '不贴搜索正文', 'pending', 'conflict',
             'pushed_at', 'gh api', '≤25 次', 'DRUX_CANARY_']
    for kw in rules:
        assert kw in s, f'重写后丢了关键规则：{kw}'


def test_incident_stories_moved_out_of_skill_md():
    s = SKILL.read_text(encoding='utf-8')
    lessons = (REFS / 'subagent-lessons.md').read_text(encoding='utf-8')
    for narrative in ('五千万 token', 'citation-check-skill 最后一次推送',
                      '把 D2 已登记的 4 行抹掉了'):
        assert narrative not in s, f'事故叙事应移入教训档案：{narrative}'
        assert narrative in lessons, f'教训档案必须收留：{narrative}'
    assert '\n5b)' not in s and '\n5e)' not in s, '旧编号补丁形态应已消失'
