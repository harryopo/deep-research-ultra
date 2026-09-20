"""计划 A 的 hook 探针：证明宿主真会调 Stop hook。计划 B 换成 gate_hook.py 做验戳。"""
import datetime
import json
import sys
from pathlib import Path


def main() -> int:
    payload = sys.stdin.read()
    target = Path(__file__).resolve().parent / '.drux-hook-stop.log'
    with target.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps({'at': datetime.datetime.now().isoformat(),
                             'bytes': len(payload)}, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
