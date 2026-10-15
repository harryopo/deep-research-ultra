"""同步测试计数钉子 —— **数字由脚本自己测，人不参与**。

## 为什么要有这个脚本

index.html / README.md / HANDOFF.md 一共 5 处钉着同一个数，而那个数
每次改测试都会变。我在 v6.91~v6.93 这几轮里**手打错了三次**：

    1282（我以为）→ 实测 1260
    1332（TOT 算成 K+SH 却写成 1282+50）→ 写进去一堆 1332
    1307（我又猜了一个）→ 实测 1309

每次都得靠 `test_landing_page_facts` / `test_v671_handoff_counts` /
`test_v682_readme_facts` 这三条测试红着才发现，而它们红的原因
只是我抄错了数字 —— **测试抓的是一个抄写错误，不是逻辑错误**。

所以：让脚本自己去 `pytest --collect-only` 数、自己去 glob 数文件、
自己算总数、自己替换。人只负责跑它。

## 用法

    python scripts/sync_test_counts.py            # 只看会改成什么，不落盘
    python scripts/sync_test_counts.py --write    # 真改

改完记得跑全量确认 5 处都对上了。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "skills" / "deep-research-ultra" / "scripts"


def _collected(path: pathlib.Path) -> int:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header",
         str(path)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900,
    )
    m = re.search(r"(\d+) tests? collected", r.stdout)
    if not m:
        raise SystemExit(f"没从 {path} 的输出里解析出收集数：\n{r.stdout[-400:]}")
    return int(m.group(1))


def measure() -> dict:
    kernel = _collected(SCRIPTS / "tests")
    shell = _collected(REPO / "tests")
    n_files = len(list((SCRIPTS / "tests").glob("test_*.py")))
    return {"kernel": kernel, "shell": shell, "files": n_files,
            "total": kernel + shell}


EDITS = {
    "index.html": [
        (r"<strong>\d{4}</strong><span>项测试",
         "<strong>{total}</strong><span>项测试"),
    ],
    "README.md": [
        (r"# \d+ 个测试文件 / \d+ 个用例",
         "# {files} 个测试文件 / {kernel} 个用例"),
        (r"当前 \*\*\d+ 项\*\*（内核 \d+ \+ 壳 \d+）",
         "当前 **{total} 项**（内核 {kernel} + 壳 {shell}）"),
    ],
    ".ai/HANDOFF.md": [
        (r"全量 \d+ 项（本机 Windows \d+ 过 / 2 跳",
         "全量 {total} 项（本机 Windows {win} 过 / 2 跳"),
        (r"（\*\*\d+ 项\*\*＝内核 \d+＋壳 \d+",
         "（**{total} 项**＝内核 {kernel}＋壳 {shell}"),
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="真落盘（默认只打印）")
    args = ap.parse_args()

    m = measure()
    m["win"] = m["total"] - 2          # Windows 上 2 项因缺 bash 跳过
    print("实测：内核 %d + 壳 %d = 全量 %d（测试文件 %d 个）"
          % (m["kernel"], m["shell"], m["total"], m["files"]))

    changed = 0
    for rel, pairs in EDITS.items():
        p = REPO / rel
        t = p.read_text(encoding="utf-8")
        for pat, tmpl in pairs:
            t2, n = re.subn(pat, tmpl.format(**m), t)
            if n != 1:
                print("  ★ %s: %s 命中 %d 次（要 1 次）—— 锚点变了，先看一眼"
                      % (rel, pat[:40], n))
                return 2
            if t2 != t and n:
                changed += 1
            t = t2
        if args.write:
            p.write_text(t, encoding="utf-8")
        print("  %-16s %s" % (rel, "已改" if args.write else "将改"
                              if changed else "无需改"))

    print()
    print("要改 %d 处。%s" % (changed, "已落盘。" if args.write
                             else "加 --write 才落盘。"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
