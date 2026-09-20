"""GBK 控制台下的 CLI 冒烟测试（Windows 默认代码页 936）。

真实故障：Phase 0 环境门 `research.py --env-check` 与 `--list` 在 Windows
控制台打印 ✅/❌ 时抛 UnicodeEncodeError 直接 exit 1，调研第一步就走不通。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]

GBK_ENV = {**os.environ, "PYTHONIOENCODING": "gbk"}


@pytest.mark.parametrize("argv,expect", [
    (["research.py", "--list"], "引擎"),
    (["research.py", "--env-check", "--env-profile", "minimal", "--no-net"], "就绪"),
    (["tier.py", "https://www.gov.cn/x"], "官方"),
    (["panel.py", "perspectives"], "domain_expert"),
])
def test_cli_survives_gbk_console(argv, expect):
    """GBK 控制台：既不能崩，中文输出也必须以 UTF-8 落到管道。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / argv[0]), *argv[1:]],
        capture_output=True,
        cwd=str(SCRIPTS),
        env=GBK_ENV,
        timeout=120,
    )
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0, f"{argv} exit={proc.returncode}\n{stderr[-800:]}"
    assert "UnicodeEncodeError" not in stderr
    combined = proc.stdout.decode("utf-8", errors="replace") + stderr
    assert expect in combined, f"输出非 UTF-8 可读文本，中文被 GBK 编码成乱码"
