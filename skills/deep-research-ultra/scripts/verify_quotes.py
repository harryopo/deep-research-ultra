"""verify_quotes.py — 引文逐字对账门  [v6.44 新增]

账本与报告里凡是写成『…』的片段，必须能在**抓回的原始材料**里逐字命中；命中不了就非零退出。

为什么要有它：v6.42 实跑第五轮补正文时，我自己写的 11 条"正文逐字"claim 里有 6 处对不上原文——
`Scale (0–3)` 打成 `(0-3)`、`κ = 0.91` 打成 `kappa`、目录项之间自加 ` / `，
最危险的一条是把摘要转述当成正文引文（摘要说 "74.5% view peer review as ineffective"，
正文限定的是"抓不到元数据错误"且分母 n=94）。这类错误人眼扫过去看不出来，只有拿原文比才看得见。

三条固定规则：
- 只按**逐字**判：允许折叠空白（PDF/HTML 抽出来必然带换行与多空格），**不允许**换字符形态；
- fail-closed：没有可比对的原始材料时直接报错退出，不报"通过"——"没查"不等于"查过了没问题"；
  同样地，**没有待查文本**（账本里没有 claim 且没给报告）也报错退出，不许打印"全部命中"；
- 每条 MISS 顺手给出"正文里近似的那串"（按 dash/引号归一后定位），让改的人一眼看出差在哪个字符。

引号即承诺（本 skill 的书面约定）：
- 『…』/「…」/“…” = **逐字引文**，必须命中原始材料，否则本门拦停；
- 〔…〕 = **Lead 自己的措辞**（术语、归纳、检索词），不是引文，两套引号识别都不收它。
  没有这条约定时，把转述加引号会被门一直拦、去掉引号又丢语义，只能靠"另加一句非原文"打补丁。
  实跑一轮账本 67 条 claim 里数出 8 段自造话被写成了『』。

回执说清查了多少（v6.47）：短于 `--min-len`（默认 15）的引号段**不参与判定**，但这对括号承诺的
就是逐字、与长度无关，所以它们会被数进 `unchecked` 并在回执点名——有未对账段时回执不再写
"全部逐字命中"。同一轮实跑里，门点名的是 8 段长引文，人手扫出来的却是 35 段 4–14 字的中文术语
（『支撑性』『已接地所以无造假』），后者从来没被看过一眼。

用法:
  python verify_quotes.py --ledger <ledger_dir> --raw <抓取材料目录或单文件>
                          [--claim-id id[,id...]] [--min-len 15] [--json]
  python verify_quotes.py --report <report.md> --raw <抓取材料目录>
                          # 报告正文里的引文同样要逐字——交付的是报告
  退出码：0 全部逐字命中；1 有 MISS；2 参数/IO 错误（含"没有可比对材料""没有待查文本"）
"""
import argparse
import io
import json
import os
import re
import sys

# 只用于"给建议"，不用于判定命中：判定必须逐字
_SUGGEST_TABLE = str.maketrans({
    '–': '-', '—': '-', '’': "'", '‘': "'", '“': '"', '”': '"',
    '\u00a0': ' ', '　': ' ', '，': ',', '：': ':',
})

# 与 ledger._QUOTE_PATTERNS 同一套括号：判同认为"这是逐字引文"的，对账也必须认为是——
# 两边认得不一样就会出现"一侧说没引文、另一侧说引文没命中"的死锁（v6.44 实跑撞到）。
QUOTE_PATTERNS = (
    re.compile(r'『([^』]{15,})』', re.S),
    re.compile(r'「([^」]{15,})」', re.S),
    re.compile(r'“([^”]{15,})”', re.S),
)

# 同一套括号、但先不管长度：用来数"承诺了逐字、却因为太短而没被对账"的那一段。
# 『』 这对括号的承诺与长度无关，门只看得到长段，就得把"短段没看"说出口。
_BRACKETS = (('『', '』'), ('「', '」'), ('“', '”'))


