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


# ---------------------------------------------------------------------------
# v6.73 定性高危形态（纯规则，不接 NLI/LLM）
# ---------------------------------------------------------------------------
# 每组是一个「正 → 负」词对。判定只看**是否同属一组**，不看主语——
# 实测「该方法优于基线」→「其部署成本高于基线」正是不该报的那一类：
# 优于 与 高于 不同组，所以放过。反过来，同组即判反转。

POLAR_GROUPS = (
    (('高于', '大于', '超过', '优于', '强于', '快于', '好于', '领先', '胜于'),
     ('低于', '小于', '不足', '劣于', '弱于', '慢于', '差于', '落后', '逊于')),
    (('增加', '上升', '提高', '提升', '增长', '扩大'),
     ('减少', '下降', '降低', '下滑', '回落', '收缩')),
    (('可行', '有效', '可用', '成立'), ('不可行', '无效', '不可用', '不成立')),
    (('支持', '印证', '证实'), ('反对', '反驳', '证伪', '未能证实')),
    # 极限形容词。刻意**不收**「最高/最低/最多/最少」——子串匹配会撞上
    # 「最低延迟」「最高收益」这类正常说法（延迟最低≠极性反转），
    # 宁可漏也不误报：这是提示不是门，误报会让人先怀疑工具。
    (('最好', '最佳', '最优', '最强'), ('最差', '最劣', '最弱')),
)

# 全称量词：报告里有、claim 里没有，就是把局部说成了全体
UNIVERSAL = ('所有', '全部', '总是', '任何', '每一个', '无一例外',
             '永远', '必然', '一律', '普遍', '都优于', '都强于')

# 限定词分两类，**两侧作用不同**，第一版把它们混在一起所以漏报了：
#
# RESTRICTIVE（真限定）：它把断言缩小了。出现在**报告**里就是"自己又打了折扣"，
#   那就不是全称断言，不该报警（"在所有场景中，该方法**部分**优于基线"）。
# CONTEXT（上下文）：只是给全称后面补了个名词，本身不缩小范围。
#   「所有**场景下**都优于基线」里的"场景下"是"所有"的补语，不是限定——
#   第一版把它当限定词，于是闸 3 把**真正**的范围扩大自己消掉了（实测漏报）。
RESTRICTIVE = ('部分', '某些', '特定', '仅在', '只在', '在此条件下', '之一', '未必')
CONTEXT = ('场景下', '情况下', '条件下', '范围内', '条件下')


def _polar_hits(text: str):
    """文本里出现的极性词，标成 [(组号, 方向, 词)]，方向 0=正 1=负。"""
    out = []
    for gi, (pos, neg) in enumerate(POLAR_GROUPS):
        for w in pos:
            if w in text:
                out.append((gi, 0, w))
        for w in neg:
            if w in text:
                out.append((gi, 1, w))
    return out


def _has_universal(text: str):
    return [u for u in UNIVERSAL if u in text]


def _has_qualifier(text: str):
    """真限定词。报告侧只看这个——上下文词不缩小范围，不该触发豁免。"""
    return [q for q in RESTRICTIVE if q in text]


def _has_context(text: str):
    return [q for q in CONTEXT if q in text]


# 闸 4 用的否定标记（v6.79）。覆盖"没有任何证据/未证实/查不到/并非/不能证明"这类
# **诚实标注**的常见句式——它们天然带全称词（任何/都/所有），但语义是收窄不是扩大。
#
# 刻意不收单字「不」：它太泛，"这个方法不如基线"里的「不」不是否定语境，
# 放进来会连带吃掉真阳性（极性反转/范围扩大都可能被误放过）。宁可漏放，
# 不可放过——这跟"误报比漏报贵"是同一条权衡。
_NEGATION = (
    '没有', '无', '未', '并非', '否', '查不到', '无法', '未能', '不能', '不得',
    '尚无', '暂无', '缺乏', '找不到', '零', '不成立', '不构成',
)


def _has_negation(text: str):
    return [n for n in _NEGATION if n in text]


