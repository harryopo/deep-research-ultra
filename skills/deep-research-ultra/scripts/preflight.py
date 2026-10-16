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
    # v6.88 的**分母 85** 由 boundaries.py 复算（秒级，进过程门）。
    # 注意同一版的 **56.2% 检测率** 不在此列：它要跑变异探针约 30 分钟，
    # 放进过程门就没人会跑（慢到没人跑的门等于没有）。
    # 那部分靠 `probe_mutation.py --systematic` 手动复算，
    # 结果落在 `.research/mutation_systematic.json`，并在 CHANGELOG 写明样本量。
    "v6.88.0": [SCRIPTS / "analysis" / "boundaries.py"],
    # v6.95 与上面三条不同：它量的是**一阶**问题 ——「产出的东西对不对」，
    # 而前三条量的是「记在案的数字能不能被别人重跑」。它也更快（~4 秒），
    # 所以进 PROVENANCE 而不是 EXEMPT。
    # 第一次跑就红：dr-024 期望 evicted_lru 按条目数淘汰时 +1，实得 0。
    # 修好后 2/2 条评测 8/8 项期望通过，**未纳入 38/40（需人判，不计通过）**。
    "v6.95.0": [SCRIPTS / "evals" / "run_evals.py"],
    # v6.96 的实测数字就是 v6.95 那个评测器的覆盖面（2/40 -> 6/40、28/28 项），
    # 复算脚本仍是同一个。登记两次是因为按版本段核对 ——
    # 「这版没登记新东西」不是豁免的理由，那会让规则形同虚设。
    "v6.96.0": [SCRIPTS / "evals" / "run_evals.py"],
}

