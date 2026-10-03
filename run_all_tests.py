#!/usr/bin/env python3
"""全仓测试入口：内核（scripts/tests）与插件壳（tests）两套一起跑，汇总真实总数。

背景：v6.51 收口时 REQUIRED_SECTIONS 扩容只改了内核测试的 fixture，根 tests/
的盖戳测试挂了 3 项——单跑任一套都是绿的，"绿"被两个测试根瓜分了。
此后 CHANGELOG 写的「全量 N 项」一律以本脚本的输出为准：
它报的是**通过数**，不是收集数（test_landing_page_facts 钉的是收集数，两者互补）。
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
SUITES = [
    ('内核 scripts/', REPO / 'skills' / 'deep-research-ultra' / 'scripts'),
    ('插件壳 tests/', REPO / 'tests'),
]


def parse_summary(out: str):
    """从 pytest -q 末尾摘要行取 (passed, failed)。两种顺序都要认：
    '885 passed in 86.4s' 与 '3 failed, 47 passed in 7.1s'。
    findall 给的是 (数字, 词)，按词归位——直接 dict() 会建成 {数字: 词}。"""
    counts = {'passed': 0, 'failed': 0}
    for num, word in re.findall(r'(\d+) (passed|failed)', out):
        counts[word] = int(num)
    return counts['passed'], counts['failed']


def main() -> int:
    total_passed = total_failed = 0
    parsed_all = True
    for label, cwd in SUITES:
        proc = subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', '--tb=line'],
            cwd=str(cwd), capture_output=True, encoding='utf-8', errors='replace')
        out = (proc.stdout or '') + (proc.stderr or '')
        passed, failed = parse_summary(out)
        if passed == 0 and failed == 0:
            parsed_all = False
            print(f'!! {label}: 解析不到 pytest 摘要（退出码 {proc.returncode}）')
            print(out[-600:])
            continue
        total_passed += passed
        total_failed += failed
        mark = 'OK' if failed == 0 else '!!'
        print(f'{mark} {label}: {passed} passed, {failed} failed')
    print(f'—— 全仓合计：{total_passed} passed, {total_failed} failed ——')
    return 0 if parsed_all and total_failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
