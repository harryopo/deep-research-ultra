"""verify_quotes.py — 引文逐字对账门  [v6.44 新增]

账本与报告里凡是写成『…』的片段，必须能在**抓回的原始材料**里逐字命中；命中不了就非零退出。

为什么要有它：v6.42 实跑第五轮补正文时，我自己写的 11 条"正文逐字"claim 里有 6 处对不上原文——
`Scale (0–3)` 打成 `(0-3)`、`κ = 0.91` 打成 `kappa`、目录项之间自加 ` / `，
最危险的一条是把摘要转述当成正文引文（摘要说 "74.5% view peer review as ineffective"，
正文限定的是"抓不到元数据错误"且分母 n=94）。这类错误人眼扫过去看不出来，只有拿原文比才看得见。

三条固定规则：
- 只按**逐字**判：允许折叠空白（PDF/HTML 抽出来必然带换行与多空格），**不允许**换字符形态；
- fail-closed：没有可比对的原始材料时直接报错退出，不报"通过"——"没查"不等于"查过了没问题"；
- 每条 MISS 顺手给出"正文里近似的那串"（按 dash/引号归一后定位），让改的人一眼看出差在哪个字符。

用法:
  python verify_quotes.py --ledger <ledger_dir> --raw <抓取材料目录或单文件>
                          [--claim-id id[,id...]] [--min-len 15] [--json]
  退出码：0 全部逐字命中；1 有 MISS；2 参数/IO 错误（含"没有可比对材料"）
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

QUOTE_RE = re.compile(r'[『「]([^』」]{15,})[』」]')


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


def check_quotes(ledger_dir, raw, claim_ids=None, min_len=15):
    corpus = load_corpus(raw)
    if not corpus:
        return {'checked': 0, 'misses': [], 'corpus_files': 0,
                'error': '没有可比对的原始材料（%s 下没有非空的 txt/html/xml/md）——'
                         '引文对账需要抓回的正文或页面存档，缺它无法判定，不能当作通过' % raw}
    checked = 0
    misses = []
    for cid, text in iter_claim_texts(ledger_dir, claim_ids):
        for frag in QUOTE_RE.findall(text):
            frag = _fold(frag)
            if len(frag) < min_len:
                continue
            checked += 1
            if any(frag in body for _p, body in corpus):
                continue
            misses.append({'claim_id': cid, 'fragment': frag,
                           'suggest': _suggest(frag, corpus)})
    return {'checked': checked, 'misses': misses, 'corpus_files': len(corpus),
            'error': None}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='verify_quotes.py', description=__doc__.split('\n')[0])
    ap.add_argument('--ledger', required=True, help='账本目录（里面有 ledger.jsonl）')
    ap.add_argument('--raw', required=True, help='抓取材料目录或单文件')
    ap.add_argument('--claim-id', default='', help='只查这几条 claim（逗号分隔）')
    ap.add_argument('--min-len', type=int, default=15, help='参与对账的最短引文字数')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    args = ap.parse_args(argv)

    if not os.path.isdir(args.ledger):
        print('账本目录不存在：%s' % args.ledger, file=sys.stderr)
        return 2
    res = check_quotes(args.ledger, args.raw,
                       [c.strip() for c in args.claim_id.split(',') if c.strip()],
                       args.min_len)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res['error']:
            print('⛔ ' + res['error'], file=sys.stderr)
            return 2
        print('语料 %d 份，对账引文 %d 段' % (res['corpus_files'], res['checked']))
        for m in res['misses']:
            print('MISS [%s] 『%s』' % (m['claim_id'], m['fragment'][:80]), file=sys.stderr)
            if m['suggest']:
                print('      正文写法 『%s』' % m['suggest'][:80], file=sys.stderr)
        if res['misses']:
            print('共 %d 处引文与原始材料对不上——按正文逐字改写，或把转述明确标成转述'
                  % len(res['misses']), file=sys.stderr)
            return 1
        print('✅ 全部逐字命中')
    return 1 if res['misses'] else 0


if __name__ == '__main__':
    sys.exit(main())
