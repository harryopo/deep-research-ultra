"""系统化变异生成 —— 从 AST 找位置，在源码里做**字节切片**替换。

## 为什么不做 ast.unparse 重排版

`ast.unparse` 会丢掉注释并重排行号。而本仓库有一条测试专门盯行号：
`test_line_number_points_at_the_offending_line` 断言错误信息里的 `report.md:8`。
一旦重排行号，**每个变异都会「抓到」这条测试** —— 检测率虚报到 100%，
比没有测量更坏。

所以：AST 只用来**定位**（lineno/col_offset），替换用字节偏移量做切片，
其余字节一个不动。行号因此完全保持。

## 两个必须用字节的坑（都踩过）

1. **不能用 `sum(len(l) + 1 ...)` 累加行长。** `splitlines(keepends=True)`
   对 CRLF 文件每行结尾是 **2** 个字符（`\\r\\n`），那个 `+1` 会让**每一行**
   都多算 1，错位随行号线性增长。第一版就是这么写的 ——
   48 个变异里 22 个语法错，切出来的是 `'t` 这种碎片。
2. **AST 的 `col_offset` 是 UTF-8 字节偏移，不是字符下标。** 源文件里有中文，
   按字符算会错。

所以全程 `text.encode()` + 行首字节表，不碰字符索引。

## 五种变异算子

| 算子 | 形状 | 语义 |
|---|---|---|
| 比较算子翻转 | `a < b` → `a <= b` | 边界条件 |
| 比较算子取反 | `a == b` → `a != b` | 取反 |
| 布尔算子互换 | `A and B` → `A or B` | 条件逻辑 |
| 取 `not` | `not A` → `A` | 条件逻辑 |
| 数值 +1 | `>= 50` → `>= 51` | 阈值 |

都选**纯算子/字面量级**的：能用切片精确替换，不动控制流、不动缩进。

**注意 operator 节点常常不带位置信息** —— `ast.And/Or/Not` 在不少 Python
版本里是 singleton，没有 `lineno`。所以一律走「在两段文本之间找算子 token」，
不依赖 AST 坐标（第一版直接 `node.op.lineno`，直接 AttributeError）。

## 刻意跳过的位置

`assert` 语句（改断言等于改判据，不是改行为）、文档字符串、
`__repr__`/`main`/日志这类函数（改数字通常是文案）。

## 为什么按算子平衡抽样

笼统随机抽的话，样本会被 `const` 淹没（AST 里字面量远多于算子），
测出来的其实是「const 变异的检出率」，不是总体。
所以每种算子配额相同，余量再按种子补给 —— 结果可复现，种子写在输出里。
"""
from __future__ import annotations

import argparse
import ast
import random
import re
from pathlib import Path

S = Path(__file__).resolve().parent
MODULES = ("score.py", "verify_quotes.py", "research.py", "ledger.py")

SKIP_FUNCS = {"__repr__", "__str__", "main", "help", "usage",
              "format_help", "print_help", "_log", "log"}

COMPARE_FLIP = {
    ast.Lt: "<=", ast.LtE: "<", ast.Gt: ">=", ast.GtE: ">",
    ast.Eq: "!=", ast.NotEq: "==", ast.Is: "is not", ast.IsNot: "is",
    ast.In: "not in", ast.NotIn: "in",
}
OP_RE = re.compile(r"\s*(is not|not in|is|in|==|!=|<=|>=|<|>)")