def quoted_spans(text, floor=2):
    """文本里所有引号段（折叠空白后），不参与判定，只用于统计未对账的那些。"""
    out = []
    for open_, close_ in _BRACKETS:
        pat = re.compile('%s([^%s]{%d,})%s' % (re.escape(open_), re.escape(close_),
                                               floor, re.escape(close_)), re.S)
        for m in pat.finditer(str(text or '')):
            frag = _fold(m.group(1))
            if frag and frag not in out:
                out.append(frag)
    return out


def quoted_fragments(text, min_len=15):
    return [f for f in quoted_spans(text) if len(f) >= min_len]


def _fold(text):
    return re.sub(r'\s+', ' ', text).strip()


def load_corpus(raw):
    """raw 可以是目录（递归收 *.txt/*.html/*.xml/*.md）或单个文件。返回 [(路径, 折叠后的正文)]。"""
    files = []
    if os.path.isdir(raw):
        for root, _dirs, names in os.walk(raw):
            for n in sorted(names):
                if n.lower().endswith(('.txt', '.html', '.xml', '.md')):
                    files.append(os.path.join(root, n))
    elif os.path.isfile(raw):
        files = [raw]
    corpus = []
    for path in files:
        try:
            body = _fold(io.open(path, encoding='utf-8', errors='replace').read())
        except OSError:
            continue
        if body:
            corpus.append((path, body))
    return corpus


def _suggest(fragment, corpus):
    """按字符形态归一后定位，返回正文里那一段的**原始**写法（供改错对照）。"""
    want = _fold(fragment).translate(_SUGGEST_TABLE).lower()
    head = want[:min(30, len(want))]
    for _path, body in corpus:
        norm = body.translate(_SUGGEST_TABLE).lower()
        i = norm.find(head)
        while i != -1:
            seg = body[i:i + len(fragment) + 30]
            if _fold(seg).translate(_SUGGEST_TABLE).lower().strip(' .,;')[:len(want)] == want:
                return _fold(seg)[:len(fragment) + 20]
            i = norm.find(head, i + 1)
    return ''


