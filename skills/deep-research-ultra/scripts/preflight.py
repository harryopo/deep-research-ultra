#!/usr/bin/env python3
"""preflight — 过程门：对 Lead 自己的工作做机械检查，而不只是对报告做。

## 为什么要有这个

本项目至今 1100+ 项测试**全是检查产出**（报告、账本、防伪戳、文档数字）。
**对过程零检查** —— 这就是缺口。

`docs/dev/v6.84-过程门与文献依据.md` 记了为什么这不是"再加几条提醒"：

- Huang et al. 2024 / 2402.08115：LLM **没有外部信号时无法可靠自我纠正**，
  加自我验证**让性能变差**，应做成 LLM-Modulo（验证交给外部可靠系统）
- 2606.19544：高重测一致性可以与严重偏置**并存** —— 我重读自己的产出觉得
  "没问题"，那是高可复现性配低效度；原始一致率把区分度高估 33–41pp
- 2507.06920：LLM 的错误**高度聚集**，同模型验证者有**相同的盲区**
  （homogenization trap）

所以过程门只做一件事：**用结构上不同、失效模式不相关的东西去查。**
具体就是可执行的检查 —— 脚本要么跑得起来要么跑不起来，没有"感觉"。

## 明确不做的事

**不做自我复述/自我审查环节。** 那是把验证拉回同一个模型的同一次推理，
按上面三篇的结论不但无效还有害。这里只做能机械判定的。

## 检查项

1. `smoke`   每个脚本能 import、`--help` 能跑（抓语法错、缺 import、坏引号）
2. `single`  被钉住的"单一来源"概念只在一处定义（抓同一件事两份实现）
3. `prov`   CHANGELOG 里标了「实测」的条目，其数字能被某个受版本控制的
            脚本或夹具复算（抓"结论挂在一个别人跑不了的草稿上"）

## 用法

    python preflight.py            # 全跑，exit 0 = 过
    python preflight.py --only smoke
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
# SKILL = <repo>/skills/deep-research-ultra → 往上是
#   parents[0] <repo>/skills    parents[1] <repo>    parents[2] <repo>/skills 的父
# 仓库根是 parents[1]。第一版写的是 parents[2]，指到 <repo>/skills 去了 ——
# 过程门第一次跑就报「找不到 CHANGELOG 的版本段」，它自己把这条抓出来了。
REPO = SKILL.parents[1]

# 「单一来源」概念清单：concept -> 只允许在哪一个文件里定义
# 起因是 v6.83 出现过两份锚词表并存（分析脚本自写了一份，score.py 一份），
# 两份都合理、算出来的收益差一倍，直到把同一个测试挂在两份表上才暴露。
SINGLE_SOURCE = {
    "主题锚词表": SCRIPTS / "score.py",            # ANCHOR_HINTS
}

# 这些文件不是可执行脚本，跑它们没有意义。
# **只排除这几个具体文件，不是排除所有下划线开头的**——第一版用
# `startswith("_")` 过滤，于是 `_v684_tmp_broken.py` 这类坏脚本能溜过去。
_DUNDER = {"__init__.py", "__main__.py"}


def _out(ok: bool, label: str, detail: str = "") -> bool:
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  {detail}" if detail else ""))
    return ok


# ---------------------------------------------------------------------------
# 1) smoke：脚本能跑起来
# ---------------------------------------------------------------------------

def _script_ok(p: Path) -> tuple[bool, str]:
    """跑一次 `--help`，判它是不是「argparse 打印帮助后正常退出」。

    **不能用退出码判。** 第一版写成 `returncode not in (0, 1, 2)` 就放行，
    而 `SyntaxError` 的退出码恰好也是 **1** —— 于是本轮 E 类错误的典型形态
    （中文引号提前闭合、缺 import）**整类漏过**，门形同虚设。

    判据改成看输出：正常的 argparse 退出必然打 usage/--help；
    出现 Traceback / SyntaxError 就是崩，哪怕退出码落在 (0,1,2) 里。
    """
    try:
        r = subprocess.run([sys.executable, str(p), "--help"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           cwd=str(SCRIPTS), timeout=120)
    except subprocess.TimeoutExpired:
        return False, "超时"
    blob = (r.stdout or "") + (r.stderr or "")
    if "Traceback" in blob or "SyntaxError" in blob or "ModuleNotFoundError" in blob:
        first = next((ln for ln in blob.splitlines()
                      if "Error" in ln or "Traceback" in ln), "")
        return False, (first.strip()[:60] or f"exit={r.returncode}")
    if "usage" not in blob.lower() and "--help" not in blob.lower():
        # 没崩，但也没打出帮助——可能是这个脚本本来就不收 --help。
        # 判为可疑而不判为崩：判据放宽是为了不误伤，代价是可能漏掉
        # "脚本忽略了 --help 静默干了别的事"，那属于另一类问题。
        return True, "（未打印 usage，按可疑但不判崩）"
    return True, ""


def check_smoke() -> bool:
    print("smoke —— 每个脚本能 import 且 --help 不崩")
    print("  （v6.84：E 类错误「对运行时行为假设错误」共 4 次，是本轮最高频的一类。"
          "中文引号提前闭合、缺 import 都是这一类，而它们全部表现为"
          "「脚本在真正该干活的那一刻崩」）")
    print()
    ok = True
    scripts = sorted(p for p in SCRIPTS.glob("*.py")
                     if p.name not in _DUNDER)
    crashed = []
    for p in scripts:
        good, why = _script_ok(p)
        if not good:
            crashed.append(f"{p.name}({why})")
    ok &= _out(not crashed,
                f"{len(scripts)} 个脚本 --help 全部正常",
                f"崩的: {crashed}" if crashed else "")

    ana = sorted((SCRIPTS / "analysis").glob("*.py"))
    acrashed = []
    for p in ana:
        good, why = _script_ok(p)
        if not good:
            acrashed.append(f"{p.name}({why})")
    ok &= _out(not acrashed,
                f"{len(ana)} 个 analysis 脚本 --help 全部正常",
                f"崩的: {acrashed}" if acrashed else "")
    return ok


# ---------------------------------------------------------------------------
# 2) single：单一来源
# ---------------------------------------------------------------------------

def check_single_source() -> bool:
    print()
    print("single-source —— 被钉住的概念只在一处定义")
    print("  （v6.83 出过两份锚词表并存：分析脚本自写一份、score.py 一份，"
          "算出来的收益差一倍，直到把同一个测试挂在两份表上才暴露）")
    print()
    ok = True
    for concept, owner in SINGLE_SOURCE.items():
        hits = []
        marker = "ANCHOR_HINTS"
        for p in sorted(SCRIPTS.rglob("*.py")):
            if any(part.startswith('.') for part in p.relative_to(SCRIPTS).parts):
                continue          # gitignore 的草稿目录不参与——它不进包
            if "tests" in p.relative_to(SCRIPTS).parts:
                continue          # 测试里引用不算定义
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Assign):
                    tgts = [t.id for t in n.targets if isinstance(t, ast.Name)]
                    if marker in tgts:
                        hits.append(p.relative_to(SCRIPTS).as_posix())
        allowed = owner.relative_to(SCRIPTS).as_posix()
        others = [h for h in hits if h != allowed]
        ok &= _out(not others, f"「{concept}」只定义在 {allowed}",
                   f"另有定义: {others}" if others else
                   f"（共 {len(hits)} 处）")
    return ok


# ---------------------------------------------------------------------------
# 3) prov：结论挂在可复算的物件上
# ---------------------------------------------------------------------------

# CHANGELOG 里标「实测」且带数字的版本 → 必须有受版本控制的复算脚本
# 键是 CHANGELOG 里的版本号，值是能复算它的脚本
PROVENANCE = {
    # v6.84.0 之前不强制：那时的版本段里 23 个里有 20 个含实测数字，
    # 全补分析脚本等于补一套没用的东西。检查从 v6.84.0 起生效，
    # 之前的条目视为既有事实（见 BASELINE）。
    "v6.83.0": [SCRIPTS / "analysis" / "relevance.py"],
    "v6.86.0": [SCRIPTS / "analysis" / "holdout.py"],
}

# 豁免：同样是实测数字，但**不需要**分析脚本 —— 必须在代码里写清理由，
# 否则「忘记登记」和「有理由地豁免」就分不开，那道门形同虚设。
EXEMPT = {
    "v6.84.0": "本版数字是测试计数（1187）与版本钉子，"
               "由 run_all_tests.py 与 git tag 复算，不是分析结论",
    "v6.85.0": "纯版本对齐，无实测数字",
    "v6.87.0": "检测率 75% 需 `probe_mutation.py --report` 实跑约 20 分钟，"
               "放进过程门就没人会跑 —— 慢到没人跑的门等于没有。"
               "改用秒级的 `--check` 保证变异锚点仍与当前代码吻合，"
               "即记录在案的检测率仍适用；两者一起钉在 "
               "test_v687_mutation_probe.py",
}

# 检查从哪个版本开始生效。写成常量而不是"当前版本"，
# 是为了让规则可预测 —— 否则每升一版就等于又豁免了一版。
BASELINE = (6, 84, 0)

# 注意：这个正则**不能**要求开头有 "##" —— `re.split(r"^##\s+")` 切出来的段
# 开头已经是版本号了。第一版这里写着 "##\s+v(...)"，于是扫描永远返回空；
# 而「空」恰好等于「没有未登记项」，两次空抵消，**检查看起来一直是绿的**。
# 这类静默失效比报错更坏：报错会被看见。
_VER = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def _vtuple(ver):
    m = re.match(r"v(\d+)\.(\d+)\.(\d+)", ver or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)


def _sections_with_measured(text):
    """找出所有「标了实测且带小数」的版本段。

    为什么要扫出来而不是只查 PROVENANCE 里那几项：v6.86 的第一版
    就是这么漏的 —— CHANGELOG 里写了新的实测数字，而 `PROVENANCE` 是
    硬编码的，**没人提醒要登记**，检查照样全绿。只查登记项 = 查自己。
    """
    found = []
    parts = re.split(r"^##\s+", text, flags=re.M)[1:]
    for sec in parts:
        m = _VER.match(sec)
        if not m:
            continue
        ver = f"v{m.group(1)}.{m.group(2)}.{m.group(3)}"
        body = sec[len(m.group(0)):]
        if "实测" in body and re.search(r"\d+\.\d", body):
            found.append(ver)
    return found


def check_provenance() -> bool:
    print()
    print("provenance —— 标「实测」的结论能被别人重跑")
    print("  （v6.84 的起因：v6.83 的 precision/recall/AUC 写进了 CHANGELOG，"
          "但产出脚本在 gitignore 里 —— 数字只有一半可复算。"
          "对应 2606.19544 的「高可复现性配低效度」）")
    print()
    ok = True
    changelog = REPO / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""

    # --- 正向：扫描 CHANGELOG，看有没有「该登记却没登记」的版本段 ---
    unregistered = [ver for ver in _sections_with_measured(text)
                    if ver not in PROVENANCE and ver not in EXEMPT
                    and _vtuple(ver) >= BASELINE]
    ok &= _out(not unregistered, "v6.84.0 之后标「实测」的版本段都已登记",
               f"未登记: {unregistered} —— 要么把复算脚本加进 PROVENANCE，"
               f"要么在 EXEMPT 里写明为什么不需要（别默默跳过）"
               if unregistered else
               f"已登记 {len(PROVENANCE)} 项 + 豁免 {len(EXEMPT)} 项")

    for ver, scripts in PROVENANCE.items():
        has_section = f"## {ver}" in text
        if not has_section:
            ok &= _out(False, f"{ver} 在 CHANGELOG 里有条目", "找不到该版本段")
            continue
        missing = [p.relative_to(REPO).as_posix() for p in scripts
                   if not p.exists()]
        ok &= _out(not missing, f"{ver} 的复算脚本已入库",
                   f"缺: {missing}" if missing else
                   "、".join(p.relative_to(REPO).as_posix() for p in scripts))

    # --- 反向：analysis/ 里的脚本必须真的跑得起来且与 CHANGELOG 对账通过 ---
    for p in sorted((SCRIPTS / "analysis").glob("*.py")):
        if "--check" not in p.read_text(encoding="utf-8"):
            ok &= _out(False, f"{p.name} 支持 --check",
                       "进了版本控制的分析脚本必须能自证与 CHANGELOG 一致")
            continue
        r = subprocess.run([sys.executable, str(p), "--check"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           cwd=str(SCRIPTS), timeout=300)
        ok &= _out(r.returncode == 0, f"{p.name} --check 通过",
                   (r.stdout or "").strip().splitlines()[-1][:70]
                   if r.returncode else "")
    return ok


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="过程门：Lead 的工作要不要机械检查")
    ap.add_argument("--only", choices=["smoke", "single", "prov"])
    a = ap.parse_args(argv)

    print("=" * 72)
    print("过程门 preflight —— 检查过程，不只检查产出")
    print("=" * 72)
    print()
    print("为什么不加「自我审查」环节：LLM 没有外部信号时无法可靠自我纠正，")
    print("加自我验证会让性能变差（ICLR 2024 / 2402.08115）；同模型验证者与")
    print("生成者有相同的盲区（homogenization trap, 2507.06920）。")
    print("所以这里只做能机械判定的检查。详见 docs/dev/v6.84-过程门与文献依据.md")
    print()

    checks = {"smoke": check_smoke,
              "single": check_single_source,
              "prov": check_provenance}
    order = [a.only] if a.only else ["smoke", "single", "prov"]
    ok = True
    for name in order:
        ok &= checks[name]()

    print()
    print("=" * 72)
    print(f"过程门：{'通过' if ok else '未通过'}"
          + ("　（这只覆盖有机械判据的错误；「没想到要去查」那类挡不住）"
             if ok else ""))
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
