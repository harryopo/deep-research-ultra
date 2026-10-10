"""v6.61.0：子 Agent 按角色配模型（对比实跑报告三项建议里的最后一个 P1）。

同行证据：open_deep_research 给 4 个角色各配一档模型，GPT Researcher 用快模型
爬摘要、强模型写终稿。本项目此前没有档位概念——检索跑腿和判断写作吃同一档，
要么浪费（判断型工作给轻档）要么拖累（跑腿用最强档）。

只锁文档不管用，Lead 未必翻到 Phase 2.5 才派单。所以锁三件事：
1. SKILL.md 的 Phase 2.5（派单处）有配档表，检索/判断/Lead 三个角色都在，
   且带"宿主的 Agent 工具没有 model 参数就忽略本表"的护栏——没有这条，
   Lead 可能为了配模型把并行扇出退化成亲自串行跑，那是丢大头保小头；
2. `--plan-only` 回执打「派单模型」行——回执是派单前最后一眼，档位写在这
   才有人照抄（分波上限就是这么落地的，见 test_v6350）；
3. 两个环境变量真的改变回执，否则 DRUX_MODEL_* 就是死配置。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SKILL = SCRIPTS.parent / 'SKILL.md'
sys.path.insert(0, str(SCRIPTS))


def _phase25_block() -> str:
    """截 Phase 2.5 标题到「子 Agent 提示词模板」之间的正文。

    配档表必须长在派单那一节：写在别处，Lead 拼任务书时一个字都看不到。
    """
    md = SKILL.read_text(encoding='utf-8')
    after = md.split('### Phase 2.5:', 1)
    assert len(after) == 2, 'SKILL.md 找不到 Phase 2.5 小节'
    block = after[1].split('**子 Agent 提示词模板**', 1)
    assert len(block) == 2, ('Phase 2.5 后面没有子 Agent 模板——'
                             '截取锚点失效，下面的断言会截错地方')
    return block[0]


def _receipt(env_extra: dict | None = None) -> str:
    env = dict(os.environ)
    env.pop('DRUX_MODEL_RETRIEVER', None)
    env.pop('DRUX_MODEL_REVIEWER', None)
    env.update(env_extra or {})
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / 'research.py'), '模型配档回归主题',
         '--plan-only', '--effort', 'standard'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(SCRIPTS), env=env)
    return (out.stdout or '') + (out.stderr or '')


def test_positive_control_the_anchor_pair_exists():
    """上面的截取要红绿都截在同一块，否则后面几条可能在断言空气。"""
    block = _phase25_block()
    assert '模型配档' in block, 'Phase 2.5 里没有模型配档小节'
    assert '每波' in block, '截到的不是 Phase 2.5（分波派发说明不见了）'


def test_routing_table_covers_all_three_roles():
    block = _phase25_block()
    assert '检索子 Agent' in block, '配档表没给检索子 Agent 档位'
    assert '判断型子 Agent' in block, '配档表没给判断型角色档位'
    assert '不传 `model`' in block, '配档表没写 Lead 不传 model（Lead 被降级最致命）'
    for var in ('DRUX_MODEL_RETRIEVER', 'DRUX_MODEL_REVIEWER'):
        assert var in block, f'配档表没点名 {var}，环境变量形同虚设'


def test_host_without_model_param_degrades_to_ignoring_not_to_serial():
    """宿主不支持 model 参数时是"忽略本表"，不是"改走串行"。"""
    block = _phase25_block()
    assert '没有 `model` 参数' in block, '没写宿主不支持 model 参数时怎么办'
    assert '忽略本表' in block, '没写"忽略"，Lead 会自己发明处置方式'
    assert '串行' in block, ('没点名禁止退化成 Lead 亲自串行跑——'
                             '配模型是省成本，不是拿并行扇出换的')


def test_plan_receipt_prints_model_line_without_env():
    text = _receipt()
    assert '派单模型' in text, f'--plan-only 回执没有派单模型行：{text[:400]}'
    # 未设变量时要把变量名露出来，Lead 才知道有开关可拧
    assert 'DRUX_MODEL_RETRIEVER' in text, '回执没报检索档的变量名'
    assert 'DRUX_MODEL_REVIEWER' in text, '回执没报判断档的变量名'
    assert 'Lead 不传 model' in text, '回执没写 Lead 不传 model'


def test_env_vars_change_the_receipt():
    """死配置防线：设了 DRUX_MODEL_* 必须原样出现在回执里。"""
    text = _receipt({'DRUX_MODEL_RETRIEVER': 'model-fast-x',
                     'DRUX_MODEL_REVIEWER': 'model-strong-y'})
    assert 'DRUX_MODEL_RETRIEVER=model-fast-x' in text, '检索档变量没生效（死配置）'
    assert 'DRUX_MODEL_REVIEWER=model-strong-y' in text, '判断档变量没生效（死配置）'
