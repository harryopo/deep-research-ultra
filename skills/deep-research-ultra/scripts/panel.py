"""
panel.py — 深度调研专家团评审清单生成（Expert Panel）  [v6.0 新增]

为调研大纲/章节草稿生成"多角色评审提问清单"，供主 Agent（Lead）与子 Agent 执行补查。
借鉴：STORM 多视角提问 + RedDebate 红蓝对抗 + GPT Researcher reviewer-revisor 闭环。

设计约束（重要）：
- 本模块 **只输出结构化评审清单（提示词模板 + JSON 契约）**，不真正调用 LLM；
  由主 Agent 读入清单后，用自身推理能力对草稿/大纲执行评审。
- 输出契约稳定：所有输出均为 JSON 可序列化结构，便于主 Agent 逐项消化。
- 默认 5 个内置角色；perspectives 可自定义（传 dict 列表）。

输出契约：
  review_outline  → {"perspectives": [{"role", "focus", "questions": [..]}]}
  review_draft    → {"role", "focus", "findings": [{"type", "detail", "action"}]}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PERSPECTIVES = [
    {
        'role': 'domain_expert',
        'label': '域专家',
        'focus': '事实准确性、术语正确性、专业深度与遗漏的关键子领域',
        'review_outline_questions': [
            '该子主题是否覆盖了本领域公认的核心分支？',
            '哪些术语/概念可能被误用或过时？',
            '该主题下最权威的一手来源（论文/标准/官方）是否应补充？',
            '若由领域内行家检验，哪些表述最可能被质疑？',
        ],
        'draft_findings': [
            '指出草稿中事实性错误或可疑断言',
            '指出被忽略的关键子领域/反例',
            '评估引用的权威性是否足够（是否偏重低质源）',
        ],
    },
    {
        'role': 'skeptic',
        'label': '怀疑者（红队）',
        'focus': '反例、矛盾、过时信息、利益相关偏置（对抗性质疑）',
        'review_outline_questions': [
            '每个子问题是否存在被主流叙事掩盖的反例？',
            '哪些来源可能与利益相关（厂商/机构立场）需要警示？',
            '该问题是否存在"通过率极高但证据链薄弱"的结论?',
        ],
        'draft_findings': [
            '指出结论与证据不匹配之处（claim-evidence gap）',
            '指出可能已过时（≥2 年且领域快速演进）的结论',
            '指出可证伪但未被检验的假设（红队攻击面）',
        ],
    },
    {
        'role': 'practitioner',
        'label': '实践者',
        'focus': '可落地性、工程代价、成本投入、与真实使用场景的贴合度',
        'review_outline_questions': [
            '每个方案/结论在真实环境中实施的主要障碍是什么？',
            '是否缺少成本（算力/时间/人力）维度的对比？',
            '哪些资源（教程/工具链/开源实现）应作为附录/延伸阅读？',
        ],
        'draft_findings': [
            '指出"理论上可行但实践中不现实"的陈述',
            '评估报告是否给出可操作的落地路径（步骤/工具/约束）',
            '指出缺失的成本或规模数字',
        ],
    },
    {
        'role': 'reporter',
        'label': '记者',
        'focus': '遗漏事实、多方叙事、时间线、关键人物与事件完整性',
        'review_outline_questions': [
            '该主题的时间线/关键里程碑是否完整？',
            '是否存在二选一之外的第三方观点或叙事？',
            '关键背景（为何重要/影响谁）是否交代清楚？',
        ],
        'draft_findings': [
            '指出被省略但与主题直接相关的重要事实/事件',
            '指出单边叙事（只有一方面观点）的段落',
            '检查是否缺少时间线或发展脉络',
        ],
    },
    {
        'role': 'cost_analyst',
        'label': '成本视角',
        'focus': '选项的成本-收益比较、规模敏感性与预算约束（适用于方案类调研）',
        'review_outline_questions': [
            '各候选方案是否有可比的价格/成本数据？',
            '是否评价了"性价比"或投入产出比而非只有能力排名？',
            '成本是否会随规模变化（临界点在哪）？',
        ],
        'draft_findings': [
            '指出缺乏量化的成本对比之处',
            '指出给出成本数据的来源层级与时效',
            '评估结论是否考虑了预算约束的现实性',
        ],
    },
]


class PanelReviewer:
    """专家团评审清单生成器。"""

    def __init__(self, perspectives: Optional[List[Dict[str, Any]]] = None):
        self.perspectives = perspectives or PERSPECTIVES

    # ------------------------------------------------------------------
    # 远程获取默认角色与大纲评审清单
    # ------------------------------------------------------------------
    def default_perspectives(self) -> List[Dict[str, Any]]:
        """返回内置角色定义（label + focus）。"""
        return [{'role': p['role'], 'label': p['label'], 'focus': p['focus']}
                for p in self.perspectives]

    def review_outline(self, outline: str,
                       perspectives: Optional[List[str]] = None) -> Dict[str, Any]:
        """对调研大纲/子问题清单生成各角色评审问题清单。

        Args:
            outline: 大纲文本（子问题列表 / plan-only 输出）
            perspectives: 指定角色（role 列表），None = 全部

        Returns:
            {"perspectives": [{"role", "label", "focus", "questions": [...]}]}
        """
        want = set(perspectives or [])
        out = []
        for p in self.perspectives:
            if want and p['role'] not in want:
                continue
            out.append({
                'role': p['role'], 'label': p['label'], 'focus': p['focus'],
                'questions': [
                    f'【{p["label"]}】{q}（原文上下文见大纲："{_snip(outline, 60)}"）'
                    for q in p['review_outline_questions']
                ],
            })
        return {'perspectives': out}

    def review_draft(self, draft: str,
                     perspective: str = 'domain_expert') -> Dict[str, Any]:
        """对单章节草稿生成指定角色的评审发现契约（供主 Agent 消化执行）。

        Returns:
            {"role", "label", "focus", "findings": [{"type", "detail", "action"}]}
        """
        p = next((x for x in self.perspectives if x['role'] == perspective), self.perspectives[0])
        return {
            'role': p['role'], 'label': p['label'], 'focus': p['focus'],
            'findings': [
                {
                    'type': _finding_type(t),
                    'detail': f'【{p["label"]}】{t}',
                    'action': '补充检索并修订' if _finding_type(t) in ('gap', 'evidence_needed')
                              else '核验冲突来源后修订',
                }
                for t in p['draft_findings']
            ],
            '_note': '这是评审契约（提示词模板），请逐条消化后对草稿执行补查；',
        }

    # ------------------------------------------------------------------
    # 快捷: 生成"补查问题"（供子 Agent prompt 拼接）
    # ------------------------------------------------------------------
    def supplement_questions(self, outline: str,
                             perspectives: Optional[List[str]] = None) -> List[str]:
        """扁平化输出全部评审问题（一次性拼进子 Agent 提示词）。"""
        data = self.review_outline(outline, perspectives)
        return [q for p in data['perspectives'] for q in p['questions']]


def _finding_type(template: str) -> str:
    """从模板文本粗判 finding 类型。"""
    for kw, typ in (('矛盾', 'contradiction'), ('证据', 'evidence_needed'),
                    ('过时', 'contradiction'), ('省略', 'gap'), ('缺失', 'gap'),
                    ('遗漏', 'gap'), ('不匹配', 'contradiction')):
        if kw in template:
            return typ
    return 'gap'


def _snip(text: str, n: int = 60) -> str:
    t = ' '.join(str(text).split())
    return t if len(t) <= n else t[:n] + '…'


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        print('''\n用法:
  python panel.py perspectives                      # 列出内置角色
  python panel.py review-outline --input <file|text> [--roles r1,r2]
  python panel.py supplement-questions --input <file|text> [--roles r1,r2]
  python panel.py review-draft --input <file|text> --role <role>''')
        return 0

    reviewer = PanelReviewer()
    cmd = args[0]

    def _input() -> str:
        if '--input' not in args:
            print('缺少 --input <file|text>', file=sys.stderr)
            sys.exit(2)
        raw = args[args.index('--input') + 1]
        if Path(raw).exists():
            return Path(raw).read_text(encoding='utf-8')
        return raw

    def _roles():
        if '--roles' in args:
            return [r.strip() for r in args[args.index('--roles') + 1].split(',')]
        return None

    if cmd == 'perspectives':
        print(json.dumps(reviewer.default_perspectives(), ensure_ascii=False, indent=2))
        return 0

    if cmd == 'review-outline':
        print(json.dumps(reviewer.review_outline(_input(), _roles()),
                         ensure_ascii=False, indent=2))
        return 0

    if cmd == 'supplement-questions':
        print(json.dumps(reviewer.supplement_questions(_input(), _roles()),
                         ensure_ascii=False, indent=2))
        return 0

    if cmd == 'review-draft':
        role = 'domain_expert'
        if '--role' in args:
            role = args[args.index('--role') + 1]
        print(json.dumps(reviewer.review_draft(_input(), role), ensure_ascii=False, indent=2))
        return 0

    print(f'未知命令: {cmd}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    from console import force_utf8
    force_utf8()
    sys.exit(_main())