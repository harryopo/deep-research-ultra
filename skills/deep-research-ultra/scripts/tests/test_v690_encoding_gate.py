"""仓库里不许有 U+FFFD（编码坏字符）。

## 为什么它值得一条测试

我每轮都在 PowerShell 里手写一遍这个检查，而**我已经用一种方式骗过自己至少一次**：

```powershell
Select-String -Path A,B -Pattern "\uFFFD" | ForEach-Object { "坏字符 L" + $_.LineNumber }
Write-Output "（无输出＝干净）"      # ← 无条件打印
```

它报了 `坏字符 L94`，紧接着打印"干净"，而我**照着"干净"就 commit 了**，
把三个 U+FFFD 带进了仓库：一个汉字被写成了三个替换字符
（下面 `test_detector_catches_a_planted_bad_char` 里就是同款，
只不过那里是故意植入的）。

人肉检查会失效，所以变成测试。这条测试自己也要能被验证 ——
见 `test_detector_catches_a_planted_bad_char`。

## 为什么扫的是 git 跟踪的文件

`.research/` 下的本地草稿里有历史遗留的坏字符，而它们**没被跟踪** ——
不排除掉的话这条测试一开始就是红的，红久了就没人看了。
要发布的东西 = 被跟踪的东西。

## 为什么用 `\\ufffd` 转义而不是直接写那个字符

直接写 U+FFFD 会让**这个文件自己**带一个坏字符，那就永远红。
转义写法是纯 ASCII，安全。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# parents 链：file → tests → scripts → <skill> → skills → <repo root>
# ⚠️ 我第一版写的是 parents[3]（= skills/），于是 `git ls-files` 在子目录里跑，
# 只列出 skills/** —— 主门那条测试就"扫了子集然后全绿"。
# 是 test_tracked_file_list_is_real_and_actually_scanned 抓出来的：
# 关键文件不在列表里。**静默的部分失效比报错更坏。**
REPO = Path(__file__).resolve().parents[4]
BAD = chr(0xFFFD)   # 用 chr() 而不是字面量或 "\ufffd" 转义
# —— 写入路径会把转义序列还原成字符本身，那正是本项目 U+FFFD 的来源
TEXT_SUFFIXES = {".py", ".md", ".html", ".json", ".txt", ".yml", ".yaml", ".toml", ".cfg"}
SKIP_DIRS = {".git", "__pycache__", ".research", "node_modules", ".pytest_cache"}


def _tracked_files() -> list[Path]:
    """被 git 跟踪的文本文件。git 不可用时退化成走文件系统。"""
    try:
        r = subprocess.run(
            ["git", "ls-files", "-z"], cwd=str(REPO),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        if r.returncode == 0 and r.stdout:
            names = [n for n in r.stdout.split("\0") if n]
            out = []
            for n in names:
                p = REPO / n
                if p.suffix in TEXT_SUFFIXES and p.is_file():
                    out.append(p)
            if out:
                return out
    except (OSError, subprocess.SubprocessError):
        pass

    out = []
    for p in REPO.rglob("*"):
        if not p.is_file() or p.suffix not in TEXT_SUFFIXES:
            continue
        if SKIP_DIRS & set(p.relative_to(REPO).parts):
            continue
        out.append(p)
    return out


def _scan(text: str) -> list[tuple[int, str]]:
    """返回 [(行号, 该行)]，每个含 U+FFFD 的行一条。"""
    if BAD not in text:
        return []
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if BAD in line:
            hits.append((i, line.strip()[:70]))
    return hits


def test_no_replacement_char_in_tracked_files():
    """被跟踪的文本文件里不许出现 U+FFFD。"""
    bad: list[str] = []
    for p in _tracked_files():
        try:
            text = p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue          # 本来就不是 UTF-8 的，跳过（不是本条要管的）
        for ln, ctx in _scan(text):
            rel = p.relative_to(REPO).as_posix()
            bad.append(f"{rel}:{ln}: {ctx}")
    assert not bad, (
        "仓库里有编码坏字符（U+FFFD）。"
        "通常是编辑工具写入时把一个汉字压成了替换字符 —— "
        "看着像对的，读出来才发现。\n  " + "\n  ".join(bad)
    )


def test_detector_catches_a_planted_bad_char():
    """**检测器本身要能抓到东西**，否则上面那条是空转。

    这就是本项目反复吃亏的那条：造完就信。
    """
    planted = "    # 这是三个是边界实跑里\n" + "    # " + BAD + "路时效性调研\n"
    hits = _scan(planted)
    assert len(hits) == 1, f"植入 1 个坏字符却只扫出 {len(hits)} 处 —— 检测器失灵了"
    assert hits[0][0] == 2, f"行号报成 {hits[0][0]}，应是 2"
    assert BAD in hits[0][1]


def test_detector_stays_quiet_on_clean_text():
    """反向对照：干净文本必须零命中（否则就是无差别报警）。"""
    clean = "    # 三个是边界实跑里 zero 那一类\n    assert '这三个' in s\n"
    assert _scan(clean) == [], "干净文本被误报了 —— 检测器在无差别报警"
    assert _scan("") == []


def test_skipped_dirs_are_not_scanned():
    """`.research/` 这类本地草稿必须被排除，否则测试一开始就是红的。"""
    assert ".research" in SKIP_DIRS
    files = _tracked_files()
    leaked = [p for p in files if ".research" in p.relative_to(REPO).parts]
    assert not leaked, f"跟踪文件里混进了 .research 草稿：{leaked[:3]}"


def test_this_file_itself_is_clean():
    """本文件用 `\\ufffd` 转义而不是直接写坏字符 —— 自己得先干净。"""
    raw = (Path(__file__).read_bytes().decode("utf-8"))
    assert BAD not in raw, "检测器文件自己带了 U+FFFD —— 那样它会永远红"
    assert raw.count("\\ufffd") >= 1, (
        "本文件的说明里写了「用 \\ufffd 转义」，但代码里并没有出现这个转义 —— "
        "说明文档与实现脱节了")


def test_tracked_file_list_is_real_and_actually_scanned():
    """**整条链路**要通：`git ls-files` 真的列出了会被发布的东西。

    只测 `_scan` 是不够的 —— 如果 `_tracked_files()` 返回空列表，
    主门那条测试就是"扫描了 0 个文件然后全绿"，属于静默失效
    （和 v6.86 那个 `prov` 正则永远返回空是同一类）。
    """
    files = _tracked_files()
    assert files, (
        "_tracked_files() 返回空 —— 主门那条测试会变成"
        "「扫了 0 个文件然后全绿」，是静默失效")

    names = {p.relative_to(REPO).as_posix() for p in files}
    # 必须包含几个「如果坏了就真的会流出去」的入口
    must = [
        "skills/deep-research-ultra/scripts/score.py",
        "skills/deep-research-ultra/SKILL.md",
    ]
    missing = [m for m in must if m not in names]
    assert not missing, f"跟踪列表里没有关键文件：{missing}"

    # 端到端：把一个带坏字符的副本喂给主门用的那条路径
    sample = REPO / "skills/deep-research-ultra/scripts/score.py"
    text = sample.read_bytes().decode("utf-8")
    assert _scan(text) == [], "score.py 当前就是干净的（顺便复核一遍）"
    hits = _scan(text + "\n# " + chr(0xFFFD) + "\n")
    assert len(hits) == 1, "把坏字符拼进真实文件的内容后，端到端扫描没抓到"
