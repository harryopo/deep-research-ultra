# -*- coding: utf-8 -*-
"""打一个可测试的安装包，并**在包内**验证它。

## 为什么要把它从临时脚本搬进仓库

这个脚本的每一版都住在 TEMP 里，于是每一版都自带一个**假绿灯**：
skip 对账那一步用 `startswith("SKIP ")` 去匹配 `pytest -rs` 印的
`SKIPPED [1] …`，一个都匹配不上，于是「抓到 0 条」被判成「没有异常 skip」，
而同一屏的 `run_all_tests.py` 明明写着 `6 skipped`。

**过滤器返回空集合时必须判失败，不能判通过。** 这条已经写在下面的
`reconcile_skips()` 里，也有一版一版的教训在旁边。

## 四条规矩都是项目自己的，不是这里发明的

1. **`git archive HEAD`，不用 `git ls-files`。**
   `git ls-files` + `z.write(root/f)` 读的是**工作区**内容 ——
   HANDOFF v7.1.0 记着「打包第一版用 `git ls-files` 会把未提交改动混进包」。
   工作区干净时两者等价，但**等价是巧合不是保证**。
2. **顶层只有 `deep-research-ultra/`**（v7.1.0 补的；6.60.0 那版漏了这层）。
3. **解压后在包内真跑一遍**（v7.2.0 起的验收）。包外绿、包内缺文件/路径不对
   是最常见的发布事故 —— 过程门依赖仓库根路径，包里就是包根。
4. **打包时发现的差异要如实报，不当门。** 曾经把「包内 SKILL.md 版本必须等于
   内核号」当门，结果是我自己的假设把好包判成不可用 ——
   `SKILL.md` 的 `version:` 才是单源，CHANGELOG 的版本比它细。

## 用法

    python package_release.py --version v7.7.0
    python package_release.py --version v7.7.0 --dry-run   # 只核对，不打包

任何一步红就 exit 1，不报「可用」。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE
SKILL = SCRIPTS.parent
REPO = SKILL.parents[1]
DIST = REPO / "dist"
PREFIX = "deep-research-ultra/"

# 包内必须存在的文件。含每个版本新增的关键文件 ——
# 「文件在不在」与「内容对不对」是两回事，下面还会查内容。
MUST_HAVE = [
    "README.md",
    "run_all_tests.py",
    "server.py",
    "mcp.json",
    "skills/deep-research-ultra/SKILL.md",
    "skills/deep-research-ultra/scripts/install.py",
    "skills/deep-research-ultra/scripts/preflight.py",
    "skills/deep-research-ultra/scripts/report.py",
    "skills/deep-research-ultra/scripts/package_release.py",
    "skills/deep-research-ultra/scripts/evals/run_evals.py",
    "skills/deep-research-ultra/evals/evals.json",
]

# 允许的 skip 理由白名单。出现第四种 = 包里缺东西，不是环境问题。
ALLOWED_SKIP = (
    "本机无 bash",       # setup-mcp.sh 要 bash
    "需要 git 检出",     # 变异探针靠 git archive 造副本
    "还没跑过",          # 读 .research/ 里的结果文件，不进包
)


def _git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=str(cwd or REPO),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def reconcile_skips(stdout: str, claimed: int) -> tuple[list[str], list[str]]:
    """把 `pytest -rs` 的输出拆成 (逐条理由, 问题)。

    ⚠️⚠️ 这一段被写错过三次，每次都造出一个假绿灯：
      * 按 `"SKIP "`（带空格）匹配，而 pytest 印的是 `SKIPPED [1] …` → 抓到 0 条
      * 抓到 0 条时**继续判通过** —— 「没抓到」被当成了「没有问题」
      * 只看自己抓到几条，不与 `run_all_tests.py` 报的数对账

    修法是三条硬规则：
      1. 匹配 `SKIPPED`（不带尾空格），并剥掉 `[n] path:line: ` 前缀
      2. **空集合直接判有问题** —— 它与 claimed 不一致就是矛盾
      3. 逐条抓到的条数必须等于 claimed（两处独立来源），否则有问题
    """
    problems: list[str] = []
    reasons: list[str] = []
    for line in stdout.splitlines():
        s = line.strip()
        if not s.startswith("SKIPPED"):
            continue
        body = re.sub(r"^\[\d+\]\s*", "", s[len("SKIPPED"):].strip())
        parts = body.split(": ", 1)
        reasons.append(parts[1].strip() if len(parts) > 1 else "")

    summary = [l for l in stdout.splitlines() if "passed" in l and "skipped" in l]
    m = re.search(r"(\d+) skipped", summary[-1]) if summary else None
    from_summary = int(m.group(1)) if m else -1

    print("      汇总行报 skipped=%s ｜ 逐条抓到 %d 条 ｜ run_all_tests 报 %d"
          % (from_summary, len(reasons), claimed))
    if not reasons:
        problems.append(
            "抓到 0 条 skip，但汇总说 %d 条、run_all_tests 说 %d 条 —— "
            "过滤器又没匹配上（pytest 印的是 SKIPPED，不是 'SKIP '）"
            % (from_summary, claimed))
    if from_summary != claimed:
        problems.append("两处来源不一致：pytest 汇总 %s vs run_all_tests %d"
                        % (from_summary, claimed))
    if len(reasons) != from_summary:
        problems.append("逐条抓到 %d 条 ≠ 汇总的 %s 条"
                        % (len(reasons), from_summary))
    unknown = [r for r in reasons if not any(a in r for a in ALLOWED_SKIP)]
    for r in unknown:
        problems.append("无法解释的 skip：%s" % r[:70])
    if reasons and not unknown:
        print("      每条都对得上三个环境守卫之一 → 是环境守卫，不是缺文件")
    return reasons, problems


def build(version: str, dry_run: bool = False) -> int:
    problems: list[str] = []
    notes: list[str] = []

    print("=" * 78)
    print("打 deep-research-ultra-%s.candidate.zip" % version)
    print("=" * 78)
    rc, head, _ = _git("rev-parse", "HEAD")
    if rc != 0:
        print("  ★ 这里不是 git 检出，打不了包（git archive 需要 HEAD）")
        return 1
    _, dirty, _ = _git("status", "--porcelain")
    tracked_dirty = [l for l in dirty.splitlines()
                     if l.strip() and not l.startswith("??")]
    print("  HEAD       %s" % head[:12])
    print("  已跟踪改动 %s" % ("无 —— 包内容等于提交内容"
                            if not tracked_dirty else tracked_dirty))
    if tracked_dirty:
        notes.append("**工作区有未提交的已跟踪改动**，而 `git archive HEAD` "
                     "不会把它们打进包 —— 包里是 HEAD 的内容。")

    out = DIST / ("deep-research-ultra-%s.candidate.zip" % version)
    if dry_run:
        print("\n  --dry-run：不写文件，只做后面的核对")
    else:
        DIST.mkdir(exist_ok=True)
        if out.exists():
            out.unlink()
        r = subprocess.run(
            ["git", "archive", "--format=zip", "--prefix=" + PREFIX, "HEAD"],
            cwd=str(REPO), capture_output=True)
        if r.returncode != 0:
            print("  git archive 失败：%s" % r.stderr.decode("utf-8", "replace"))
            return 1
        out.write_bytes(r.stdout)
        print("  已写 %s  %.0f KB" % (out.name, out.stat().st_size / 1024))

    # ---------------------------------------------------------------- 结构
    print("\n【结构】")
    with zipfile.ZipFile(out) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        inside = [n[len(PREFIX):] for n in names if n.startswith(PREFIX)]
        blobs = {n: z.read(n) for n in names if n.startswith(PREFIX)}
    tops = sorted({n.split("/")[0] for n in names})
    junk = [n for n in names if "/__pycache__/" in n or n.endswith(".pyc")
            or "/.research/" in n or "/dist/" in n]
    print("  条目 %d ｜ 顶层 %s ｜ 垃圾条目 %d" % (len(names), tops, len(junk)))
    if tops != [PREFIX.rstrip("/")]:
        problems.append("顶层不止一个/不对：%s" % tops)
    if junk:
        problems.append("垃圾条目 %d 个：%s" % (len(junk), junk[:3]))

    miss = [m for m in MUST_HAVE if m not in inside]
    print("  关键文件 %d/%d%s" % (len(MUST_HAVE) - len(miss), len(MUST_HAVE),
                               "" if not miss else "  缺：%s" % miss))
    if miss:
        problems.append("缺 %d 个关键文件：%s" % (len(miss), miss))

    # 关键修复的**内容**必须在包里 —— 「文件在」不等于「修的那行在」。
    # ⚠️ 每项都指明查哪个文件。第一版三项全查 preflight.py，
    # 而 PARTIAL_NOTES 根本不在 preflight.py 而在 evals/run_evals.py ——
    # 于是它报「包内少了 v6.98 的修复」，而包里明明有。
    # **一个报错的检查比没有检查更坏**：它会让你去修一个没坏的东西。
    need_marks = [
        ("skills/deep-research-ultra/scripts/preflight.py",
         ".git 判据（v6.97）", 'in_checkout = (REPO / ".git").exists()'),
        ("skills/deep-research-ultra/scripts/preflight.py",
         "_last_line 兜底（v6.97）", "def _last_line("),
        ("skills/deep-research-ultra/scripts/evals/run_evals.py",
         "评测子集 PARTIAL_NOTES（v6.98）", "PARTIAL_NOTES = {"),
    ]
    missing_marks = []
    for rel, what, needle in need_marks:
        blob = blobs.get(PREFIX + rel)
        if blob is None:
            missing_marks.append("%s（文件不在包里）" % what)
            continue
        if needle not in blob.decode("utf-8", "replace"):
            missing_marks.append("%s（%s 里没有 %r）" % (what, rel.split("/")[-1], needle))
    problems.extend("包内缺关键修复：%s" % m for m in missing_marks)
    print("  关键修复在包里：%s"
          % ("%d/%d 全部在 ✓" % (len(need_marks), len(need_marks))
             if not missing_marks else "缺：%s" % missing_marks))

    md = blobs[PREFIX + "skills/deep-research-ultra/SKILL.md"].decode("utf-8", "replace")
    tv = [l.strip() for l in md.splitlines()[:12] if l.strip().startswith("version:")]
    sk_ver = tv[0].split(":", 1)[1].strip() if tv else "?"
    print("\n【版本】包内 SKILL.md 声明 %s（它是 README/index.html 的单源）" % sk_ver)

    rn = DIST / "release-notes.md"
    if rn.exists():
        m = re.search(r"内核 ([\d.]+) / 插件壳 ([\d.]+)", rn.read_text(encoding="utf-8"))
        pj = next((n for n in blobs if n.endswith(".qoder-plugin/plugin.json")), None)
        shell_v = json.loads(blobs[pj].decode("utf-8"))["version"] if pj else "?"
        if not m or m.group(1) != sk_ver or m.group(2) != shell_v:
            problems.append("release-notes.md 与包里对不上：notes=%s 包=%s/%s"
                            % (m.groups() if m else None, sk_ver, shell_v))
        else:
            print("  release-notes 与包一致：内核 %s / 插件壳 %s ✓" % (sk_ver, shell_v))

    if dry_run:
        for n in notes:
            print("\n⚠ %s" % n)
        if problems:
            print("\n★ 不可用：")
            for p in problems:
                print("  - %s" % p)
            return 1
        print("\n结构核对通过（--dry-run 未打包）")
        return 0

    # ---------------------------------------------------------------- 包内实跑
    print("\n" + "=" * 78)
    print("【包内验证】解压后跑 —— 包外绿不代表包能用")
    print("=" * 78)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    pkg = Path(tempfile.mkdtemp(prefix="pkgtest_"))
    results: list[tuple[str, bool]] = []
    claimed_skips = -1
    try:
        with zipfile.ZipFile(out) as z:
            z.extractall(str(pkg))
        inner = pkg / "deep-research-ultra"

        def step(label, args, cwd, timeout=2400):
            r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout, env=env)
            lines = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
            print("  %-28s exit=%d" % (label, r.returncode))
            for l in lines[-3:]:
                print("      " + l[:94])
            if r.returncode != 0 and r.stderr:
                for l in r.stderr.strip().splitlines()[-2:]:
                    print("      ! " + l.strip()[:94])
            return r.returncode == 0, lines

        ok, lines = step("run_all_tests.py",
                         [sys.executable, "-X", "utf8", "run_all_tests.py"], inner)
        results.append(("run_all_tests.py", ok))
        for l in lines:
            m = re.search(r"(\d+) skipped", l)
            if m and "合计" in l:
                claimed_skips = int(m.group(1))

        results.append(("preflight.py", step(
            "preflight.py",
            [sys.executable, "-X", "utf8",
             "skills/deep-research-ultra/scripts/preflight.py"], inner, 900)[0]))
        results.append(("evals/run_evals.py", step(
            "evals/run_evals.py",
            [sys.executable, "-X", "utf8",
             "skills/deep-research-ultra/scripts/evals/run_evals.py"], inner, 900)[0]))

        for name in ("boundaries.py", "holdout.py", "relevance.py"):
            r = subprocess.run(
                [sys.executable, "-X", "utf8",
                 "skills/deep-research-ultra/scripts/analysis/" + name, "--check"],
                cwd=str(inner), capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=env, timeout=300)
            first = ((r.stdout or "").strip().splitlines() or [""])[0]
            print("  %-28s exit=%d" % (name + " --check", r.returncode))
            print("      " + first[:94])
            results.append((name, r.returncode == 0))

        # skip 对账：拿 pytest 的**逐条理由**与两处汇总数字对账
        print("\n  【skip 对账】")
        r = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "--no-header",
             "-p", "no:cacheprovider", "skills/deep-research-ultra/scripts/tests", "-rs"],
            cwd=str(inner), capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=2400)
        _reasons, probs = reconcile_skips(r.stdout or "", claimed_skips)
        problems.extend(probs)
    finally:
        shutil.rmtree(pkg, ignore_errors=True)

    bad = [n for n, ok in results if not ok]
    if bad:
        problems.append("包内没过：%s" % bad)

    # ---------------------------------------------------------------- 摘要
    print("\n" + "=" * 78)
    print("包      %s" % out)
    print("内容    git HEAD %s" % head[:12])
    print("大小    %d 字节（%.0f KB）" % (out.stat().st_size, out.stat().st_size / 1024))
    print("SHA256  %s" % hashlib.sha256(out.read_bytes()).hexdigest().upper())
    print("=" * 78)
    for n in notes:
        print("\n⚠ %s" % n)
    if problems:
        print("\n★ 不可用：")
        for p in problems:
            print("  - %s" % p)
        return 1
    print("\n与仓库 HEAD 一致，包内全绿 —— 这个包可以拿去测。")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="打一个可测试的安装包并在包内验证它（只用 HEAD 的内容）")
    p.add_argument("--version", required=True,
                   help="包版本，如 v7.7.0（产物名会带 .candidate 后缀）")
    p.add_argument("--dry-run", action="store_true",
                   help="只做结构与内容核对，不写文件、不在包内跑")
    return build(p.parse_args(argv).version, p.parse_args(argv).dry_run)


if __name__ == "__main__":
    raise SystemExit(main())