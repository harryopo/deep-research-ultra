"""v6.53.1 回归：Agent-Reach 社区通道接入——登录态通道按用户红线禁用（文档钉）。"""

from __future__ import annotations

from pathlib import Path


def test_skill_md_agent_reach_login_channels_are_disabled_by_policy():
    skill = (Path(__file__).resolve().parents[2] / 'SKILL.md').read_text(encoding='utf-8')
    assert '登录态通道红线' in skill, '社区通道必须有登录态红线声明'
    assert '一律不得配置或调用' in skill, '红线必须是硬禁令，不是建议'
    assert '仅免登录通道' in skill, '社区 Agent 的通道集要按实际可用面写'
    assert '由 L4' in skill and 'canary' in skill, '出带不在 L1 白名单内的说明要写清'
