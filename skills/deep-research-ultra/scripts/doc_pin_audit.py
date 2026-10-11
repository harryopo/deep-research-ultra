r"""doc_pin_audit.py — 量一量"测试数"里有多少是文档钉子。

## 为什么要有这个

体检 P2-13 记了一条：99 个内核测试文件里有 31 个引用 SKILL.md/README/index.html，
共 81 处断言——**"全绿"里有一部分只是"文案没被改"**。这是实测量，不是推测。

但那条数字是**某一天**的。代码一变它就过期，而"测试数"是写死在宣传页上的。
所以它不该是一次性统计，而该是一个**可重跑的测量 + 持续监测**：
宣传页上那几个数字，必须能由这个脚本在磁盘上重算出来。

> **v6.69 更正**：体检里"31/99 是文档钉子"这个说法**误导**——那 31 个是"引用了文档的
> 文件数"，其中绝大多数同时在测代码行为。本脚本第一版按"有没有文档断言"判 mixed，
> 结果给出 0% 纯钉子；改成按**断言占比**判定后才接近真相。两个口径差得很远，
> 所以下面的 `doc_ratio` 是这个工具唯一该被引用的数字。

## 怎么判定（按断言占比，不按有没有）

一个测试文件按**文档断言占全部断言的比例**分三类：

- `doc_pin`：占比 >= 0.7 —— 主体就是在查文档里有没有某句话
- `mixed`  ：0.3 <= 占比 < 0.7
- `behavior`：占比 < 0.3 —— 顺手查了文档，主体在测代码行为

**为什么必须用比例**：第一版按"有没有"判，导致两种误判同时发生——
"100 个文档断言 + 1 次函数调用"被归进 mixed（实质是钉子），
"10 个文档断言 + 200 个行为断言"也被归进 mixed（实质是功能测试）。两边都判错。

判定用 AST：`ast.dump` 看断言的 subject，字符串常量单独取出匹配，
避免"文件名恰好出现在某个无关字符串里"造成的误计。

## 用法

    python doc_pin_audit.py                 # 打印分类明细
    python doc_pin_audit.py --json          # 机器可读
    python doc_pin_audit.py --show-mixed    # 连 mixed 的占比一起打出来复核
退出码 0 恒成立（这是测量工具不是门）；目录里没有 test_*.py 时退出 2。
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Set

# 断言 subject 命中这些，就是在检查文档文本
DOC_SUBJECT_HINTS = (
    'SKILL_MD', 'SKILL.md', 'README', 'index.html', '_md', 'skill_text',
    'docs/', 'references/', '.ai/HANDOFF', 'CHANGELOG',
)
# 引用了这些路径变量的断言同样算文档断言
DOC_PATH_ATTRS = ('skill_md', 'skill', 'readme', 'html', 'md_path', 'docs')


def _loads_string(node: ast.AST) -> Set[str]:
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def classify(path: Path) -> Dict[str, object]:
    """判定单个测试文件属于哪一类，并给出依据。"""
    try:
        src = path.read_text(encoding='utf-8', errors='replace')
        # 有些测试文件的 docstring 里有非法转义序列（如 `\s`），ast.parse 会发
        # SyntaxWarning。那是**被审计文件**的问题，不是本工具的——直接打印出来会让人
        # 以为审计脚本自己坏了，所以在这里静音；文件仍会正常解析。
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', SyntaxWarning)
            tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError) as e:
        return {'kind': 'unparsed', 'reason': str(e), 'doc_hits': 0,
                'doc_ratio': 0.0, 'behavior_calls': 0, 'asserts': 0}

    imported: Set[str] = set()
    called_others = 0
    doc_hits = 0
    n_asserts = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add((a.asname or a.name).split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != '*':
                    imported.add(a.asname or a.name)
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else \
                (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name and name not in ('self',) and not name.startswith('_'):
                called_others += 1
        elif isinstance(node, ast.Assert):
            n_asserts += 1
            seg = ast.dump(node.test)
            txt = ' '.join(_loads_string(node.test))
            if any(h in seg or h in txt for h in DOC_SUBJECT_HINTS):
                doc_hits += 1
            elif any(h in seg.lower() for h in DOC_PATH_ATTRS):
                doc_hits += 1

    if n_asserts == 0:
        kind = 'no_asserts'
        ratio = 0.0
    else:
        ratio = round(doc_hits / n_asserts, 3)
        if ratio >= 0.7:
            kind = 'doc_pin'
        elif ratio >= 0.3:
            kind = 'mixed'
        else:
            kind = 'behavior'
    return {'kind': kind, 'doc_hits': doc_hits, 'doc_ratio': ratio,
            'behavior_calls': called_others, 'asserts': n_asserts,
            'imports': sorted(imported)[:8]}


def scan(test_dir: Path) -> Dict[str, object]:
    files = sorted(test_dir.glob('test_*.py'))
    rows = []
    for f in files:
        info = classify(f)
        info['file'] = f.name
        rows.append(info)
    by_kind: Dict[str, int] = {}
    for r in rows:
        by_kind[r['kind']] = by_kind.get(r['kind'], 0) + 1
    total = len(rows)
    all_asserts = sum(int(r.get('asserts', 0)) for r in rows)
    doc_asserts = sum(int(r.get('doc_hits', 0)) for r in rows)
    return {
        'total': total,
        'by_kind': by_kind,
        'rows': rows,
        # 按文件数：纯钉子文件占全部测试文件
        'doc_pin_share': round(
            (by_kind.get('doc_pin', 0) / total), 3) if total else 0.0,
        # 按断言数：文档断言占全部断言——"这个数字有多少含金量"更该看这个
        'asserts_total': all_asserts,
        'asserts_doc': doc_asserts,
        'doc_assert_share': round(
            doc_asserts / all_asserts, 3) if all_asserts else 0.0,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='统计测试里文档钉子与功能测试的占比')
    ap.add_argument('--test-dir', default=None)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--show-mixed', action='store_true',
                    help='连 mixed 文件的占比一起打出来复核')
    args = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    tdir = Path(args.test_dir) if args.test_dir else here / 'tests'
    if not tdir.is_dir():
        print(f'测试目录不存在: {tdir}', file=sys.stderr)
        return 2

    data = scan(tdir)
    if data['total'] == 0:
        print(f'{tdir} 里没有 test_*.py——路径不对或口径坏了', file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f'测试文件 {data["total"]} 个（{tdir}）')
    for k, n in sorted(data['by_kind'].items(), key=lambda x: -x[1]):
        print(f'  {k:<12} {n:>4}')
    print(f'\n纯文档钉子文件占比：{data["doc_pin_share"]:.0%}'
          f'（按文件数；>=0.7 的断言占比才算纯钉子）')
    print(f'文档断言占比    ：{data["doc_assert_share"]:.0%}'
          f'（{data["asserts_doc"]}/{data["asserts_total"]} 条断言——'
          f'"全绿里有多少只是文案没被改"，更该看这个数）')
    pins = [r for r in data['rows'] if r['kind'] == 'doc_pin']
    if pins:
        print('\n纯文档钉子文件（主体在查文档里有没有某句话）：')
        for r in sorted(pins, key=lambda x: -x['doc_ratio']):
            print(f'  {r["file"]:<44} {r["doc_ratio"]:>5.0%}'
                  f'  ({r["doc_hits"]}/{r["asserts"]})')
    if args.show_mixed:
        mixed = [r for r in data['rows'] if r['kind'] == 'mixed']
        if mixed:
            print('\nmixed 文件（两类断言都有，占比 0.3~0.7）：')
            for r in sorted(mixed, key=lambda x: -x['doc_ratio']):
                print(f'  {r["file"]:<44} {r["doc_ratio"]:>5.0%}'
                      f'  ({r["doc_hits"]}/{r["asserts"]})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
