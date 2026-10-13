"""边界清单 —— 列出核心模块里每一个判定边界，并标出哪些没被测到。

## 为什么要有"分母"

变异测试只给出**分子**：哪些改动没被抓住。它回答不了
「这套测试到底覆盖了几个边界、漏了多少」。

而 v6.79~v6.88 这几轮我踩的坑 —— 陈旧 `.pyc`、缓存分支提前 return、
封顶被 Tier 抬上去、`total=101`、单字引号、`read_text` 换行转换 ——
**全部落在边界与异常路径上**，没有一次是典型输入。

所以要一张**带分母的表**：每个边界一行，标明有没有测试钉住。
有了它，「补测试」从一个开放任务变成一个**有终点的清单**。

## 提取哪些边界

| 类型 | 形状 | 为什么会漏 |
|---|---|---|
| `incl` | `<=` / `>=` | 经典差一错误：恰好等于边界时的归属 |
| `zero` | `> 0` / `>= 0` / `< 0` / `<= 0` | 零是「不过滤」与「过滤全部」的岔口 |
| `thresh` | 条件里的裸常量（门槛分） | 门槛点本身没人钉 |
| `len` | `len(x) <= N` | 长度边界 + 空容器 |
| `guard` | `if not x:` 开头且 x 是形参 | 空输入/退化输入 |

**只提取可机械判定的**，不判断"这个边界重要不重要"——那属于人判断，
混进来就把这份清单变成又一次手工挑选。

## 「没被测到」怎么判定

不靠猜，靠变异结果：`--systematic` 跑完会留下
`.research/mutation_systematic.json`，里面的存活变异就是"改了没被发现"的点。
把边界 ID 与存活变异对齐 —— 对上的就是没被测到的。

对齐靠 `(文件, 行号)`，这是机械的，不含判断。
**注意它只覆盖被抽样到的边界**，所以报告里要同时给出
「已探测 N 个 / 总共 M 个」，别让 M 看起来像全覆盖。
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

# 核心模块。刻意收窄 —— 这几个是评分/过滤/核验的核心，边界错了直接影响产出。
MODULES = ("score.py", "verify_quotes.py", "research.py", "ledger.py",
           "tier.py", "validate_report.py")

# 不在 `main`/日志里改判定通常只是文案
SKIP_FUNCS = {"__repr__", "__str__", "main", "format_help", "print_help"}

INCL = {"LtE": "incl", "GtE": "incl"}
ZERO = {"Gt": "zero", "Lt": "zero"}
# 布尔上下文里的比较运算符（x 是值/属性名，不是字面量）
ZERO_CTX = re.compile(r"^\s*0\b")
LEN_CALL = re.compile(r"^\s*len\(")


class B:
    __slots__ = ("file", "line", "kind", "code", "func")

    def __init__(self, file, line, kind, code, func):
        self.file, self.line, self.kind = file, line, kind
        self.code, self.func = code, func

    @property
    def bid(self):
        return f"{self.file}:{self.line}:{self.kind}"

    def as_dict(self):
        return {"id": self.bid, "file": self.file, "line": self.line,
                "kind": self.kind, "code": self.code, "func": self.func}


def _lines(data: bytes):
    return data.decode("utf-8").splitlines()


def _ctx(line_text):
    return " ".join(line_text.split())[:96]


def extract(path: Path):
    """提取该文件的全部边界。"""
    data = path.read_bytes()
    text = data.decode("utf-8")
    lines = _lines(data)
    tree = ast.parse(text)
    out = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if fn.name in SKIP_FUNCS:
                continue
    for node in ast.walk(tree):
        # --- 形参守卫：if not <param>: ... ---
        if isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp) \
                and isinstance(node.test.op, ast.Not) \
                and isinstance(node.test.operand, ast.Name):
            v = node.test.operand
            if any(v.id == a.arg
                   for a in ast.walk(tree)
                   if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef))
                   for a in a.args.args):
                ln = node.lineno
                out.append(B(path.name, ln, "guard",
                             _ctx(lines[ln - 1] if ln <= len(lines) else ""),
                             _func_of(tree, ln)))
            continue

        # --- 比较：<= >= > < 与 len()、零、门槛常量 ---
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            op = node.ops[0]
            name = type(op).__name__
            ln = node.lineno
            ctx = _ctx(lines[ln - 1] if ln <= len(lines) else "")
            comp = node.comparators[0]
            kind = None
            if name in INCL:
                kind = INCL[name]
            elif name in ZERO:
                # `x > 0` 里的 0 —— 零值岔口；`len(x) > 0` 归到 len
                if isinstance(comp, ast.Constant) and comp.value == 0:
                    if isinstance(node.left, ast.Call) and \
                            getattr(node.left.func, "id", "") == "len":
                        kind = "len"
                    else:
                        kind = "zero"
            if kind is None and isinstance(node.left, ast.Call) and \
                    getattr(node.left.func, "id", "") == "len":
                if name in ("LtE", "GtE", "Lt", "Gt"):
                    kind = "len"
            if kind is None and isinstance(comp, ast.Constant) and \
                    isinstance(comp.value, (int, float)) and \
                    not isinstance(comp.value, bool) and comp.value not in (0, 1):
                kind = "thresh"          # 条件里的裸门槛常量
            if kind:
                out.append(B(path.name, ln, kind, ctx, _func_of(tree, ln)))

        # --- len(x) <= N 里的 N ---
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "len":
            ln = node.lineno
            ctx = _ctx(lines[ln - 1] if ln <= len(lines) else "")
            if re.search(r"len\([^)]*\)\s*(<=|>=|<|>)\s*\d+", ctx):
                out.append(B(path.name, ln, "len", ctx, _func_of(tree, ln)))
    # 同 (file,line,kind) 只留一个
    seen, uniq = set(), []
    for b in out:
        if b.bid in seen:
            continue
        seen.add(b.bid)
        uniq.append(b)
    uniq.sort(key=lambda b: (b.line, b.kind))
    return uniq


def _func_of(tree, line):
    """粗定位：找最后一个起始行 <= line 的函数名。"""
    best = ""
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and n.lineno <= line:
            if not best or n.lineno > best[0]:
                best = (n.lineno, n.name)
    return best[1] if best else "<module>"


def load_survivors():
    """读变异结果，返回存活变异的 (file, line) 集合与总探测数。"""
    p = S / ".research" / "mutation_systematic.json"
    if not p.exists():
        return set(), 0
    d = json.loads(p.read_text(encoding="utf-8"))
    surv = {(r["file"], r["line"]) for r in d.get("results", [])
            if r.get("verdict") == "SURVIVED"}
    return surv, len(d.get("results", []))


def check():
    """`--check`：断言提取器仍能稳定产出清单。

    边界清单的价值全在**分母准确**。提取器一改（漏了 `<=`、把普通比较收进来、
    退化成只数常量），分母就变了，而"测试覆盖了几个边界"这个问题也就没有答案了。

    这里不钉死具体数字 —— 那会让任何一行代码改动都要改测试。
    钉的是**性质**：每条都必须可定位到行、有源码上下文、ID 唯一。
    """
    rows = []
    for f in MODULES:
        p = S / f
        if not p.exists():
            continue
        rows.extend(extract(p))
    if not rows:
        print("❌ 一个边界都没提取到 —— 提取器坏了，"
              "而边界清单的分母会变成 0，看着像「没有边界」")
        return 1

    bad = []
    ids = set()
    for b in rows:
        if b.bid in ids:
            bad.append(f"ID 重复：{b.bid}")
        ids.add(b.bid)
        if not b.code:
            bad.append(f"没有源码上下文：{b.bid}")
        if b.kind not in ("incl", "guard", "len", "thresh", "zero"):
            bad.append(f"未知类型 {b.kind}：{b.bid}")
        p = S / b.file
        n = len(p.read_bytes().decode("utf-8").splitlines())
        if not (1 <= b.line <= n):
            bad.append(f"行号越界（文件共 {n} 行）：{b.bid}")
    if bad:
        print("❌ 清单有问题：")
        for x in bad[:10]:
            print(f"   {x}")
        return 1

    kinds = sorted({b.kind for b in rows})
    print(f"✅ {len(rows)} 个边界，{len(kinds)} 类 {kinds}，ID 唯一、上下文齐全")
    if "incl" not in kinds or "guard" not in kinds:
        print("   ⚠️ 缺 incl 或 guard —— 那是最容易漏的两类，检查提取条件")
    return 0


def main():
    rows = []
    for f in MODULES:
        p = S / f
        if not p.exists():
            continue
        rows.extend(extract(p))

    bykind = {}
    for b in rows:
        bykind.setdefault(b.kind, []).append(b)

    surv, probed = load_survivors()

    print("=" * 78)
    print(f"边界清单：{len(rows)} 个（{len(MODULES)} 个核心模块）")
    print("=" * 78)
    print()
    for k in sorted(bykind):
        print(f"  {k:<8} {len(bykind[k]):>4}")
    print()
    if probed:
        hit = [b for b in rows if (b.file, b.line) in surv]
        print(f"  变异已探测到 {probed} 个变异点；"
              f"其中 {len(hit)} 个落在清单里的边界上")
        print(f"  → 边界清单的 {len(hit)}/{len(rows)} 被确认「改了没被发现」")
        print()
        print("  被变异确认没测到的边界：")
        for b in hit:
            print(f"    {b.file}:{b.line:<5} [{b.kind:<7}] {b.code}")
    else:
        print("  （还没有变异结果；先跑 probe_mutation.py --systematic）")
        print()
        print("  清单按类型抽样（前 6 个/类）：")
        for k in sorted(bykind):
            for b in bykind[k][:6]:
                print(f"    {b.file}:{b.line:<5} [{k:<7}] {b.code}")

    out = S / ".research" / "boundaries.json"
    out.write_text(json.dumps(
        {"total": len(rows),
         "by_kind": {k: len(v) for k, v in bykind.items()},
         "probed": probed,
         "uncovered": [{"id": b.bid, "code": b.code}
                       for b in rows if (b.file, b.line) in surv],
         "all": [b.as_dict() for b in rows]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"落盘 → {out.name}")
    return 0


def cli():
    import argparse

    ap = argparse.ArgumentParser(
        description="提取核心模块的判定边界清单（分母），并可与变异结果对齐")
    ap.add_argument("--check", action="store_true",
                    help="断言提取器仍能稳定产出清单（供测试/过程门调用）")
    a = ap.parse_args()
    return check() if a.check else main()


if __name__ == "__main__":
    sys.exit(cli())