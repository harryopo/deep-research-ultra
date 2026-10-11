"""claim_support.py — 作者手写段的"这句话在我引用的 claim 里找得到吗"自查。

## 为什么要有这个工具（一次攻击实验逼出来的）

v6.62 堵住了"没有账本"（无 `--ledger` 判未通过）。但那是浅水区。这次构造的攻击是：

    账本里有一条 verified claim：「RAG 评测框架 A 的召回率高于框架 B」
    报告写  ：「框架 B 的召回率显著低于框架 A [1]，且单次查询成本更高 [1]」
    [1] 指向那条 claim 的真实来源，编号合法、URL 出现、无串号、章节齐全

→ `validate_report` **passed=True、0 issues、盖上了防伪戳**。

也就是说：校验门证明的是"编号有对应来源"，**不是"这句话被那个来源支撑"**。
这正是 ACL 2026 测的 citation faithfulness（引用的断言是否真被该源支撑）。

## 为什么只查数字，不查语义

语义忠实要 NLI/LLM 判定，而这个项目刻意把质量判断做成纯确定性规则
（`report.py` 的设计约束就是"纯规则、不依赖 LLM"）。务实路线是**先堵幻觉里
最高频的那一半——编造的数字**：结论说"成本高 40%"而它的 claim 只讲召回率，
那个 40% 就是无中生有的。

## 定位：提示，不是门

误报压不到零（结论里的数字可能来自 Lead 读过的原文、只是没写进 claim）。
所以它**不进校验门**，是交付前自查工具。判断权在人/Lead，工具只负责指出
"这几个数字在你引用的 claim 里找不到，去核一下"。

用法：
    python claim_support.py --report report.md --ledger .research/<session>/ledger
退出码 0 = 全部数字都有据；1 = 有数字找不到支撑（需人工核）；2 = 参数/IO 错
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# 数字：带单位/百分比/四位年份。刻意不抓裸小整数——"两个来源""三条规则"里的
# 2 和 3 在正常文本里满地都是，抓了必误报。（同样：数字与单位之间用 `[ \t]*`，
# `\s*` 会跨行，把下一段的数字吸进来。）
NUM_RE = re.compile(
    r'\d+(?:\.\d+)?[ \t]*(?:%|％|倍|万|亿|毫秒|秒|分钟|小时|天|周|个月|年|次|'
    r'kb|mb|gb|tb|ms|x)'
    r'|\b(?:19|20)\d{2}[ \t]*年\b'
    r'|≥[ \t]*\d+(?:\.\d+)?[ \t]*(?:%|ms|s|倍|G|GB|M|MB)'
)

# 作者手写段：骨架渲染的 claim 行由 cited_claim_ids 管，这里只看人写的判断
HANDWRITTEN_HEADS = ('一页拍板', '执行摘要', '结论与建议', '结论')


def _load_ledger(ledger_dir: str) -> Tuple[Dict[str, Dict], Dict[str, List[str]]]:
    """返回 (claims_by_id, url -> [claim_id])。"""
    path = Path(ledger_dir) / 'ledger.jsonl'
    if not path.exists():
        raise FileNotFoundError(f'账本不存在: {path}')
    claims: Dict[str, Dict] = {}
    url_to_claims: Dict[str, List[str]] = {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get('type') == 'claim':
            cid = str(obj.get('id', ''))
            if cid:
                claims[cid] = obj
        elif obj.get('type') == 'source':
            url = str(obj.get('url', '')).rstrip('.,')
            cid = obj.get('claim_id')
            if url and cid:
                url_to_claims.setdefault(url, []).append(str(cid))
    if not claims:
        raise ValueError('账本里没有任何 claim')
    return claims, url_to_claims


def _registry_map(md: str, url_to_claims: Dict[str, List[str]]) -> Dict[str, str]:
    """报告的来源登记表：[N] → claim_id。

    编号是报告内部的重排序，与账本 id 不是一回事，所以要经 URL 过一次。
    """
    idx = max(md.find('## 来源'), md.find('## 参考资料'))
    tail = md[idx:] if idx >= 0 else ''
    out: Dict[str, str] = {}
    for m in re.finditer(r'\[(\d+)\][^\n\[]*?(https?://[^\s|)\]]+)', tail):
        num, url = m.group(1), m.group(2).rstrip('.,')
        ids = url_to_claims.get(url)
        if ids:
            out.setdefault(num, ids[0])
    return out


def _handwritten_sections(md: str) -> List[Tuple[str, str]]:
    """取作者手写段。

    两个踩过的坑，都写在这里免得再犯：
    1. **不能用 f-string 写含 `{1,3}` 的正则**——花括号会被当成替换字段，
       `rf'#{1,3}'` 实际变成 `#(1, 3)`，正则静默失配（表现为"一段都抓不到"）。
    2. 标题与换行之间只能用 `[ \\t]*`，**不能用 `\\s*`**——`\\s` 含换行，
       贪婪匹配会把标题后的换行吃掉再要求第二个换行。
    """
    out: List[Tuple[str, str]] = []
    for head in HANDWRITTEN_HEADS:
        pat = (r'(?:^|\n)#{1,3}[ \t]*' + re.escape(head) +
               r'[ \t]*\n(.*?)(?=\n#{1,3}[ \t]*\S|\Z)')
        m = re.search(pat, md, re.S)
        if m:
            out.append((head, m.group(1)))
    return out


def _numbers(text: str) -> List[str]:
    return [m.group(0).strip() for m in NUM_RE.finditer(text)]


def _core_digits(num: str) -> str:
    return re.sub(r'[^\d.]', '', num).rstrip('.')


def check(md: str, claims: Dict[str, Dict],
          reg: Dict[str, str]) -> Tuple[int, List[Dict[str, Any]]]:
    """返回 (检查过的数字数, 无支撑清单)。"""
    checked = 0
    unsup: List[Dict[str, Any]] = []
    for head, body in _handwritten_sections(md):
        for lineno, line in enumerate(body.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('|') or '【待写】' in stripped:
                continue
            nums = _numbers(stripped)
            if not nums:
                continue
            cited = re.findall(r'\[(\d+)\]', stripped)
            if not cited:
                continue          # 没引用不是本工具的职责（校验门那条已经拦）
            pool_parts = []
            for n in cited:
                cid = reg.get(n)
                if cid and cid in claims:
                    pool_parts.append(str(claims[cid].get('text', '')))
            pool = ' '.join(pool_parts)
            pool_flat = pool.replace(',', '').replace('，', '')
            for num in nums:
                checked += 1
                core = _core_digits(num)
                if not core:
                    continue
                if core not in pool_flat:
                    unsup.append({
                        'section': head,
                        'number': num,
                        'citations': cited,
                        'line': stripped[:90],
                        'claim_texts': [str(claims[reg[n]].get('text', ''))[:60]
                                        for n in cited if n in reg],
                    })
    return checked, unsup


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='作者手写段的数字是否有账本支撑（自查工具，非门禁）')
    ap.add_argument('--report', required=True)
    ap.add_argument('--ledger', required=True)
    args = ap.parse_args(argv)

    rp = Path(args.report)
    if not rp.exists():
        print(f'报告不存在: {rp}', file=sys.stderr)
        return 2
    try:
        claims, url_to_claims = _load_ledger(args.ledger)
    except Exception as e:
        print(f'账本读取失败: {e}', file=sys.stderr)
        return 2

    md = rp.read_text(encoding='utf-8', errors='ignore')
    reg = _registry_map(md, url_to_claims)
    checked, unsup = check(md, claims, reg)

    if not checked:
        print(f'ℹ️ 作者手写段里没有"带引用 + 带数字"的句子——本工具无事可查。'
              f'（没挂引用的句子由 validate_report 的结论引用检查负责）')
        return 0
    if not unsup:
        print(f'✅ {checked} 个数字都能在它引用的 claim 里找到')
        return 0
    print(f'⚠️ {len(unsup)}/{checked} 个数字在它引用的 claim 里找不到：\n')
    for u in unsup:
        print(f'  · [{u["section"]}] {u["number"]!r}  (引 {u["citations"]})')
        print(f'    报告：{u["line"]}')
        for t in u['claim_texts']:
            print(f'    claim：{t}')
    print('\n这些数字可能来自你读过的原文（只是没写进 claim），也可能就是编的——'
          '逐个核一下，别默认它成立。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
