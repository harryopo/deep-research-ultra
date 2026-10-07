"""报告骨架生成器（v6.14）——把报告的机械部分从 Lead 手里拿走。

X-D14 的实况：deep 档定义 6000-15000 字、2-3 轮反思，一轮根本写不完，
写不完又要过校验门，人就开始用占位内容糊一份"看起来完成"的报告。
所以分工改了：引用编号、来源登记表、按主题排好的 claim 清单由账本直接生成，
Lead 只写机器写不了的东西——摘要、判断、连接与落地建议。

骨架里 Lead 必须写掉的段落带【待写】标记，validate_report.py 把该标记判为硬失败，
因此骨架不可能被当成报告交付；要出门必须先把标记写没。未验证的 claim 不占标记——
它们渲染成"⚠️ 仅作线索"，几十条 pending 不至于逼出几十处待写。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ledger import ResearchLedger, _one_line
except ImportError:  # 作为包导入时
    from scripts.ledger import ResearchLedger, _one_line  # type: ignore

PLACEHOLDER = '【待写】'

# v6.55 报告类型学（references/report-types.md）：各类型在维度分节后追加的
# 类型专属骨架块。compare 有独立渲染路径（基线/候选/矩阵），不在此表。
_INTENT_EXTRA_SECTIONS = {
    'academic': [('## 研究空白与机会',
                  [PLACEHOLDER + ' 哪些问题尚无定论、哪些数据互相矛盾、哪里值得再挖——每条挂 [N]'])],
    'business': [('## 竞争格局速览',
                  ['', '| 玩家 | 定位 | 规模（口径与年份） | 商业模式 | 来源 |',
                   '|---|---|---|---|---|',
                   f'| {PLACEHOLDER} | | | | |', f'| {PLACEHOLDER} | | | | |',
                   f'| {PLACEHOLDER} | | | | |'])],
    'risk': [('## 风险登记表',
              ['', '| 风险 | 证据 [N] | 可能性 | 影响 | 缓解 |', '|---|---|---|---|---|',
               f'| {PLACEHOLDER} | | | | |', f'| {PLACEHOLDER} | | | | |',
               f'| {PLACEHOLDER} | | | | |'])],
    'opensource': [('## 引入成本与迁移建议',
                    [PLACEHOLDER + ' 改造点 / 依赖冲突 / 迁移步骤 / 回滚方案——每条四要素'
                     '（改什么 / 依据 [N] / 成本与风险 / 优先级）'])],
}


def _citations(sources_of_claim: List[Dict[str, Any]]) -> str:
    """按账本 primary_index 生成 [N] 引用，编号顺序稳定。"""
    return ''.join(f"[{s['primary_index']}]"
                   for s in sorted(sources_of_claim, key=lambda x: x['primary_index']))


def _sources_by_claim(sources: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for s in sources:
        grouped.setdefault(s.get('claim_id', ''), []).append(s)
    return grouped


def _host(url: str) -> str:
    """注册域近似值（只用于给 Lead 一句"独立域名有几个"的事实）。"""
    tail = str(url).split('://')[-1]
    return tail.split('/')[0].lower().removeprefix('www.')


def _split_lead_sections(md: str) -> Dict[str, str]:
    """按固定二级标题切旧报告：header/一页拍板/执行摘要/topics/调研方法/结论与建议/来源。

    给 --merge-from 用：重生成骨架时把 Lead 写完的段落原样搬回来，claim 行与
    登记表按新账本重新渲染。
    """
    buckets: Dict[str, List[str]] = {'header': []}
    cur = 'header'
    for ln in md.split('\n'):
        m = re.match(r'^##\s*(.+?)\s*$', ln)
        if m:
            name = m.group(1)
            if name.startswith('一页拍板'):
                cur = 'bluf'
            elif name.startswith('执行摘要'):
                cur = 'summary'
            elif name.startswith('调研方法'):
                cur = 'method'
            elif name.startswith('结论与建议'):
                cur = 'conclusion'
            elif name.startswith('来源'):
                cur = 'tail'
            else:
                cur = 'topics'
            buckets.setdefault(cur, [])
            continue
        buckets.setdefault(cur, []).append(ln)
    return {k: '\n'.join(v).strip('\n') for k, v in buckets.items()}


def _reusable(block: str) -> bool:
    """Lead 真写完了的段才可保留：空段与仍带【待写】的一律不保留（占位内容不出门）。"""
    return bool(block.strip()) and PLACEHOLDER not in block


def build_skeleton(ledger_dir: str, title: str = '', merge_from: str = '',
                   intent: str = '') -> str:
    """读账本 → 出报告骨架（章节齐、引用齐、来源登记表齐，正文留【待写】）。

    intent='compare'（v6.54 对比/优化类）：主题命名约定——`本项目*`=基线，
    `候选：X`=候选方案，其余主题=对比维度。渲染顺序：基线 → 候选逐个 →
    对比矩阵（行=维度，列=方案，格子【待写】）→ 维度证据。

    merge_from 给旧报告路径时（v6.52）：一页拍板/执行摘要/调研方法/结论与建议、
    文件头元数据、以及每条冲突 claim 下的「**裁决**」行，凡 Lead 已写完（不含
    【待写】）的原样保留；claim 行与来源登记表按**当前账本**重新渲染。这消掉了
    流程红线①的真实成本——改账本状态后重生成，Lead 不用再手贴六段。
    """
    led = ResearchLedger(ledger_dir)
    led.require()
    data = led.export_json()
    claims, sources = data['claims'], data['sources']
    grouped = _sources_by_claim(sources)
    verified = sum(1 for c in claims if c['status'] == 'verified')
    conflicts = sum(1 for c in claims if c['status'] == 'conflict')
    hedged = len(claims) - verified - conflicts

    kept: Dict[str, str] = {}
    verdicts: Dict[str, str] = {}
    if merge_from:
        old_md = Path(merge_from).read_text(encoding='utf-8')
        kept = _split_lead_sections(old_md)
        # 裁决行归属：跟在哪个 claim 行后——claim 文本前 16 字在行内匹配，
        # 与 validate_report.cited_claim_ids 的前缀口径同一套。
        prefix16 = {str(c.get('text', ''))[:16]: c['id']
                    for c in claims if len(str(c.get('text', ''))) >= 16}
        last_claim_line = ''
        for ln in old_md.split('\n'):
            if ln.startswith('- '):
                last_claim_line = ln
                continue
            if re.match(r'^\s{2}\*\*裁决\*\*', ln) and last_claim_line:
                cid = next((pid for pref, pid in prefix16.items()
                            if pref in last_claim_line), '')
                if cid and cid not in verdicts:
                    verdicts[cid] = ln.strip()

    facts = (f'账本事实：claims {len(claims)} 条（verified {verified} / 仅作线索 {hedged}'
             f' / 来源冲突 {conflicts}），'
             f'来源 {len(sources)} 条，独立域名 {len({_host(s.get("url", "")) for s in sources})} 个。')

    if _reusable(kept.get('header', '')):
        lines: List[str] = kept['header'].split('\n')
    else:
        lines = [f'# {title or "调研报告"}', '']

    if _reusable(kept.get('bluf', '')):
        lines += ['## 一页拍板', kept['bluf'], '']
    else:
        lines += ['## 一页拍板',
                  f'{PLACEHOLDER} 给"要拍板的人"用：直接给结论/推荐（该选哪个、或这件事该怎么做）、'
                  '主要风险、以及下一步动作。每条判断挂 [N]。'
                  '决策类调研必须写出明确推荐——"各有优劣、看你需求"不算结论。', '']
    if _reusable(kept.get('summary', '')):
        lines += ['## 执行摘要', kept['summary'], '']
    else:
        lines += ['## 执行摘要',
                  f'{PLACEHOLDER} 3-5 句给出最关键结论、置信度与适用边界（上限 1200 字）', '']

    order: List[str] = []
    for c in claims:
        if c['topic'] not in order:
            order.append(c['topic'])

    def _render_claims(topic: str) -> List[str]:
        out: List[str] = []
        for c in [x for x in claims if x['topic'] == topic]:
            cite = _citations(grouped.get(c['id'], []))
            # 成立范围（样本/数据源/年份/是否同行评议）跟着结论走：缺了它，一个百分比
            # 就会被当成普适结论引用（2026-09-29 外部清单问题 3/4 的实形）
            scope = f"（成立范围：{_one_line(c.get('scope'))}）" if c.get('scope') else ''
            flag = '🚩 L3不可信：' if c.get('untrusted') else ''
            if c['status'] == 'verified':
                out.append(f"- {flag}{_one_line(c['text'])} {cite}{scope}")
            elif c['status'] == 'conflict':
                # 标签只说账本里查得到的事实：有没有留过取舍、留的是什么。
                # 过去一律印"待裁决"，第七轮把三组冲突裁完并写了 note 之后，
                # 这个标签就成了对过程状态的谎报——读者以为还没给结论，账本里每条都记着取舍。
                note = _one_line(c.get('note'))
                tag = f'（账本留痕：{note}）' if note else '（未裁决）'
                out.append(f"- ⚠️ 来源冲突{tag}：{flag}{_one_line(c['text'])} {cite}{scope}")
                v = verdicts.get(c['id'])
                out.append(v if v else
                           f'  {PLACEHOLDER} 写清两方证据、分歧根源与本报告的取舍')
            else:
                # 未验证项渲染成"仅作线索"，不逐条留【待写】：标准档一次 60 条 claim
                # 会逼出几十处待写标记，逐条处置超出单轮产能，结果反而是拿模板句把标记
                # 刷没（2026-09-22 实跑撞上：骨架 40 处【待写】）。未验证的可见性由
                # ⚠️ 承担，validate_report 的"引用未验证 claim 必须带 ⚠️"照旧把关。
                out.append(f"- ⚠️ 仅作线索：{flag}{_one_line(c['text'])} {cite}{scope}"
                           f"（状态 {c['status']}，未达 verified 判据）")
        return out

    if intent == 'compare':
        # v6.54 对比/优化类：本项目基线 → 候选方案逐个 → 对比矩阵 → 维度证据。
        # 报告要回答的是"本项目和候选差在哪、怎么办"，不是维度流水账。
        baseline = [t for t in order if t.startswith('本项目')]
        cands = [t for t in order if t.startswith('候选：')]
        dims = [t for t in order if t not in baseline and t not in cands]
        lines += ['## 本项目现状（基线）', '',
                  f'{PLACEHOLDER} 主体画像分析：技术栈、架构、部署形态、已知痛点——'
                  '用读者视角写分析性段落，引用下方证据的 [N]。', '']
        for t in baseline:
            lines += _render_claims(t)
        lines.append('')
        lines += ['## 候选方案', '']
        for t in cands:
            lines += [f'### {t}', '',
                      f'{PLACEHOLDER} 分析性段落：定位、架构、优劣——'
                      '引用下方证据的 [N]，逐维度写差异与优劣。', '']
            lines += _render_claims(t)
            lines.append('')
        lines += ['## 对比矩阵', '',
                  '> 每格写结论＋[N]；本项目列只写有据事实——对比缺基线就是空对空。', '']
        header = '| 对比维度 | 本项目 |' + ''.join(
            f' {t[len("候选："):]} |' for t in cands)
        lines.append(header)
        lines.append('|' + '---|' * (2 + len(cands)))
        for d in dims:
            lines.append(f'| {d} | {PLACEHOLDER} |' + f' {PLACEHOLDER} |' * len(cands))
        lines.append('')
        if not baseline:
            lines += ['> ⚠️ 账本里没有「本项目现状」主题——对比缺基线。先做主体画像'
                      '（SKILL.md Phase 1.2b），否则矩阵的本项目列只能填空。', '']
        lines += ['## 对比维度证据', '']
        for d in dims:
            lines += [f'### {d}', '']
            lines += _render_claims(d)
            lines.append('')
    else:
        for topic in order:
            lines += [f'## {topic}', '']
            lines += _render_claims(topic)
            lines.append('')
        for heading, block_lines in _INTENT_EXTRA_SECTIONS.get(intent, []):
            lines += [heading] + block_lines + ['']

    if _reusable(kept.get('method', '')):
        # 账本事实行按新账本刷新；旧声明/判定注释不搬——按新状态重新出
        method_text = re.sub(r'^账本事实：.*$', lambda _m: facts,
                             kept['method'], flags=re.M)
        method_lines = [l for l in method_text.split('\n')
                        if not l.strip().startswith('选型调研')
                        and not l.strip().startswith('<!-- 选型调研')]
        lines += ['## 调研方法'] + method_lines
    else:
        lines += ['## 调研方法',
                  f'{PLACEHOLDER} 写检索窗口、数据源分层、子 Agent 分工与 verified 判据（档 A/档 B）',
                  facts]
    # 校验门见到仓库链接就要求六维（风险/许可证/维护/适配/落地/量化）。报告里只是
    # 引某个仓库当证据时，这六项不相关——v6.52 起发布门按"仓库是否出现在决策节"
    # 自动判定，这里只留指引注释；Lead 仍可写显式声明行覆盖自动判定。
    # （v6.15-v6.51 在这里无条件写"选型调研: 是"，把引证据的报告逼成手工改行。）
    if any('github.com' in str(s.get('url', '')) or 'gitee.com' in str(s.get('url', ''))
           for s in sources):
        lines.append('<!-- 选型调研判定：仓库链接只出现在证据节时，发布门自动豁免六维；'
                     '出现在一页拍板/执行摘要/结论与建议里则按选型走六维门。'
                     '要显式指定，可写一行以「选型调研」开头接是或否的声明 -->')
    lines.append('')

    concl_ph = f'{PLACEHOLDER} 结论、风险、落地步骤（这一节是机器给不了的）'
    if intent == 'compare':
        concl_ph += ('\n\n### 优化建议（对比类必填）\n'
                     '每条四要素：**改什么** / **依据 [N]** / **成本与风险** / '
                     '**优先级（P0-P2）**；"值得借鉴"必须落到可执行的改动上')
    if _reusable(kept.get('conclusion', '')):
        lines += ['## 结论与建议', kept['conclusion'], '']
    else:
        lines += ['## 结论与建议', concl_ph, '']

    lines += ['## 来源', '', '| 编号 | Tier | 标题 | URL |',
              '|------|------|------|-----|']
    for s in sources:
        url = str(s.get('url', '')).strip()
        head = str(s.get('title', '')).strip() or url
        lines.append(f"| [{s['primary_index']}] | {s.get('tier', '-')} "
                     f"| {head} | {url} |")
    lines += ['', '---',
              '> 本文件由 `skeleton.py` 从证据账本生成，引用编号与来源登记表不可手改。'
              '标了"待写"的段落（摘要 / 调研方法 / 结论建议 / 每条冲突的裁决）必须由 Lead 写掉——'
              '标记不删净就过不了校验门，骨架也就永远不会被当成报告交付。'
              '未验证的 claim 已就地渲染为 ⚠️ 仅作线索，不必逐条改写；'
              '但正文引用它们时不得写成结论，校验门会查这处标注。']
    return '\n'.join(lines) + '\n'


def _main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        print('用法:\n  python skeleton.py <ledger_dir> [-o report_skeleton.md] '
              '[--title "报告标题"] [--merge-from 旧报告.md] [--intent compare]')
        return 0
    ledger_dir = args[0]
    out = args[args.index('-o') + 1] if '-o' in args and args.index('-o') + 1 < len(args) else ''
    title = args[args.index('--title') + 1] if '--title' in args else ''
    intent = ''
    if '--intent' in args:
        i = args.index('--intent')
        intent = args[i + 1] if i + 1 < len(args) else ''
    merge_from = ''
    if '--merge-from' in args:
        i = args.index('--merge-from')
        merge_from = args[i + 1] if i + 1 < len(args) else ''

    try:
        md = build_skeleton(ledger_dir, title, merge_from=merge_from, intent=intent)
    except FileNotFoundError as exc:
        print(f'❌ {exc}', file=sys.stderr)
        return 2
    if out:
        Path(out).write_text(md, encoding='utf-8')
        kept = sum(1 for ln in md.split('\n') if ln.strip().startswith('**裁决**'))
        print(f'✅ 骨架已生成: {out}（{md.count(PLACEHOLDER)} 处 {PLACEHOLDER} 待 Lead 写完'
              + (f'；--merge-from 保留了裁决 {kept} 条' if merge_from else '') + '）')
    else:
        print(md)
    return 0


if __name__ == '__main__':
    from console import force_utf8
    force_utf8()
    sys.exit(_main())