class Mutant:
    __slots__ = ("path", "kind", "start", "end", "repl", "detail", "line")

    def __init__(self, path, kind, start, end, repl, detail, line=None, data=None):
        self.path, self.kind = path, kind
        self.start, self.end, self.repl = start, end, repl
        # 行号必须按**实际改动位置**算，不能用 node.lineno：
        # 多行表达式的算子 token 可能落在节点起始行**之后**。
        # 报 `m.line` 却在第 3 行，那条记录指向的就不是改的地方。
        self.line = (data[:start].count(b"\n") + 1) if data is not None else line
        self.detail = detail

    @property
    def file(self):
        """文件名（字符串）。

        与手工那版的 `Mut.file` 同名同型。原先只有 `path`，`boundary_run` 里
        写成 `m.file.name` 就 AttributeError 崩掉 —— 命名不一致是最容易
        省掉的一类错误，所以这里给成属性而不是让人每次记清是哪个。
        """
        return self.path.name

    def label(self):
        return f"{self.path.name}:{self.line} [{self.kind}] {self.detail}"

    def apply(self, data: bytes) -> bytes:
        return data[:self.start] + self.repl.encode("utf-8") + data[self.end:]

    def old(self, data: bytes) -> str:
        return data[self.start:self.end].decode("utf-8", "replace")

    def ctx(self, text: str) -> str:
        """变异点所在那行的源码 —— 用来核对「改的到底是哪儿」。"""
        ch = len(text.encode("utf-8")[:self.start].decode("utf-8", "replace"))
        ls = text.rfind("\n", 0, ch) + 1
        le = text.find("\n", ch)
        return " ".join(text[ls:le if le > 0 else len(text)].split())[:76]


def _line_starts(data: bytes):
    """行首字节偏移表。靠它算位置，天然对 CRLF/LF 都对。

    但**输入**必须已经是磁盘上那份字节 —— `read_text()` 会把 `\r\n`
    规范成 `\n`，那张表就与磁盘错开了。详见 `generate()` 里的说明。
    """
    starts = [0]
    for m in re.finditer(b"\n", data):
        starts.append(m.end())
    return starts


