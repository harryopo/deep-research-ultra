"""v6.84：过程门（preflight）自身的行为，以及它为什么必须存在。

## 为什么要做这个

本项目至今 1100+ 项测试**全是检查产出**（报告、账本、戳、文档数字）。
**对过程零检查** —— 这是 `docs/dev/v6.84-过程门与文献依据.md` 记的缺口。

那篇文档里还有一句更要紧的：**不做什么**。文献（ICLR 2024、2402.08115）
说 LLM 没有外部信号时无法可靠自我纠正，加自我验证**让性能变差**；
同质化陷阱（2507.06920）说同模型验证者与生成者有相同盲区。
所以这里只做**可机械判定**的检查，不加任何"让 agent 再审视一遍"的环节。

## 为什么必须有测试守着这道门

一道自己会坏的检查等于没有。下面的用例分别钉住三件事：

1. **它真的会红** —— 造一个坏脚本、一个重复定义、一个缺 provenance 的版本段，
   确认 preflight 报 FAIL。只会通过的检查等于没有检查。
2. **它的判据不是自说自话** —— `prov` 项必须真的去跑分析脚本的 `--check`，
   而不是只看文件存在。
3. **它不能越权** —— 不得拦住"gitignore 的草稿目录"，那是刻意的排除。

以及一条**元测试**：过程门自己曾经因为路径推错而第一次跑就报红
（`SKILL.parents[2]` 指到了 `<repo>/skills`）。那条经历写进了 preflight 的注释，
这里钉住路径确实指向仓库根——**一个"检查过程"的工具自己搞错路径，
比没有它更让人不信任**。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
REPO = S.parents[2]
PREFLIGHT = S / "preflight.py"


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(cwd or S), timeout=1800)


# ---------------------------------------------------------------------------
# 1) 路径：它自己不能找错地方
# ---------------------------------------------------------------------------

def test_preflight_repo_path_points_at_repo_root():
    """SKILL 往上是 skills/ → 仓库根。第一版写成 parents[2]，指到 `<repo>/skills` 了。

    这条不是洁癖——它**第一次跑就因为这个报红**，而报错信息是
    「找不到 CHANGELOG 的版本段」，指向的是数据问题、实际是路径问题。
    一个自己会找错路的检查工具，比没有它更让人不信任。
    """
    src = PREFLIGHT.read_text(encoding="utf-8")
    assert "REPO = SKILL.parents[1]" in src, \
        'REPO 必须指向仓库根（SKILL=<repo>/skills/deep-research-ultra）'
    assert (REPO / "CHANGELOG.md").exists(), \
        f'REPO 推错层：{REPO} 下没有 CHANGELOG.md'


def test_preflight_passes_on_clean_tree():
    """干净树上必须通过，且三项都要出现。"""
    r = _run()
    assert r.returncode == 0, f'过程门在干净树上红了：\n{(r.stdout or "")[-900:]}'
    out = r.stdout or ""
    for name in ("smoke", "single-source", "provenance"):
        assert name in out, f'少了一项检查：{name}'
    assert "只覆盖有机械判据的错误" in out, \
        '必须说清它的边界——「没想到要去查」那类它挡不住'


# ---------------------------------------------------------------------------
# 2) 它真的会红（只会通过的检查等于没有检查）
# ---------------------------------------------------------------------------

def test_smoke_check_actually_bites(tmp_path):
    """塞一个语法错的脚本，smoke 必须报红。

    判据来源是本轮 E 类错误（4 次，最高频）：中文引号提前闭合、缺 `import re`
    这类，全部表现为「脚本在真正该干活的那一刻崩」。所以这条不是假设性用例。
    """
    bad = S / "_v684_tmp_broken.py"
    bad.write_text("x = '未闭合字符串\n", encoding="utf-8")
    try:
        r = _run("--only", "smoke")
        assert r.returncode != 0, '塞了语法错的脚本，smoke 竟然过了'
        assert "FAIL" in (r.stdout or ""), r.stdout[-400:]
    finally:
        bad.unlink(missing_ok=True)
    r2 = _run("--only", "smoke")
    assert r2.returncode == 0, '清掉之后仍红——它没在看当前状态'


def test_single_source_check_actually_bites(tmp_path):
    """在第二个文件里定义同一张锚词表，single-source 必须报红。

    起因是 v6.83 的真实事故：分析脚本自写了一份锚词表、score.py 一份，
    两份看起来都合理，算出来的收益差一倍（+11.1 vs +5.3），
    直到把同一个测试同时挂在两份表上才暴露。
    """
    dup = S / "_v684_tmp_dup.py"
    dup.write_text("ANCHOR_HINTS = ('retrieval', 'kubernetes')\n", encoding="utf-8")
    try:
        r = _run("--only", "single")
        assert r.returncode != 0, '出现了第二处定义，single-source 竟然过了'
        assert "ANCHOR_HINTS" in (r.stdout or "") or "另有定义" in (r.stdout or "")
    finally:
        dup.unlink(missing_ok=True)


def test_provenance_check_actually_bites():
    """PROVENANCE 里挂一个不存在的版本，provenance 必须报红。

    这条对应"结论挂在一个别人跑不了的草稿上"——v6.83 的真实状态就是
    样本夹具进了版本控制、产出脚本躺在 gitignore 里。
    """
    src = PREFLIGHT.read_text(encoding="utf-8")
    assert '"v6.83.0"' in src
    # 把它改成不存在的版本，确认判据真的在查存在性
    tmp = S / "_v684_tmp_pf.py"
    tmp.write_text(src.replace('"v6.83.0"', '"v0.99.0-not-exist"', 1), encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(tmp), "--only", "prov"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           cwd=str(S), timeout=600)
        assert r.returncode != 0, '版本段不存在却过了——判据没在查'
        assert "CHANGELOG" in (r.stdout or ""), r.stdout[-400:]
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 3) 它必须真的去跑分析脚本，而不是只看文件存在
# ---------------------------------------------------------------------------

def test_provenance_actually_executes_the_analysis_script():
    """`prov` 必须调 `analysis/relevance.py --check`，不是只看文件在不在。

    否则"脚本存在但已经跑不通了"这种情况会静默通过——而那正是
    这道门要抓的东西（结论挂着一个跑不起来的复算脚本上）。
    """
    src = PREFLIGHT.read_text(encoding="utf-8")
    assert '"--check"' in src, 'provenance 项没有调 --check'
    assert 'relevance.py' in src or "analysis" in src
    # 实跑时它必须真的执行（上面 test_preflight_passes_on_clean_tree 已覆盖，
    # 这里补一条：把夹具改坏，确认 --check 会红）
    fx = S / "tests" / "fixtures" / "relevance_samples.json"
    backup = fx.read_bytes()
    try:
        import json
        rows = json.loads(backup.decode("utf-8"))
        for r in rows:                       # 把所有切题的 relevance 压到 0
            if r.get("manual_label") == "on":
                r["scores"]["relevance"] = 0.0
        fx.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        r = _run("--only", "prov")
        assert r.returncode != 0, '把夹具改坏了，--check 竟然过了'
    finally:
        fx.write_bytes(backup)


# ---------------------------------------------------------------------------
# 4) 它不得越权
# ---------------------------------------------------------------------------

def test_preflight_skips_gitignored_scratch_dir():
    """`.research/` 这类点开头的草稿目录必须被排除。

    判据是 gitignore：它们不进包，所以过程门也不该管它们——
    否则往草稿目录扔个写坏一半的脚本就会让全量测试变红
    （v6.82 那次传输层测试已经踩过这个，被迫改成跳过点开头目录）。
    """
    scratch = S / ".research"
    scratch.mkdir(exist_ok=True)
    bad = scratch / "_v684_tmp_broken.py"
    bad.write_text("x = '未闭合字符串\n", encoding="utf-8")
    try:
        r = _run()
        assert r.returncode == 0, (
            f'草稿目录里的坏文件让过程门红了：\n{(r.stdout or "")[-500:]}')
    finally:
        bad.unlink(missing_ok=True)


def test_preflight_does_not_claim_to_cover_everything():
    """它必须自己说清边界。

    一道声称能挡住所有过程错误的门是危险的——A 类错误（未验证就断言）里
    有一半是"我根本没想到要去查"，机械门挡不住。把这句写进输出，
    是为了让读的人不产生错误的安全感。
    """
    src = PREFLIGHT.read_text(encoding="utf-8")
    assert "挡不住" in src or "只做能机械判定的" in src, \
        'preflight 的文档/输出里没有说清它挡不住什么'
    assert "不做" in src or "明确不做" in src, \
        '必须明写「不做自我审查」并给理由——那是文献的核心结论'
