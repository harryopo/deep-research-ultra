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

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ledger import ResearchLedger
except ImportError:  # 作为包导入时
    from scripts.ledger import ResearchLedger  # type: ignore

PLACEHOLDER = '【待写】'


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


def build_skeleton(ledger_dir: str, title: str = '') -> str:
    """读账本 → 出报告骨架（章节齐、引用齐、来源登记表齐，正文留【待写】）。"""
    led = ResearchLedger(ledger_dir)
    led.require()
    data = led.export_json()
    claims, sources = data['claims'], data['sources']
    grouped = _sources_by_claim(sources)
    verified = sum(1 for c in claims if c['status'] == 'verified')
    conflicts = sum(1 for c in claims if c['status'] == 'conflict')
    hedged = len(claims) - verified - conflicts

    lines: List[str] = [f'# {title or "调研报告"}', '']
    lines += ['## 执行摘要',
              f'{PLACEHOLDER} 3-5 句给出最关键结论、置信度与适用边界（上限 1200 字）', '']

    order: List[str] = []
    for c in claims:
        if c['topic'] not in order:
            order.append(c['topic'])
    for topic in order:
        lines += [f'## {topic}', '']
        for c in [x for x in claims if x['topic'] == topic]:
            cite = _citations(grouped.get(c['id'], []))
            if c['status'] == 'verified':
                lines.append(f"- {c['text']} {cite}")
            elif c['status'] == 'conflict':
                lines.append(f"- ⚠️ 冲突待裁决：{c['text']} {cite}")
                lines.append(f'  {PLACEHOLDER} 写清两方证据、分歧根源与本报告的取舍')
            else:
                # 未验证项渲染成"仅作线索"，不逐条留【待写】：标准档一次 60 条 claim
                # 会逼出几十处待写标记，逐条处置超出单轮产能，结果反而是拿模板句把标记
                # 刷没（2026-09-22 实跑撞上：骨架 40 处【待写】）。未验证的可见性由
                # ⚠️ 承担，validate_report 的"引用未验证 claim 必须带 ⚠️"照旧把关。
                lines.append(f"- ⚠️ 仅作线索：{c['text']} {cite}"
                             f"（状态 {c['status']}，未达 verified 判据）")
        lines.append('')

    lines += ['## 调研方法',
              f'{PLACEHOLDER} 写检索窗口、数据源分层、子 Agent 分工与 verified 判据（档 A/档 B）',
              f'账本事实：claims {len(claims)} 条（verified {verified} / 仅作线索 {hedged}'
              f' / 冲突待裁决 {conflicts}），'
              f'来源 {len(sources)} 条，独立域名 {len({_host(s.get("url", "")) for s in sources})} 个。', '']

    lines += ['## 结论与建议', f'{PLACEHOLDER} 结论、风险、落地步骤（这一节是机器给不了的）', '']

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
              '[--title "报告标题"]')
        return 0
    ledger_dir = args[0]
    out = args[args.index('-o') + 1] if '-o' in args and args.index('-o') + 1 < len(args) else ''
    title = args[args.index('--title') + 1] if '--title' in args else ''

    try:
        md = build_skeleton(ledger_dir, title)
    except FileNotFoundError as exc:
        print(f'❌ {exc}', file=sys.stderr)
        return 2
    if out:
        Path(out).write_text(md, encoding='utf-8')
        print(f'✅ 骨架已生成: {out}（{md.count(PLACEHOLDER)} 处 {PLACEHOLDER} 待 Lead 写完）')
    else:
        print(md)
    return 0


if __name__ == '__main__':
    from console import force_utf8
    force_utf8()
    sys.exit(_main())
