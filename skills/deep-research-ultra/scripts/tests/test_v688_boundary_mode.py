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

# ---------------------------------------------------------------------------
# 七、属性拼错这一类：静态查，别等它崩
# ---------------------------------------------------------------------------
# `boundary_run` 里写成 `m.file.name`（Mutant 只有 `path`），
# 一跑就 AttributeError 崩掉 —— 而崩掉是好的，至少会说话。
# 真正坏的是：崩在跑了 40 分钟之后。所以这类错要在**跑之前**挡住。


def test_boundary_run_only_uses_attributes_mutant_actually_has():
    """`boundary_run` 里访问 `Mutant` 的属性必须真的存在。

    做法：AST 找出 `boundary_run` 里所有 `m.<attr>` 形式的属性访问，
    逐个对照 `Mutant` 的 `__slots__` 与属性表。
    """
    import ast
    import textwrap

    import mutate_gen as mg

    known = set(mg.Mutant.__slots__)
    # 属性（含 file 那个 property）与公开方法都要算进来
    known |= {n for n, v in vars(mg.Mutant).items()
              if isinstance(v, property) or callable(v)}
    known |= {"path", "file"}       # file 是后补的属性

    src = textwrap.dedent(inspect.getsource(pm.boundary_run))
    tree = ast.parse(src)
    used = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "m" and not n.attr.startswith("_")):
            used.add(n.attr)
    # 用到但 Mutant 没有的
    bad = used - known
    assert not bad, (
        f'boundary_run 用了 Mutant 没有的属性 {bad}；'
        f'Mutant 实际有 {sorted(known)} —— 这类错在跑了几十分钟之后才崩')


def test_mutant_exposes_file_as_a_string_like_the_handpicked_mut():
    """`Mutant.file` 要与 `Mut.file` 同名同型（都是字符串）。

    命名不一致是最容易省掉的一类错误：一边 `m.file` 一边 `m.path.name`，
    写错时只有运行才炸。所以给成属性，而不是让人每次记清是哪个。
    """
    from pathlib import Path as _P

    import mutate_gen as mg

    ms, _ = mg.generate(S / "score.py", cap=3)
    assert ms, "生成器一个变异都没产出，这条测试失去意义"
    m = ms[0]
    assert isinstance(m.file, str), f'Mutant.file 应是字符串，实得 {type(m.file)}'
    assert m.file == m.path.name, "Mutant.file 应等于路径的文件名"
    assert isinstance(pm.Mut("x.py", "a", "b", "c").file, str), \
        "手挑那版的 .file 也是字符串 —— 两版得同名同型"


# ---------------------------------------------------------------------------
# 八、⚠️ 本项目最贵的一个 bug：变异写进了真实工作区
# ---------------------------------------------------------------------------
# `boundary_run` 里 `mutate_gen.generate(p)` 原本传的是 `S / f`（真路径），
# 于是 `Mutant.path` 指向真文件，后面的 `p.write_bytes(m.apply(data))`
# 把变异直接写进真实工作区 —— **副本隔离被完全绕开**。
#
# 实测后果：一次前台实跑被我用 `Select-Object -First 30` 掐断管道，进程被杀、
# `finally` 的还原没执行，`score.py` 两行
#   `if not query:`    → `if query:`
#   `if not content:`  → `if content:`
# 留在工作区没还原。而那两处不是我提交的改动，下一次 `git status` 之前
# 我一直以为工作区是干净的 —— **更糟的是它没有让任何测试变红**，
# 因为 `if content: return 30.0` 在语法上完全合法，行为差异要靠读才知道。
#
# 三道防线一起加，少一道都可能再犯。


def test_boundary_run_generates_mutants_from_the_copy_not_the_real_tree():
    """变异对象必须来自副本路径 —— `Mutant.path` 决定了写到哪儿。"""
    src = _fn("boundary_run")
    assert "mutate_gen.generate(cp, cap=10 ** 6)" in src, \
        "必须用副本路径 cp 生成变异"
    assert "mutate_gen.generate(p, cap=0 or 10 ** 6)" not in src, \
        "generate(p, ...) 里那个 p 是 S / f（真路径）—— 变异会写进真实工作区"


def test_boundary_run_asserts_every_mutation_target_lives_under_the_copy():
    """每次写盘前都要断言目标在副本目录下。"""
    src = _fn("boundary_run")
    assert "_is_under(p, tmp)" in src, \
        "写盘前必须校验目标路径在临时副本下，别靠自觉"


def test_boundary_run_fingerprints_the_real_tree_before_and_after():
    """跑前留指纹、跑后核对 —— 证明「一个字节都没动」，而不是假定没动。

    这是唯一能在**进程被杀之外**兜住的检查：
    `finally` 挡得住异常和正常退出，挡不住 SIGKILL。
    指纹核对至少让下一次运行立刻发现上一次留下了残局。
    """
    import inspect as _i

    src = _fn("boundary_run")
    assert "_fingerprint(S)" in src, "跑之前必须给真实树留指纹"
    assert "真实工作区被改动了" in src, "指纹不一致时要报错而不是继续"
    assert _i.signature(pm._fingerprint).parameters["root"], \
        "_fingerprint 要能对任意目录取指纹"
    assert hasattr(pm, "_is_under"), "缺 _is_under"


def test_is_under_rejects_paths_outside_the_root():
    """`_is_under` 必须真的能拒 —— 用 `..` 与相似前缀两种绕过手法试。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "copy"
        root.mkdir()
        inside = root / "sub" / "a.py"
        inside.parent.mkdir()
        inside.write_text("x", encoding="utf-8")
        assert pm._is_under(inside, root), "副本内的文件应判为在下面"
        for bad in (root.parent / "real.py",
                    Path(td) / "copy_evil" / "a.py",     # 前缀相同但不在下面
                    Path(td) / "a.py"):
            assert not pm._is_under(bad, root), \
                f'{bad} 不该被判为在 {root} 下'


def test_real_tree_is_untouched_after_a_fingerprint_roundtrip():
    """指纹机制本身要能区分「变了」与「没变」。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "a.py").write_text("x = 1\n", encoding="utf-8")
        before = pm._fingerprint(d)
        assert pm._fingerprint(d) == before, "没动就该一致"
        (d / "a.py").write_text("x = 2\n", encoding="utf-8")
        after = pm._fingerprint(d)
        assert after != before, "改了一个字节就该被认出来"
        (d / "b.py").write_text("y = 1\n", encoding="utf-8")
        assert set(pm._fingerprint(d)) - set(before) == {"b.py"}, \
            "新增文件也要被认出来"
