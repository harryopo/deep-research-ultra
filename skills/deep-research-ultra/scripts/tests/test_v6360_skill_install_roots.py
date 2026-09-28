"""全局 skill 的安装位清单只许有一份，且要覆盖装机实际在用的根。

实测缺陷清单之外的连带发现（2026-09-28，回答"agent-reach 没装会怎样"时抓到的）：
- `env_check._check_skill` 只扫 `~/.agents/skills` 与 `~/.claude/skills`；
- `skill_engines._get_skill_directories` 扫的是另外四个根，**不含 `~/.agents/skills`**，
  而本机 sciverse / defuddle / oss-finder 就装在那里。

两边各写一份的代价：同一台机器上，`--env-check` 说"装了"，skill 封装的引擎却说"没装"
（于是 🤖 那一档的源在回执与真实取数之间反复矛盾）；而装在 Qoder 自己的
`~/.qoder/skills` 下的 skill，两边都看不见——明明装了却被判缺失，用户会照着提示重复安装。
"""

from __future__ import annotations

import pathlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import env_check  # noqa: E402
from engines import skill_engines  # noqa: E402

ROOTS = ('.agents', '.qoder', '.claude')


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """假装一台机器：同一个 skill 只装在 ~/.qoder/skills 下。"""
    d = tmp_path / '.qoder' / 'skills' / 'agent-reach'
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_text('name: agent-reach\n', encoding='utf-8')
    monkeypatch.setattr(pathlib.Path, 'home', staticmethod(lambda: tmp_path))
    return tmp_path


def test_skill_lookup_sees_the_qoder_root(fake_home):
    assert skill_engines.is_skill_installed('agent-reach'), \
        '装在 ~/.qoder/skills 的 skill 被判成未安装'


def test_env_check_and_engine_layer_agree(fake_home):
    """两处判据必须同源：一个说装了、另一个说没装，Lead 就没法照回执行动。"""
    ok, detail = env_check._check_skill('agent-reach')
    assert ok, f'--env-check 看不见它：{detail}'
    assert skill_engines.is_skill_installed('agent-reach')
    assert Path(detail).exists(), f'env-check 回的不是一个真实路径：{detail}'


def test_the_agents_root_is_in_the_shared_list(fake_home):
    """`~/.agents/skills` 必须在共用的根清单里——这是多数 Agent 的默认安装位。"""
    (fake_home / '.agents' / 'skills' / 'oss-finder').mkdir(parents=True)
    (fake_home / '.agents' / 'skills' / 'oss-finder' / 'SKILL.md').write_text(
        'name: oss-finder\n', encoding='utf-8')

    assert skill_engines.skill_install_path('oss-finder') is not None


def test_missing_skill_says_where_it_looks(fake_home):
    """判"没装"时要说清找过哪些根，否则用户会往一个它不看的目录里装。"""
    ok, detail = env_check._check_skill('not-installed-at-all')

    assert not ok
    assert '.qoder' in detail or 'agents' in detail, detail
