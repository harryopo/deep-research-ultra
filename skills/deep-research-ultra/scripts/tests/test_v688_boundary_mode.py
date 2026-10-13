"""`--boundaries` 模式的性质测试。

## 为什么要有这个模式

`--systematic` 回答「这套测试整体有多可靠」（约 30%，且带分母 85）。
但那是个**百分比**，回答不了「我该去补哪几个」。

`--boundaries` 把变异限制在边界上，于是：

    没被钉住的边界数 ≈ 分母 × (1 − 边界检测率)

这是从百分比到**带编号的待办清单**的一步。

## 几条必须钉住的性质

- **分母不许因为"生成不出变异"而缩水**：跳过的边界要报出来。
  否则 85 悄悄变成 80，而报告里还是写着"85 个里漏了 N 个"。
- **变异必须真的落在边界那一行**，不是"文件里有个变异"。
- **折算要说清是折算**，别把估算写成实测。
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import probe_mutation as pm  # noqa: E402


def _fn(name):
    """取函数源码。

    用 `textwrap.dedent` 而不是 `cleandoc`：函数体相对 def 仍是缩进的，
    cleandoc 只去掉公共前导空白，直接 parse 会 IndentationError。
    """
    import textwrap

    src = inspect.getsource(getattr(pm, name))
    return textwrap.dedent(inspect.cleandoc(src))


def test_boundary_run_never_silently_drops_undetectable_boundaries():
    """生成不出变异的边界**必须报出来**，否则分母悄悄缩水。

    实测 85 个边界里有 5 个生成不出变异（该行没有可翻转的算子/常量）。
    吞掉它们的话，报告写着「85 个里漏了 20 个」，而真实的分母是 80 ——
    比值直接错了，而错的方向是让自己显得比实际好。
    """
    src = _fn("boundary_run")
    assert "无法生成变异" in src, "跳过的边界必须有专门的一行输出"
    assert "no_mutant" in src, "落盘结果里要记 no_mutant 的数量"
    assert "uncovered_ids" in src or "matched_ids" in src, \
        "要能算出「哪些边界没被任何变异命中」"


def test_boundary_run_reports_both_denominator_and_numerator():
    """折算必须把分母、分子、探测数三个数都写出来。"""
    src = _fn("boundary_run")
    for key in ("inventory_total", "probed", "caught", "unpinned"):
        assert key in src, f'落盘结果缺 {key} —— 分母/分子说不清'
    assert "折算" in src, "要明确标注哪一行是折算而不是实测"
    assert "边界检测率" in src, "要给出边界检测率"


def test_boundary_mutants_are_anchored_to_the_inventory_line():
    """每个变异都必须命中清单里的 (文件, 行号)，不能只说"同文件"。

    边界清单的价值全在定位。变异如果只是"这个文件里的"，那折算出来的
    「未钉住边界数」就无从查证。
    """
    src = _fn("boundary_run")
    assert "byline" in src and "byline.get((f, m.line)" in src, \
        "必须按 (文件, 行号) 把变异对齐到边界条目"
    assert "bid" in src, "每条结果要带边界 ID（file:line:kind）"


def test_boundary_kinds_map_only_to_permitted_operators():
    """每类边界只允许对应的算子，别把 `guard` 也用数值变异去撞。

    `guard` 的语义是"空输入"，用 `const +1` 去撞它测不到该测的东西。
    """
    import analysis.boundaries as BD

    src = _fn("boundary_run")
    assert "KIND_OK" in src, "边界类型 → 算子的映射必须是显式表"
    # 映射里出现过的类型必须都是清单认的类型
    for k in ("incl", "zero", "len", "thresh", "guard"):
        assert k in src, f'清单里的 {k} 类没有对应的算子映射'


def test_every_boundary_kind_has_at_least_one_mutable_instance():
    """五类边界都要有变异可生成 —— 否则有一类白测了。

    实测：`incl` 2 个、`guard` 2 个、`thresh` 1 个生成不出变异。
    若某类**全部**生成不出，说明 `KIND_OK` 的映射写错了。
    """
    import mutate_gen as mg
    import analysis.boundaries as BD

    byline = {}
    inv = []
    for f in BD.MODULES:
        p = S / f
        if not p.exists():
            continue
        rows = BD.extract(p)
        inv.extend(rows)
        for b in rows:
            byline.setdefault((f, b.line), []).append(b.kind)
    KIND_OK = {"incl": ("compare",), "zero": ("compare",),
               "len": ("compare", "const"), "thresh": ("const",),
               "guard": ("not",)}
    hitkinds = set()
    matched = set()
    for f in BD.MODULES:
        p = S / f
        if not p.exists():
            continue
        ms, _ = mg.generate(p, cap=10 ** 6)
        for m in ms:
            for kind in byline.get((f, m.line), ()):
                if m.kind in KIND_OK.get(kind, ()):
                    hitkinds.add(kind)
                    matched.add(f"{f}:{m.line}:{kind}")
                    break
    for k in ("incl", "guard", "len", "thresh", "zero"):
        assert k in hitkinds, f'{k} 类边界一个变异都生成不出来 —— 映射写错了'
    assert len(matched) >= 70, \
        f"只有 {len(matched)}/{len(inv)} 个边界能被变异命中，探测面太小"


def test_cli_exposes_the_boundaries_mode():
    """CLI 必须真的暴露这个模式，否则又是一条没人走的路。"""
    import subprocess

    r = subprocess.run([sys.executable, "-m", "probe_mutation", "--help"],
                       cwd=str(S), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0
    for flag in ("--boundaries", "--systematic", "--report", "--check"):
        assert flag in out, f"用法里缺 {flag}"