def iter_claim_texts(ledger_dir, claim_ids=None):
    path = os.path.join(ledger_dir, 'ledger.jsonl')
    wanted = set(claim_ids or [])
    if not os.path.exists(path):
        return
    for line in io.open(path, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get('type') != 'claim':
            continue
        if wanted and rec.get('id') not in wanted:
            continue
        yield rec.get('id') or '(无 id)', rec.get('text') or ''


def iter_report_texts(report):
    """报告正文逐行产出 (定位标签, 文本)。report 可以是路径，也可以是 (标签, 全文)。

    交付物是报告而不是账本：账本改对了、报告里还留着旧写法，是这一轮实跑数出来的
    （账本 83/83 全过，报告正文却有 45 段对不上抓取材料）。所以门必须量到真正交出去的那份文本。
    给路径才能报到行号；validate_report 手上只有正文，就按 (标签, 全文) 传进来。
    """
    if isinstance(report, tuple):
        label, text = report
        for n, line in enumerate(str(text).splitlines(), 1):
            yield '%s:%d' % (label, n), line
        return
    text = io.open(report, encoding='utf-8', errors='replace').read()
    name = os.path.basename(report)
    for n, line in enumerate(text.splitlines(), 1):
        yield '%s:%d' % (name, n), line


def collect_sources(ledger_dir=None, report=None, claim_ids=None):
    """待查文本 = 账本 claim（可选）+ 报告正文（可选）；两边都不给就没有东西可对账。"""
    out = []
    if ledger_dir:
        out += list(iter_claim_texts(ledger_dir, claim_ids))
    if report:
        out += list(iter_report_texts(report))
    return out


def check_quotes(ledger_dir, raw, claim_ids=None, min_len=15, report=None):
    corpus = load_corpus(raw)
    if not corpus:
        return {'checked': 0, 'misses': [], 'corpus_files': 0, 'sources': 0, 'unchecked': [],
                'error': '没有可比对的原始材料（%s 下没有非空的 txt/html/xml/md）——'
                         '引文对账需要抓回的正文或页面存档，缺它无法判定，不能当作通过' % raw}
    sources = collect_sources(ledger_dir, report, claim_ids)
    if not sources:
        return {'checked': 0, 'misses': [], 'corpus_files': len(corpus), 'sources': 0,
                'unchecked': [],
                'error': '没有待查文本：--ledger 指向的账本里没有 claim，也没给 --report'
                         '——"没东西可查"不等于"查过了没问题"，不能报通过'}
    checked = 0
    misses = []
    unchecked = []
    for where, text in sources:
        for frag in quoted_spans(text):
            if len(frag) < min_len and frag not in unchecked:
                unchecked.append(frag)
        for frag in quoted_fragments(text, min_len):
            frag = _fold(frag)
            if len(frag) < min_len:
                continue
            checked += 1
            if any(frag in body for _p, body in corpus):
                continue
            misses.append({'where': where, 'fragment': frag,
                           'suggest': _suggest(frag, corpus)})
    return {'checked': checked, 'misses': misses, 'corpus_files': len(corpus),
            'sources': len(sources), 'unchecked': unchecked, 'error': None}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='verify_quotes.py', description=__doc__.split('\n')[0])
    ap.add_argument('--ledger', default='', help='账本目录（里面有 ledger.jsonl）；与 --report 至少给一个')
    ap.add_argument('--report', default='', help='报告 markdown 文件——交付的是报告，正文引文同样要逐字')
    ap.add_argument('--raw', required=True, help='抓取材料目录或单文件')
    ap.add_argument('--claim-id', default='', help='只查这几条 claim（逗号分隔）')
    ap.add_argument('--min-len', type=int, default=15, help='参与对账的最短引文字数')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    args = ap.parse_args(argv)

    if not args.ledger and not args.report:
        print('既没有 --ledger 也没有 --report：没有任何待查文本，不能报通过', file=sys.stderr)
        return 2
    if args.ledger and not os.path.isdir(args.ledger):
        print('账本目录不存在：%s' % args.ledger, file=sys.stderr)
        return 2
    if args.report and not os.path.isfile(args.report):
        print('报告文件不存在：%s' % args.report, file=sys.stderr)
        return 2
    res = check_quotes(args.ledger or None, args.raw,
                       [c.strip() for c in args.claim_id.split(',') if c.strip()],
                       args.min_len, report=args.report or None)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res['error']:
            print('⛔ ' + res['error'], file=sys.stderr)
            return 2
        print('语料 %d 份，待查文本 %d 处，对账引文 %d 段'
              % (res['corpus_files'], res['sources'], res['checked']))
        for m in res['misses']:
            print('MISS [%s] 『%s』' % (m['where'], m['fragment'][:80]), file=sys.stderr)
            if m['suggest']:
                print('      正文写法 『%s』' % m['suggest'][:80], file=sys.stderr)
        if res['misses']:
            print('共 %d 处标着逐字的引文与原始材料对不上——按原文逐字改写，自造口径改用〔〕'
                  '（『「“ 是逐字标记）' % len(res['misses']), file=sys.stderr)
            return 1
        if res['unchecked']:
            print('另有未对账 %d 段：短于 %d 字的『「“段不参与逐字判定，'
                  '但这对括号承诺的就是逐字——自造口径请改写为〔〕'
                  % (len(res['unchecked']), args.min_len))
            print('      例：%s' % '、'.join('『%s』' % f[:20] for f in res['unchecked'][:6]))
            print('✅ 已对账的 %d 段逐字命中（短段未判，不算已核）' % res['checked'])
        else:
            print('✅ 全部逐字命中')
    return 1 if res['misses'] else 0


if __name__ == '__main__':
    sys.exit(main())
