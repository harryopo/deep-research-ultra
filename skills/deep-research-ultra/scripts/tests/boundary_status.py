"""85 个边界的最终折算：每个边界此刻是什么状态。

## 为什么要有这张表

`--boundaries` 报的是一个**百分比**，而百分比不能当待办清单用。
真正有用的是逐条状态：

| 状态 | 含义 |
|---|---|
| `pinned` | 边界被钉死了（实跑 caught，且/或我新加的钉死测试） |
| `caught-by-existing` | 实跑就 caught —— 已有测试本来就钉住了它 |
| `equivalent` | 改动**行为不变**，没有测试能钉也**不该**有 |
| `unpinned` | 改了没被发现 —— **这是唯一真正的待办** |

分母必须写清：85 个边界里，**只有最后一类需要做**。
把等价变异算进「缺口」会让数字虚高，而虚高的方向是让自己显得更好。

## 用法

    python tests/boundary_status.py <跑出来的输出文件>
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analysis.boundaries as BD  # noqa: E402
import probe_mutation as pm  # noqa: E402
import verify_boundary_pins as vbp  # noqa: E402

# `file.py:line:kind` 之间没有空格，所以它是一个整体 token，
# 按 ":" 拆而不是靠正则分组（我第一版在这里写错了）。
LINE_RE = re.compile(r"\[\s*\d+/\d+\]\s+(\S+)\s+(\S+)\s+([\d.]+)s")


def parse_run(path: Path) -> dict:
    """输出文件 -> {('file.py', line, kind): verdict}"""
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        tok = m.group(2)
        if tok.count(":") != 2:
            continue
        f, ln, kind = tok.split(":")
        try:
            out[(f, int(ln), kind)] = m.group(1)
        except ValueError:
            continue
    return out


def build(run_path: Path) -> dict:
    inventory = []
    for f in BD.MODULES:
        p = pm.S / f
        if p.exists():
            inventory.extend(BD.extract(p))
    run = parse_run(run_path)

    claimed = {(e[0], e[1]) for e in vbp.CLAIMED}
    equivalent = {(e[0], e[1]) for e in vbp.EQUIVALENT}

    rows = []
    for b in inventory:
        key = (b.file, b.line)
        verdicts = [v for (f, ln, k), v in run.items() if (f, ln) == key]
        caught = [v for v in verdicts if v.startswith("caught")]
        survived = [v for v in verdicts if v == "SURVIVED"]

        if key in equivalent:
            status = "equivalent"
        elif survived:
            status = "unpinned"
        elif key in claimed:
            status = "pinned"
        elif caught:
            status = "caught-by-existing"
        else:
            status = "not-probed"      # 实跑没覆盖到（分母里但没生成变异）
        rows.append((b.file, b.line, b.kind, status, len(verdicts)))

    rows.sort(key=lambda r: (r[3] != "unpinned", r[0], r[1]))
    return {"rows": rows, "n": len(inventory)}


def report(d: dict) -> None:
    rows, n = d["rows"], d["n"]
    c = Counter(r[3] for r in rows)
    print("=" * 74)
    print("85 个边界的最终折算")
    print("=" * 74)
    print("  分母：%d 个边界（analysis/boundaries.py 机械提取）" % n)
    for k in ("pinned", "caught-by-existing", "equivalent", "unpinned", "not-probed"):
        print("    %-20s %2d" % (k, c[k]))
    todo = c["unpinned"]
    probed = n - c["not-probed"]
    if probed:
        # 分母里剔除等价变异 —— 它们没有测试能钉也不该有，算进去只会虚高
        real = probed - c["equivalent"]
        got = real - todo
        print()
        print("  实跑探到 %d/%d 个边界" % (probed, n))
        print("  剔除 %d 个等价变异后 -> 检出率 %d/%d = %.1f%%"
              % (c["equivalent"], got, real, 100.0 * got / max(real, 1)))
        print("  （含等价变异则是 %d/%d = %.1f%% —— 那个数把"
              "\u7b49\u4ef7\u53d8\u5f02\u4e5f\u7b97\u4f5c\u7f3a\u53e3\uff0c"
              "\u865a\u9ad8\u7684\u65b9\u5411\u662f\u8ba9\u81ea\u5df1\u770b\u8d77\u6765\u66f4\u597d\uff09"
              % (got + c["equivalent"], probed,
                 100.0 * (got + c["equivalent"]) / max(probed, 1)))
    print()
    print("  ⇒ **需要做的只有 %d 条**（unpinned）。" % todo)
    print("    等价变异 %d 条不是缺口：改了行为不变，没有测试能钉也不该有。"
          % c["equivalent"])
    print()
    for status in ("unpinned", "equivalent", "not-probed"):
        sel = [r for r in rows if r[3] == status]
        if not sel:
            continue
        print("── %s (%d) ──" % (status, len(sel)))
        for f, ln, kind, _, nv in sel:
            print("  %-22s L%-6d %-7s 变异 %d" % (f, ln, kind, nv))
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    report(build(Path(sys.argv[1])))