# 豁免：同样是实测数字，但**不需要**分析脚本 —— 必须在代码里写清理由，
# 否则「忘记登记」和「有理由地豁免」就分不开，那道门形同虚设。
EXEMPT = {
    "v6.84.0": "本版数字是测试计数（1187）与版本钉子，"
               "由 run_all_tests.py 与 git tag 复算，不是分析结论",
    "v6.85.0": "纯版本对齐，无实测数字",
    "v6.91.0": "本版数字是边界实跑结果（61.2% = 41/67）与等价变异实证"
               "（L493 扫 401 个输入、L219 扫 27 个）"
               "以及编码门覆盖的 233 个文件数。"
               "等价变异那两条**没有任何测试能钉**（它们改了行为不变），"
               "要复算就得重跑变异探针；边界钉死那 30 条则已由 "
               "tests/verify_boundary_pins.py 逐条装变异验证过（30/30 变红）",
    "v6.89.0": "本版数字是**行为实测**（_score_accuracy 三档 30/50/100、"
               "时效阶梯 100/90/75/60/45/25、空查询相关性 60，"
               "以及那个事故本身：37/37 全 SURVIVED）。"
               "它们全部由 `test_v688_boundary_pins.py` 逐条钉住，"
               "并由 `tests/verify_boundary_pins.py` 验证过"
               "（装上变异要求它们变红）—— 已是可复算的，"
               "不必为它们再写一支分析脚本",
    "v6.87.0": "检测率 75% 需 `probe_mutation.py --report` 实跑约 20 分钟，"
               "放进过程门就没人会跑 —— 慢到没人跑的门等于没有。"
               "改用秒级的 `--check` 保证变异锚点仍与当前代码吻合，"
               "即记录在案的检测率仍适用；两者一起钉在 "
               "test_v687_mutation_probe.py",
    # v6.94 的过程门不是绿的 —— 是它**自己**先红的：我写了 90.6% 这个
    # 实测数字却没登记，于是报「未登记: ['v6.94.0']」。拦得住。
    # 处置与 v6.87/v6.91 同类：约 40 分钟的探针不进过程门。
    # 凭什么仍然算「可复算」：
    #   · 数字本体 —— `probe_mutation.py --systematic --cap 8`，命令与
    #     样本量（32 个变异、种子 20261013）都写在 CHANGELOG v6.94，
    #     结果落在 `.research/mutation_systematic.json`。
    #   · 那 5 条真缺口的钉死 —— `tests/verify_boundary_pins.py`
    #     逐条装变异验证过（CLAIMED 61/61 变红、EQUIVALENT 10 个确认不该红），
    #     行号漂移由 `test_v692_pin_anchors.py` 兜。
    #   · 2 条等价变异的实证 —— `verify_quotes.py:109` 扫 63 个用例零差异、
    #     `research.py:729` 靠 `bool(Path)` 恒真短路，都在测试里留了夹具。
    #   · 复核修正的方向 —— `test_v694_direction.py` 7 项，含一条端到端证伪。
    "v6.94.0": "本版数字是机械变异抽样认证检测率 90.6%（29/32，含 1 个靠挂死；"
               "只算断言 87.5%），需 `probe_mutation.py --systematic --cap 8` "
               "实跑约 40 分钟，放进过程门就没人会跑 —— 慢到没人跑的门等于没有。"
               "数字本体、样本量（32 个变异、种子 20261013）与落盘路径都写在 "
               "CHANGELOG v6.94；那 5 条真缺口已由 tests/verify_boundary_pins.py "
               "逐条装变异验证（61/61 变红 + 10 个等价变异确认不该红），"
               "2 条等价变异的实证（63 用例零差异 / bool(Path) 短路）留在测试夹具里，"
               "复核修正的方向由 test_v694_direction.py 兜",
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

def check_evals() -> bool:
    """一阶：跑 `evals.json` 的机械判定子集。

    ## 为什么这道检查与另外三道不同

    smoke / single_source / provenance 都在问「**过程**对不对」，
    而这道在问「**产出的东西**对不对」。

    在它出现之前，本项目所有量化都在二阶：变异检出率 90.6%、
    边界覆盖 72/72、测试 1372 项。它们回答的是「这套测试能不能抓出代码里的 bug」，
    **没有一条回答「插件的产出对不对」**。而 1372 项测试全绿完全可以配一个
    产出平庸结果的插件 —— 绿灯只说明灯是亮的。

    v6.95 第一次跑就红：`dr-024` 期望「按条目数淘汰时 evicted_lru 计数 +1」，
    实得 `evicted_lru=0` —— `cache._evict_if_needed` 把归属写在**清标记之后**，
    于是这个计数器恒为 0。而 1372 项测试里没有一条断言它。

    ## 为什么它敢进过程门

    因为它**只跑得动机械可判定的那几条**，而且**打印三个分母**：
    机械判定 x/y、未纳入 z/40、期望级 a/b。
    没纳入的不计为通过 —— 那 38 条要人判，硬打分只会造出假的精确度。
    慢门没人跑，所以这道只收秒级的；40 分钟的变异探针不进这里。
    """
    runner = SCRIPTS / "evals" / "run_evals.py"
    print()
    print("一阶 —— evals.json 机械判定子集")
    print("-" * 72)
    if not runner.exists():
        print(f"  [FAIL] 评测器不存在: {runner}")
        return False
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", str(runner)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(REPO), timeout=600)
    lines = [ln.strip() for ln in (r.stdout or "").splitlines()
             if ln.strip().startswith("[FAIL]")]
    # **两个分母都要打**。只打「机械判定 2/2」的话，读的人会以为 40 条都过了 ——
    # 实际有 38 条要人判。「未纳入」那一行就是防这个的。
    for ln in (r.stdout or "").splitlines():
        s = ln.strip()
        if "条评测" in s or s.startswith("未纳入 "):
            print("  " + s)
    for ln in lines:
        print("  " + ln)
    if r.returncode != 0:
        print("  " + (r.stdout or "").strip().splitlines()[-1][:70])
        print("  ★ 这是一阶检查：测出来的不是「测试够不够强」，是「产出对不对」")
    return _out(r.returncode == 0,
                "evals 机械判定子集通过" if not lines else "", "")


# ---------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description="过程门：Lead 的工作要不要机械检查")
    ap.add_argument("--only", choices=["smoke", "single", "prov", "evals"])
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
              "prov": check_provenance,
              "evals": check_evals}
    order = [a.only] if a.only else ["smoke", "single", "prov", "evals"]
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
