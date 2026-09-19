"""console.py — CLI 输出编码统一入口。

Windows 控制台默认代码页 936（GBK）：打印 ✅/❌ 会抛 UnicodeEncodeError，
中文输出也会以 GBK 字节落管道（Agent 侧读到乱码）。所有 CLI 入口在 main()
之前调用 force_utf8()，不依赖调用方设置 PYTHONIOENCODING/PYTHONUTF8。
"""

from __future__ import annotations

import sys


def force_utf8() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