def generate(path: Path, cap: int = 12, seed: int = 20261013):
    """产出至多 cap 个变异（按算子平衡 + 固定种子，可复现）。

    只返回**应用后仍能编译**的那些 —— 语法错的变异会让套件直接 ImportError，
    那样每个文件都会「被抓到」，检测率虚报到 100%。
    被丢弃的数量在返回值里说明，不静默。

    ⚠️ **必须用 `read_bytes().decode()`，不能 `read_text()`。**
    `read_text()` 默认做通用换行转换，把磁盘上的 `\r\n` 变成 `\n`；
    而 AST 的 `col_offset` 是相对**磁盘上那份文本**的字节偏移。
    两者每行差 1，偏移线性错位，最后切到**中文注释里去**
    （`切掉: '\ufffd'` —— 一个字节的中文首字节）。

    这是同一个坑的**第二层**：第一层是 `sum(len(l)+1 ...)` 的算术，
    改对之后才发现**输入**本身就被悄悄改过了。
    """
    data = path.read_bytes()
    text = data.decode("utf-8")
    starts = _line_starts(data)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], 0

    def offs(node):
        # 防御：节点位置越界时**跳过**，而不是让整个生成器崩掉。
        # 生成器一崩，实跑就退出，什么数字都拿不到 —— 而"拿不到"
        # 和"零个变异"在报告里长得一样。
        if node.lineno is None or node.lineno > len(starts):
            return None
        if (node.end_lineno is not None
                and node.end_lineno > len(starts)):
            return None
        s = starts[node.lineno - 1] + node.col_offset
        if node.end_lineno is None:
            return s, s
        return s, starts[node.end_lineno - 1] + node.end_col_offset

    skip_nodes = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and fn.name in SKIP_FUNCS:
            skip_nodes.update(id(n) for n in ast.walk(fn))

    def skipped(node):
        return id(node) in skip_nodes

    cands = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) or skipped(node):
            continue

        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            op = node.ops[0]
            if type(op) not in COMPARE_FLIP:
                continue
            o1, o2 = offs(node.left), offs(node.comparators[0])
            if o1 is None or o2 is None:
                continue
            ls, rs = o1[0], o2[1]
            m = OP_RE.search(data[ls:rs].decode("utf-8", "replace"))
            if not m:
                continue
            a, b = m.span(1)
            cands.append(Mutant(path, "compare", ls + a, ls + b,
                                COMPARE_FLIP[type(op)],
                                " ".join(data[ls:rs].decode("utf-8", "replace")
                                         .split())[:48], data=data))
            continue

        if isinstance(node, ast.BoolOp) and isinstance(node.op,
                                                      (ast.And, ast.Or)):
            o1, o2 = offs(node.values[0]), offs(node.values[1])
            if o1 is None or o2 is None:
                continue
            v0s, v1s = o1[0], o2[1]
            m = re.search(r"\b(and|or)\b",
                          data[v0s:v1s].decode("utf-8", "replace"))
            if not m:
                continue
            cands.append(Mutant(path, "boolop", v0s + m.start(1), v0s + m.end(1),
                                "or" if isinstance(node.op, ast.And) else "and",
                                " ".join(data[v0s:v1s].decode("utf-8", "replace")
                                         .split())[:48], data=data))
            continue

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            ov = offs(node.operand)
            if ov is None:
                continue
            vs = ov[0]
            head = data[max(0, vs - 24):vs].decode("utf-8", "replace")
            m = re.search(r"not\s+$", head)
            if not m:
                continue
            s = max(0, vs - 24) + m.start()
            e = max(0, vs - 24) + m.end()
            cands.append(Mutant(path, "not", s, e, "",
                                f"去掉 not（{data[s:min(len(data), vs + 20)].decode('utf-8', 'replace').strip()[:32]}）",
                                data=data))
            continue

        if isinstance(node, ast.Constant) and isinstance(node.value, int) \
                and not isinstance(node.value, bool) and 0 < abs(node.value) <= 10000:
            oe = offs(node)
            if oe is None:
                continue
            s, e = oe
            cands.append(Mutant(path, "const", s, e, str(node.value + 1),
                                f"{node.value} → {node.value + 1}", data=data))

    # 同一偏移只留一个
    seen, uniq = set(), []
    for m in cands:
        if (m.start, m.end) not in seen:
            seen.add((m.start, m.end))
            uniq.append(m)

    # **应用后必须还能编译**。语法错的变异会让套件 ImportError，
    # 那样每个文件都「被抓到」，检测率虚报到 100%。
    good, dropped = [], 0
    for m in uniq:
        try:
            compile(m.apply(data), str(path), "exec")
        except (SyntaxError, ValueError):
            dropped += 1
            continue
        good.append(m)

    rng = random.Random(seed)
    by_kind = {}
    for m in good:
        by_kind.setdefault(m.kind, []).append(m)
    if not by_kind:
        return [], dropped
    for v in by_kind.values():
        rng.shuffle(v)
    kinds = sorted(by_kind)
    per = max(1, cap // len(kinds))
    picked = []
    for k in kinds:
        picked.extend(by_kind[k][:per])
    rest = [m for k in kinds for m in by_kind[k][per:]]
    rng.shuffle(rest)
    picked.extend(rest[:max(0, cap - len(picked))])
    picked.sort(key=lambda m: (m.start,))
    return picked[:cap], dropped


def main(argv=None):
    """单独跑也能看：列出会生成哪些变异。

    为什么要真做这个 CLI：`--help` 什么都不输出、退出码还是 0，
    那正是 v6.83 的「假开关」形态——显式开了却不生效，且不吭声。
    过程门的 smoke 是按输出内容判的，这种模块会**静默地**通过。
    """
    ap = argparse.ArgumentParser(
        description="列出机械生成的变异（不改动任何文件）")
    ap.add_argument("files", nargs="*", default=list(MODULES),
                    help="要扫描的脚本名，默认四个核心模块")
    ap.add_argument("--cap", type=int, default=8, help="每个文件取几个")
    ap.add_argument("--seed", type=int, default=20261013, help="抽样种子")
    ap.add_argument("--show-context", action="store_true",
                    help="连同所在源码行一起打印")
    a = ap.parse_args(argv)

    for f in a.files:
        p = S / f if not Path(f).is_absolute() else Path(f)
        if not p.exists():
            print(f"{f}: 不存在")
            continue
        data = p.read_bytes()
        text = data.decode("utf-8")
        ms, dropped = generate(p, cap=a.cap, seed=a.seed)
        by = {}
        for m in ms:
            by[m.kind] = by.get(m.kind, 0) + 1
        print(f"\n{f} —— 取 {len(ms)} 个 {by}（丢弃语法错 {dropped}）")
        for m in ms:
            print(f"  L{m.line:<5} {m.kind:<8} 「{m.old(data)}」→「{m.repl}」")
            if a.show_context:
                print(f"        {m.ctx(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())