"""变异测试：把代码改坏，测试会不会红。

## 问的问题

这个仓库把「1200 项测试」当质量信号对外宣传。但计数高 ≠ 验证力高——
2606.19544 的「高可复现性配低效度」说的就是这个：数字漂亮，缺陷照样漏。

量过「有没有恒真/空测试」，结论是基本没有（1 条，且靠 fixture 隐式失败）。
可那只回答了「有没有水」，没回答「水是不是真在护住东西」。

## 三次「造完就信」被抓，这里是前三次

| 出处 | 造的东西 | 怎么被抓的 |
|---|---|---|
| v6.83 | 标注规则 | 把「我举的例子」当全集，8 条标错 |
| v6.86 | `prov` 扫描 | 正则永远返回空，而「空」恰好等于「没发现问题」 |
| v6.86 | 空测试扫描器 | 只认裸 assert，漏掉全部 unittest 风格（误报 10/10） |

v6.87 加了第四条，也是最贵的一条 —— 见下。

## v6.87：在仓库副本上跑，真目录结构上不可能被碰

前一版直接改真源码，靠 `finally` 还原。**实测被硬杀（进程被杀）时还原没跑**，
`verify_quotes.py` 被留在 `floor=1` 的变异状态 —— 正是我在注释里自己写的
「改坏工作区而不自知，比没测更糟」，当场发生了。

`finally` 挡得住异常，**挡不住 SIGKILL**。所以不靠纪律靠结构：
1. 用 `git archive HEAD` 把仓库导到临时目录，**只在副本上改**
2. 副本用 Python 的 zipfile 解，不走 shell（二进制过 PowerShell 管道会被毁）
3. 副本自洽性先验证：未变异的副本必须跑出与真目录一样的结果，
   否则「副本里失败」就不能算「变异被抓到」

## 装上没装上，必须验证

等长改动（`floor=2`→`floor=1`、`45.0`→`90.0`）撞上陈旧 `.pyc` 时，
Python 按 `(mtime, size)` 判定字节码是否失效，两者都没变 → 读到没变的代码，
**却不报错**。所以：子进程带 `PYTHONDONTWRITEBYTECODE=1`、每次跑前清缓存，
外加装上后直接在子进程里断言变异串存在，没生效就中止整个测量。

「以为装上了」是这类工具最常见的失败模式：不报错、给出一个正常的数字、
而那个数字描述的是没被改过的代码。

## 收窄测试范围，以及它的风险

全量约 170 秒；按 import **传递闭包**收窄后约 1 秒。
但收窄可能藏住跨路径的失败 —— v6.81 那个 bug 就是「缓存命中会提前 return」。

所以：收窄跑**绿**的变异，再跑一遍全量确认。慢的只有疑似漏网那些，
而那恰恰是唯一有价值的输出。

## 先验证明敏器

清单里前几条变异故意挑明显该被抓的 —— 先证明尺子准，再拿它量别的。

## 存活 ≠ 缺口

存活有两种原因：等价变异（改了但行为不变）与真盲区。
把等价变异报成缺口，会让人补一堆没用的测试；补完发现行为没变，
下一次就不信这个工具了。**误报比漏报贵** —— 这个项目一贯的取舍。

## 用法

    python scripts/probe_mutation.py --check     # 秒级：锚点体检
    python scripts/probe_mutation.py --report    # 实跑全部变异，约 20 分钟
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import deque
from pathlib import Path

S = Path(__file__).resolve().parent   # 本脚本直接放在 scripts/ 下，别再退一层
REPO = S.parents[2]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")


class Mut:
    __slots__ = ("file", "find", "rep", "why", "expect")

    def __init__(self, file, find, rep, why, expect="any"):
        self.file, self.find, self.rep = file, find, rep
        self.why, self.expect = why, expect


MUTATIONS = [
    # ---- 校准组：明显该被抓到 ----
    Mut("score.py", "if a in cls._SHORT_ANCHORS:", "if False:",
        "短锚词不再走词边界 —— 'rag' 会命中 'Storage'（v6.83 记录的恒真）",
        "caught"),
    Mut("score.py", "if not relevance_reliable:", "if relevance_reliable:",
        "相关性封顶判据取反 —— 该封顶的不封、不该封的封", "caught"),
    Mut("score.py", "            relevance_capped = True",
        "            relevance_capped = False",
        "relevance_capped 标记不再置位 —— v6.81 靠它区分「没听懂」与「不相关」",
        "caught"),
    Mut("score.py",
        "'grade': 'unrated' if relevance_capped else self._get_grade(total),",
        "'grade': self._get_grade(total),",
        "封顶条目照样给 high/medium 评级 —— v6.62 明令不许", "caught"),
    # ---- 边界组 ----
    Mut("score.py",
        "        t = (title or '').lower()\n        if not t:\n            return []",
        "        t = (title or '').lower()",
        "空标题不再早退 —— **等价变异**：空串对每个非空锚词都判不中，结果照样是 []",
        "equivalent"),
    Mut("score.py",
        "    _SHORT_ANCHORS = frozenset(('rag', 'llm', 'k8s', 'sre', 'ann'))",
        "    _SHORT_ANCHORS = frozenset(('rag', 'llm'))",
        "k8s/sre/ann 不再走词边界 —— 但它们也已不在 ANCHOR_HINTS 里"),
    Mut("score.py", "    UNRATED_TOTAL_CAP = 45.0", "    UNRATED_TOTAL_CAP = 90.0",
        "封顶值 45 → 90，等于把封顶放宽一倍（等长改动）"),
    Mut("score.py",
        "        total = max(0.0, min(100.0, total + adj * 100)) if adj else total",
        "        total = (total + adj * 100) if adj else total",
        "Tier 加权后不再夹到 0~100 —— 实测会让 total 变成 101.0"),
    Mut("verify_quotes.py", "def quoted_spans(text, floor=2):",
        "def quoted_spans(text, floor=1):",
        "引号跨度下限 2 → 1 —— 实测 `「字」` 会从 0 个片段变成 1 个（等长改动）"),
]


# ---------------------------------------------------------------------------
# 仓库副本
# ---------------------------------------------------------------------------

def make_copy(dest: Path) -> Path:
    """把**工作区**导到 dest，返回副本里的 scripts 目录。

    先 `git archive HEAD` 拿基线，再把 `git diff HEAD` 打上去 ——
    只用 HEAD 会漏掉未提交的改动，而那正是最需要被量的东西：
    我补缺的两个测试还没提交时，探针仍然报那两个变异 SURVIVED，
    而那**不代表工作区真的没修**，只代表还没提交。

    最后把未跟踪且未 gitignore 的文件也搬过去（新增测试、文档等）。
    `git ls-files --others --exclude-standard` 只列未跟踪且未被忽略的，
    所以 `.research/` 这类目录天然被排除。

    用 Python 的 zipfile 解，不用 shell —— 二进制过 PowerShell 管道会被毁
    （`git archive --format=tar | tar -x` 实测 "Damaged tar archive"）。
    """
    def git(*a, binary=False):
        r = subprocess.run(["git", *a], cwd=str(REPO), capture_output=True,
                           env=ENV)
        if r.returncode != 0:
            raise RuntimeError(f"git {' '.join(a)} 失败："
                               f"{r.stderr.decode('utf-8', 'replace')}")
        return r.stdout if binary else r.stdout.decode("utf-8")

    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(git("archive", "--format=zip", "HEAD",
                                        binary=True))) as z:
        z.extractall(str(dest))

    diff = git("diff", "HEAD")
    if diff.strip():
        r = subprocess.run(["git", "apply", "--directory=.",
                            "--unsafe-paths", "-"], cwd=str(dest),
                           input=diff.encode("utf-8"), capture_output=True,
                           env=ENV)
        if r.returncode != 0:
            raise RuntimeError(
                f"把工作区改动打到副本上失败：{r.stderr.decode('utf-8', 'replace')}\n"
                f"  这一步不能省：只用 HEAD 会漏掉未提交的修复，"
                f"把「还没提交」误报成「没修」。")

    untracked = [p for p in git("ls-files", "--others",
                                "--exclude-standard").splitlines() if p.strip()]
    for rel in untracked:
        srcf = REPO / rel
        if not srcf.is_file():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(srcf, out)

    scr = dest / "skills" / "deep-research-ultra" / "scripts"
    if not (scr / "score.py").exists():
        raise RuntimeError(f"副本结构不对，缺 {scr / 'score.py'}")
    return scr


def clear_pycache(scr: Path):
    for d in scr.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def run_suite(scr: Path, paths, timeout=2400):
    args = [sys.executable, "-m", "pytest", "-q", "--no-header", "-x",
            "-p", "no:cacheprovider"] + [str(p) for p in paths]
    clear_pycache(scr)
    r = subprocess.run(args, cwd=str(scr), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout,
                       env=ENV)
    return r.returncode != 0


# ---------------------------------------------------------------------------

def _imports(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out.add(n.module.split(".")[0])
    return out


def _rev_graph(scr: Path):
    mods = {f.stem: f for f in sorted(scr.glob("*.py"))}
    rev = {}
    for f in sorted(scr.rglob("*.py")):
        if "tests" in f.parts:
            continue
        for dep in _imports(f):
            if dep in mods and dep != f.stem:
                rev.setdefault(dep, set()).add(f.stem)
    return rev


def tests_touching(scr: Path, target):
    """会直接或间接用到 target 的测试文件（传递闭包）。

    只看直接 import 会复现 v6.81 那个错误 —— 那个 bug 藏在"看起来无关"的路径上。
    """
    rev = _rev_graph(scr)
    reach, q = {target}, deque([target])
    while q:
        for nxt in rev.get(q.popleft(), ()):
            if nxt not in reach:
                reach.add(nxt)
                q.append(nxt)
    return [f for f in sorted((scr / "tests").rglob("test_*.py"))
            if _imports(f) & reach]


def assert_mutation_took(scr: Path, mut):
    """**不信任「装上了」** —— 变异没生效时必须中止整个测量。

    等长改动撞上陈旧 `.pyc` 时，Python 按 `(mtime, size)` 判定字节码是否失效，
    两者都没变 → 读到没变的代码却不报错。宁可中止也不能给出一个
    看起来正常的错误结论。
    """
    clear_pycache(scr)
    p = scr / mut.file
    code = (f"print('MUT-PRESENT' if {mut.rep!r} in "
            f"open({str(p)!r},encoding='utf-8').read() else 'MUT-ABSENT')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=ENV)
    if "MUT-PRESENT" not in (r.stdout or ""):
        raise RuntimeError(
            f"变异没真正装上（读到 {(r.stdout or '无输出').strip()}）。\n"
            f"  这几乎总是等长改动撞上陈旧 .pyc 造成的。\n"
            f"  在这个前提修好之前，本次结果一律不作数。")


def anchors_ok(scr: Path = None) -> int:
    """秒级体检：变异锚点是否仍与当前代码吻合。

    记录在案的检测率只对锚点仍吻合时成立。有人改了 `score.py` 那几行，
    锚点就没了，那个百分比就不再描述当前代码 —— 所以这一步必须能随手跑。
    """
    dead = [f"{m.file}: {m.find[:50]!r}" for m in MUTATIONS
            if m.find not in (S / m.file).read_text(encoding="utf-8")]
    if dead:
        print(f"✗ {len(dead)}/{len(MUTATIONS)} 个变异锚点已失效：")
        for d in dead:
            print(f"    {d}")
        print("\n  记录在案的检测率不再描述当前代码 —— 要么重跑 --report，")
        print("  要么把已失效的变异从清单里删掉并说明为什么。")
        return 1
    same = [m for m in MUTATIONS
            if m.find != m.rep and len(m.find) == len(m.rep)]
    print(f"✓ {len(MUTATIONS)} 个变异锚点全部有效，记录的检测率仍适用")
    print(f"  （{len(same)} 个等长改动，已由 PYTHONDONTWRITEBYTECODE + "
          f"装上后验证 双重防着）")
    return 0


def report():
    if anchors_ok() != 0:
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="drux_mut_"))
    print()
    print(f"副本：{tmp}")
    print("（量的是**工作区**，不是 HEAD —— 未提交的改动与未跟踪的新文件都搬过去了）")
    print("（只在副本上改写源码 —— 真目录结构上不可能被碰，进程被杀也不留残局）")
    print()
    try:
        scr = make_copy(tmp)

        # 第 0 步：副本自洽性。跑不通的话，后面的「失败」就不能算变异造成的。
        print("步骤 0：验证副本自洽（未变异）")
        base_red = run_suite(scr, [scr / "tests"])
        print(f"  基线退出码 {'非 0 —— 副本跑不通，先修副本' if base_red else '0 ✓'}")
        if base_red:
            print("  副本自检没过，后续结果一律不作数。")
            return 1
        print()

        results = []
        for i, m in enumerate(MUTATIONS, 1):
            p = scr / m.file
            src = p.read_text(encoding="utf-8")
            if m.find not in src:
                print(f"[{i:>2}/{len(MUTATIONS)}] {m.file}  锚点在副本里失效，跳过")
                continue
            # 副本里随时可以还原，坏了也只是坏副本
            p.write_text(src.replace(m.find, m.rep, 1), encoding="utf-8")
            t0 = time.time()
            try:
                assert_mutation_took(scr, m)
                narrowed = tests_touching(scr, p.stem)
                if run_suite(scr, narrowed):
                    verdict = "caught"
                elif run_suite(scr, [scr / "tests"]):
                    verdict = "caught"
                else:
                    verdict = "SURVIVED"
            finally:
                p.write_text(src, encoding="utf-8")
                clear_pycache(scr)
            dt = time.time() - t0
            print(f"[{i:>2}/{len(MUTATIONS)}] {verdict:<9} {m.file}  {dt:>5.1f}s"
                  f"（收窄 {len(narrowed)} 个测试文件）")
            print(f"        {m.why}")
            results.append({"file": m.file, "why": m.why, "verdict": verdict,
                            "expect": m.expect, "seconds": round(dt, 1)})

        equiv = [r for r in results if r["expect"] == "equivalent"]
        caught = [r for r in results if r["verdict"] == "caught"]
        surv = [r for r in results if r["verdict"] == "SURVIVED"]
        real = [r for r in results if r["expect"] != "equivalent"]
        print()
        print("=" * 78)
        print(f"变异 {len(results)} · 真变异 {len(real)} · 抓到 {len(caught)}"
              f" · 漏网 {len(surv)} · 等价变异 {len(equiv)}")
        if real:
            print(f"**检测率 {len(caught) / len(real) * 100:.1f}%**（已剔除等价变异）")
        calib = [r for r in results if r["expect"] == "caught"]
        ok = sum(1 for r in calib if r["verdict"] == "caught")
        print()
        print(f"校准组 {ok}/{len(calib)} 抓到。"
              + ("尺子是准的，下面的数字有意义。" if ok == len(calib)
                 else "★ 尺子不准，下面的数字不作数。"))
        if surv:
            print()
            print("存活者（要逐条分清是等价变异还是真缺口）：")
            for r in surv:
                tag = "等价" if r["expect"] == "equivalent" else "★待查"
                print(f"  [{tag}] {r['file']}  {r['why']}")
        out = S / ".research" / "mutation.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print()
        print(f"落盘 → {out.name}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="变异测试：把代码改坏，看测试会不会红")
    ap.add_argument("--report", action="store_true", help="实跑全部变异（慢，约 20 分钟）")
    ap.add_argument("--check", action="store_true", help="只验变异锚点（秒级）")
    a = ap.parse_args(argv)
    if a.check:
        return anchors_ok()
    return report()


if __name__ == "__main__":
    sys.exit(main())