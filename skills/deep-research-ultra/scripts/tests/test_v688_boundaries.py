"""边界清单提取器的自检。

## 为什么分母要钉住

变异测试只给**分子**（哪些改动没被抓住）。它回答不了
「这套测试到底覆盖了几个边界、漏了多少」。

而 v6.79~v6.88 这几轮踩的坑 —— 陈旧 `.pyc`、缓存分支提前 return、
封顶被 Tier 抬上去、`total=101`、单字引号、`read_text` 换行转换 ——
**全部落在边界与异常路径上**，没有一次是典型输入。

有了分母，「补测试」才从一个开放任务变成**有终点的清单**。

## 钉性质，不钉数字

具体数量会随代码变动，钉死它只会让任何一行改动都要改测试。
这里钉的是**提取器必须满足的性质**：可定位、有上下文、ID 唯一、行号不越界。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import analysis.boundaries as BD  # noqa: E402


def test_check_passes_on_the_current_code():
    """提取器在当前代码上必须自洽。"""
    assert BD.check() == 0, "边界提取器自检没过 —— 分母不可信，别拿它下结论"


def test_every_boundary_is_locatable_with_context():
    """每条边界都要能定位到行、带上源码上下文 —— 否则清单没法用。"""
    rows = []
    for f in BD.MODULES:
        p = S / f
        if p.exists():
            rows.extend(BD.extract(p))
    assert len(rows) > 40, f"只提取到 {len(rows)} 个边界，明显偏少"

    ids = set()
    for b in rows:
        assert b.bid not in ids, f"ID 重复：{b.bid}"
        ids.add(b.bid)
        assert b.code and b.code.strip(), f"没有源码上下文：{b.bid}"
        assert b.func, f"没有函数名：{b.bid}"
        n = len((S / b.file).read_bytes().decode("utf-8").splitlines())
        assert 1 <= b.line <= n, f"行号越界（{b.file} 共 {n} 行）：{b.bid}"


def test_extraction_is_deterministic():
    """同一次提取两次结果必须完全一样 —— 分母飘了就没法比较。"""
    for f in ("score.py", "verify_quotes.py"):
        p = S / f
        if not p.exists():
            continue
        a = [b.bid for b in BD.extract(p)]
        b = [b.bid for b in BD.extract(p)]
        assert a == b, f"{f} 两次提取结果不同 —— 分母不稳定"


def test_the_five_boundary_kinds_are_all_present():
    """五类都要有。缺 `incl` 或 `guard` 就说明提取条件退化了。

    `incl`（`<=` / `>=`）与 `guard`（形参空输入）是最容易漏的两类 ——
    前者是经典差一，后者是退化输入。
    """
    kinds = set()
    for f in BD.MODULES:
        p = S / f
        if p.exists():
            kinds |= {b.kind for b in BD.extract(p)}
    for k in ("incl", "guard", "len", "thresh", "zero"):
        assert k in kinds, f"清单里没有 {k} 类 —— 提取条件退化了（实得 {kinds}）"


def test_inclusive_comparisons_are_actually_found():
    """直接确认 `<=` / `>=` 真的被提取到了，而不是"看起来有"。

    做法：造一个已知含 `<=` 的小文件，提取它，数 `<=` 的出现次数。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "probe.py"
        p.write_bytes(b"def f(n):\r\n    if n <= 0:\r\n        return 1\r\n"
                      b"    if n >= 10:\r\n        return 2\r\n"
                      b"    return 0\r\n")
        incl = [b for b in BD.extract(p) if b.kind == "incl"]
        assert len(incl) == 2, f'期望 2 个 incl（<= 与 >=），实得 {len(incl)}'


def test_parameter_guards_are_found_but_module_constants_are_not():
    """只认**形参**守卫，不把模块常量挡路的 if 也算成边界。

    `if not MIN_SCORE:` 是配置保护，不是"调用方可能传空"的边界，
    混进来会稀释清单。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "g.py"
        p.write_bytes(b"MIN = 3\r\n"
                      b"def f(q, r):\r\n"
                      b"    if not q:\r\n"
                      b"        return None\r\n"
                      b"    if not MIN:\r\n"
                      b"        return None\r\n"
                      b"    return r\r\n")
        g = [b for b in BD.extract(p) if b.kind == "guard"]
        assert len(g) == 1, f"只应提取到形参 `q` 那一个守卫，实得 {len(g)}"
        assert "not q" in g[0].code, f"提错了那个：{g[0].code}"


def test_survivor_alignment_is_by_file_and_line_only():
    """对齐只用 (文件, 行号) —— 必须是机械的，不含任何判断。

    一旦掺入"这个边界重不重要"之类的人判断，这份清单就退化成
    又一次手工挑选，而 v6.87 的 75% 就是手工挑选的下场。
    """
    src = (S / "analysis" / "boundaries.py").read_bytes().decode("utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "load_survivors")
    body = ast.unparse(fn)
    assert "line" in body and "file" in body, "对齐必须用到文件与行号"
    for word in ("重要", "关键", "优先", "risk", "weight"):
        assert word not in body, f"对齐逻辑里出现了「{word}」——掺了人判断"