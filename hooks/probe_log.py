"""计划 A 的 hook 探针：证明宿主真会调 Stop hook。计划 B 换成 gate_hook.py 做验戳。

只记日志，不拦任何东西：正常路径必须 return 0。
读 stdin.buffer 拿裸字节，不用 sys.stdin.read()：宿主在本机把 stdin 解成 cp936，
含中文的 Stop 载荷会先抛 UnicodeDecodeError 再写日志（实测 exit=1 且日志文件根本不生成），
下一任务会把「钩子跑了但读崩了」误读成「宿主没调钩子」——那是整个插件方案的否决判据，不能含糊。
解码只用 errors='replace' 换取字符数，日志的真值是 raw_bytes（裸字节数）。
写入前先把整条记录拼好：这样 open 之后到落盘之间只剩 I/O 本身会失败，
而那种失败必须像失败（不吞异常），不能被一条空日志掩盖。
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
