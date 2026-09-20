"""计划 A 的 hook 探针：证明宿主真会调 Stop hook。计划 B 换成 gate_hook.py 做验戳。

只记日志、不拦任何东西：跑通了就必须 return 0。
禁止读 sys.stdin：本机它按 cp936 解码，含中文的 UTF-8 载荷在严格错误处理下
先抛 UnicodeDecodeError 再落盘（实测 exit=1、日志文件根本不生成），
在本机默认的 surrogateescape 下更阴——不崩，但记下的长度是乱码的字符数。
两种都把「钩子被调了但读崩了」伪装成「宿主没调钩子」，
而那正是整个插件方案的否决判据，不能含糊。
故读 stdin.buffer 拿裸字节，utf-8 + errors='replace' 只用来换字符数，日志真值是 raw_bytes。
记录先拼好再 open：open 之后到落盘之间只剩 I/O 自己会失败，
那种失败必须像失败（不吞异常），不能被一条空日志掩盖。
"""
import datetime
import json
import sys
from pathlib import Path


def main() -> int:
    raw = sys.stdin.buffer.read()
    payload = raw.decode('utf-8', errors='replace')
    record = json.dumps({'at': datetime.datetime.now().isoformat(),
                         'raw_bytes': len(raw),
                         'chars': len(payload)}, ensure_ascii=False)
    target = Path(__file__).resolve().parent / '.drux-hook-stop.log'
    with target.open('a', encoding='utf-8') as fh:
        fh.write(record + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
