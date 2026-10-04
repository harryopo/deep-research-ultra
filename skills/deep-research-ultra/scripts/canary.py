"""canary.py — L4 Canary 哨兵 [注入防护方案 S.5/L4，v6.53 新增]

无权限宿主上唯一能做出**实证检测**的注入防线：
会话携带一个假凭据（canary token，形态 DRUX_CANARY_<hex>，它不对应任何真实资源）。
正常的调研永远不会把它写进任何文件；会话结束时如果它在 canary.txt 以外的任何地方
出现——报告正文、账本、分片、raw、scratch、任何写盘内容——即证明"注入已生效并
正在改变行为或外传"，按注入事故处置（〇.五：引用上报 + 留痕 + 停止交付）。

为什么可观测性是防线：挡不住注入文本进入上下文（L2 只是收窄），但可以确定性地
检测它**有没有造成后果**。这是论文里最容易量化、最有说服力的一个指标。

用法:
  python canary.py init --session <会话目录>              # 生成 canary 并打印令牌（派单用）
  python canary.py token --session <会话目录>             # 只读出已有令牌
  python canary.py check --session <会话目录> [--report 报告.md] [--extra 文件]...

检查范围：--session 目录递归全部文件（canary.txt 本身豁免——令牌就住在那），
外加 --report 与 --extra 指定的任意文件。**命中即非零退出**，Lead 必须停止交付。

退出码: 0 未外泄；1 已外泄（列出 文件:行号）；2 参数/IO 错误
（含"canary.txt 不存在"——哨兵没种下，"没种"不等于"没发生"）。
"""
import argparse
import io
import os
import secrets
import sys
import time
from pathlib import Path

CANARY_FILE = 'canary.txt'
PREFIX = 'DRUX_CANARY_'


def _token_path(session: str) -> Path:
    return Path(session) / CANARY_FILE


def _read_token(session: str) -> str:
    p = _token_path(session)
    if not p.is_file():
        return ''
    first = p.read_text(encoding='utf-8', errors='replace').splitlines()[:1]
    return first[0].strip() if first and first[0].strip().startswith(PREFIX) else ''


def cmd_init(session: str) -> int:
    p = _token_path(session)
    if p.is_file():
        token = _read_token(session)
        if token:
            print(f'canary 已存在：{token}（不重复生成，避免旧会话的哨兵失效）')
            return 0
    token = PREFIX + secrets.token_hex(4).upper()
    Path(session).mkdir(parents=True, exist_ok=True)
    p.write_text(
        f'{token}\n'
        f'created_at: {time.strftime("%Y-%m-%d %H:%M:%S")}\n'
        f'说明：这是 L4 哨兵假凭据，不对应任何真实资源。除本文件外，'
        f'它出现在任何文件里都是注入生效的实证（canary.py check 判定）。\n',
        encoding='utf-8')
    print(f'canary 已种下：{token}')
    print(f'令牌文件：{p}')
    print('派单时可把令牌告知子 Agent 并声明它是诱饵；它出现在 canary.txt 以外的'
          '任何文件都会被 check 判为注入外泄。')
    return 0


def cmd_token(session: str) -> int:
    token = _read_token(session)
    if not token:
        print(f'⛔ {CANARY_FILE} 不存在或不含 {PREFIX}* 令牌：先 init', file=sys.stderr)
        return 2
    print(token)
    return 0


def cmd_check(session: str, report: str = '', extra=None) -> int:
    token = _read_token(session)
    if not token:
        print(f'⛔ {CANARY_FILE} 不存在：哨兵没种下，无从检查——'
              f'"没种"不等于"没发生"（先 canary.py init）', file=sys.stderr)
        return 2
    tb = token.encode('utf-8')
    targets: list = []
    root = Path(session)
    for dirpath, _dirs, names in os.walk(root):
        for n in sorted(names):
            if n == CANARY_FILE:
                continue
            targets.append(Path(dirpath) / n)
    if report:
        targets.append(Path(report))
    for p in (extra or []):
        targets.append(Path(p))
    hits = []
    scanned = 0
    for p in targets:
        if not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        scanned += 1
        if tb in data:
            try:
                text = data.decode('utf-8', errors='replace')
                line_no = next(i for i, l in enumerate(text.splitlines(), 1)
                               if token in l)
            except (UnicodeDecodeError, StopIteration):
                line_no = 0
            hits.append(f'{p}:{line_no}')
    if hits:
        print(f'⛔ canary 外泄 {len(hits)} 处——注入已生效并改变行为或外传的实证：',
              file=sys.stderr)
        for h in hits:
            print(f'  {h}', file=sys.stderr)
        print('处置：停止交付；按〇.五引用上报 + 留痕；排查命中文件并告知用户。',
              file=sys.stderr)
        return 1
    print(f'✅ canary 未外泄（扫描 {scanned} 个文件，令牌只在 {CANARY_FILE}）')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='canary.py', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('init', 'token', 'check'):
        sp = sub.add_parser(name)
        sp.add_argument('--session', required=True, help='会话目录')
        if name == 'check':
            sp.add_argument('--report', default='', help='报告 md 一并扫描')
            sp.add_argument('--extra', action='append', default=[],
                            help='额外要扫的文件（可重复）')
    a = ap.parse_args(argv)
    # init 允许目录还不存在（它负责创建）；token/check 才要求已有会话
    if a.cmd != 'init' and not os.path.isdir(a.session):
        print(f'⛔ 会话目录不存在：{a.session}', file=sys.stderr)
        return 2
    if a.cmd == 'init':
        return cmd_init(a.session)
    if a.cmd == 'token':
        return cmd_token(a.session)
    return cmd_check(a.session, getattr(a, 'report', ''), getattr(a, 'extra', None))


if __name__ == '__main__':
    sys.exit(main())