def qualitative_risks(sentence: str, claim_pool: str) -> List[Dict[str, Any]]:
    """报告句相对它引用的 claim 池，有哪些定性高危形态。

    返回空列表表示没查出问题。**误报比漏报贵**——这是提示不是门，
    报错了 Lead 会先怀疑工具而不是先怀疑报告。
    """
    risks = []
    sent_polar = _polar_hits(sentence)
    pool_polar = _polar_hits(claim_pool)

    # 闸 2：claim 池正反两向都有 → claim 本身在讲两件事，对不上号，放过
    if pool_polar:
        pool_dirs = {d for _, d, _ in pool_polar}
        if len(pool_dirs) > 1:
            sent_polar = []

    # 闸 1：报告句同一词组两个方向都出现 → 对比讨论，放过
    if sent_polar:
        by_group = {}
        for gi, d, w in sent_polar:
            by_group.setdefault(gi, set()).add(d)
        contested = {gi for gi, dirs in by_group.items() if len(dirs) > 1}
        sent_polar = [t for t in sent_polar if t[0] not in contested]

    seen = set()
    for gi, sd, sw in sent_polar:
        for pgi, pd, pw in pool_polar:
            if pgi == gi and pd != sd and (gi, sw, pw) not in seen:
                seen.add((gi, sw, pw))
                risks.append({
                    'kind': 'polarity_flip',
                    'detail': f'{sw} ←→ claim 说 {pw}',
                    'claim_word': pw,
                    'report_word': sw,
                })
                break

    # 范围扩大：报告有全称、claim 没有
    u_sent = _has_universal(sentence)
    if u_sent and not _has_universal(claim_pool):
        # claim 侧两类词都算"它划了范围"——限定词（部分/特定）与上下文词
        # （在低延迟场景下）都在缩小适用范围。
        q = _has_qualifier(claim_pool) or _has_context(claim_pool)
        risks.append({
            'kind': 'scope_widened',
            'detail': (f'报告说 {u_sent[0]!r}，但 claim 没有同样口径的全称表述'
                       + (f'；claim 反而有限定（{q[0]!r}）' if q else '')),
            'claim_word': q[0] if q else '',
            'report_word': u_sent[0],
        })

    # 闸 3：报告句自己在加**真限定**（"在所有场景中，该方法部分优于基线"）。
    # 这里只看 RESTRICTIVE，不看 CONTEXT——「所有场景下」的"场景下"是"所有"的
    # 补语，把它算限定会让闸 3 把真正的范围扩大自己消掉（第一版就是这么漏报的）。
    if u_sent and _has_qualifier(sentence):
        risks = [r for r in risks if r['kind'] != 'scope_widened']

    # 闸 4（v6.79）：否定 / 无证据语境下的全称词不是"范围扩大"。
    #
    # 实测来源：抗幻觉行为层实验（2026-10-12），报告里写"查不到…这一说法的**任何**来源"、
    # "没有任何一条提到…"——三处全被闸 3 之前的逻辑判成 scope_widened。**三处都是误报**：
    # "没有任何证据支持 X"恰恰是**收窄**主张，不是扩大。
    #
    # 为什么必须修：Lead 写"未证实""没有证据表明"是**诚实标注**的要求（铁律 8），
    # 而这类句式天然带否定词 + 全称词。工具每遇一句诚实的话就报一次假警，Lead
    # 很快就学会忽略它——那时候工具的误报就不是误报，是把唯一的语义护栏关掉了。
    # 误报比漏报贵，在这里更贵。
    if u_sent and _has_negation(sentence):
        risks = [r for r in risks if r['kind'] != 'scope_widened']
    return risks

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
            cited = re.findall(r'\[(\d+)\]', stripped)
            if not cited:
                continue          # 没引用不是本工具的职责（校验门那条已经拦）
            nums = _numbers(stripped)
            # v6.73：以前"这行没数字"就直接下一行，所以定性断言（"所有场景都优于
            # 基线"）整段无人看管。现在数字与定性两条都走，但**仍要挂引用**——
            # 没有对照对象的句子判不了忠实度。
            if not nums and not (_has_universal(stripped) or _polar_hits(stripped)):
                continue
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

            # v6.73：定性检查在数字循环之外，一个句子可能两类问题都有
            if pool:
                for r in qualitative_risks(stripped, pool):
                    unsup.append({
                        'section': head,
                        'number': f"[定性] {r['detail']}",
                        'kind': r['kind'],          # main() 靠它分流措辞
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

    if not checked and not unsup:
        print(f'ℹ️ 作者手写段里没有"带引用 + 带数字"的句子——本工具无事可查。'
              f'（没挂引用的句子由 validate_report 的结论引用检查负责）')
        return 0
    if not unsup:
        print(f'✅ {checked} 个数字都能在它引用的 claim 里找到')
        return 0
    # v6.73：数字与定性是两类问题，措辞必须分开。
    # 尤其 `if not checked` 那条旧逻辑会把**只有定性告警**的情况整个吞掉——
    # 那正是 v6.73 新加的能力最常单独出现的地方（"所有场景都优于基线"没有数字）。
    numeric = [u for u in unsup if not u.get('kind')]
    qual = [u for u in unsup if u.get('kind')]
    print(f'⚠️ 查出 {len(unsup)} 处可疑：'
          + (f'数字 {len(numeric)}/{checked}，' if checked else '')
          + f'定性 {len(qual)}\n')
    for u in unsup:
        print(f'  · [{u["section"]}] {u["number"]!r}  (引 {u["citations"]})')
        print(f'    报告：{u["line"]}')
        for t in u['claim_texts']:
            print(f'    claim：{t}')
    print('\n这些可能来自你读过的原文（只是没写进 claim），也可能就是编的——'
          '逐个核一下，别默认它成立。')
    print('定性告警覆盖的是「极性反转」与「范围扩大」两类形态（v6.73），'
          '换对象/换维度的语义偏移查不出来，那类仍要靠人读。')
    return 1


if __name__ == '__main__':
    # v6.79：Windows GBK 终端下，本脚本的定性告警文案里的 `⚠️`/`→` 会让 print 抛
    # UnicodeEncodeError——**在真正吐出告警的那一刻崩掉**。v6.73 加定性检查时引入的
    # （旧版只输出数字与纯中文，GBK 扛得住）。实测场景：端到端实跑收尾阶段跑
    # `claim_support.py`，正是它该给结论的时候崩，等于把它的存在意义抵消了。
    # validate_report.py 早就有 force_utf8，这里对齐——文档已写明"脚本自身强制
    # UTF-8 输出，无需设置 PYTHONIOENCODING"，claim_support 当时漏了。
    try:
        from console import force_utf8
        force_utf8()
    except Exception:
        pass
    sys.exit(main())
