"""计划 A 的 hook 探针：证明宿主真会调 Stop hook。计划 B 换成 gate_hook.py 做验戳。

只记日志、不拦任何东西：跑通了就必须 return 0。
禁止按文本方式读 sys.stdin：本机它按 cp936 解码，含中文的 UTF-8 载荷有两种坏法，后果不一样。
一是严格错误处理（宿主设了 PYTHONIOENCODING 之类）：读载荷当场抛 UnicodeDecodeError，
日志文件连创建都没有，于是「钩子被调了但读崩了」和「宿主没调钩子」完全同形（实测 exit=1、无文件）——
那正是整个插件方案的否决判据，不能含糊。
二是本机默认的 surrogateescape：不崩、日志行照样落盘，坏的只是数字，
记下的是乱码的字符数（75 字节的载荷记成 66），不是字节数。
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
    here = Path(__file__).resolve().parent
    # 只记字节数学不到载荷的字段名，而 gate_hook 要靠载荷定位工作区。
    # 最新一份原样落盘（覆盖即可：要的是形态，不是样本量）。
    (here / '.drux-hook-stop.raw').write_bytes(raw)
    target = here / '.drux-hook-stop.log'
    with target.open('a', encoding='utf-8') as fh:
        fh.write(record + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
