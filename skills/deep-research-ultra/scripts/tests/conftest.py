"""测试运行器自身的输出编码。

scripts/*.py 各自强制了 UTF-8 输出，但 `python -m pytest tests/`（README 里那条命令）
在 Windows 上仍以 cp936 写 stdout——断言消息里的中文全变成乱码，红字读不出来就等于
没有失败信息。这里补齐最后一道未强制的输出通道。
"""

import sys


def pytest_configure(config):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
