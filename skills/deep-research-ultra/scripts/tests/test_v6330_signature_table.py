"""v6.33.0 回归：§14.3 那张签名表必须覆盖 ledger.py 的每个子命令。

SKILL.md §14.3 的注释原话是「证据账本（写命令签名照抄，不必再跑 --help）」，
冷启动那节也写着"命令照抄即可（十四节的签名表已列全）"。所以"在 SKILL.md 里出现过"
不算数——**得出现在这张照抄用的签名块里**才算 documented。

实测漂移：v6.21 加的 `link-identity` 与 v6.32 加的 `content-identity` 都只在正文散文里
出现过，签名块里没有。照着签名块抄命令的 Lead 不知道有这两条通道，
于是"跨标识符/跨主机判同"这条升级路等于不存在（claim 只能停在 pending）。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SKILL = Path(__file__).resolve().parents[2] / 'SKILL.md'
SCRIPTS_DIR = Path(__file__).resolve().parents[1]


def _signature_block() -> str:
    """取 §14.3 里那段 ledger.py 的 bash 签名块。"""
    text = SKILL.read_text(encoding='utf-8')
    m = re.search(r'### 14\.3.*?```bash(.*?)```', text, re.S)
    assert m, '找不到 §14.3 的签名块'
    start = m.group(1).index('ledger.py')
    block = m.group(1)[start:]
    nxt = re.search(r'### ', block)
    return block[:nxt.start()] if nxt else block


def _scripts_with_subcommands() -> dict:
    """扫全部 CLI 脚本，取各自的子命令清单（不止 ledger——同类缺陷要一次横扫）。"""
    out = {}
    for path in sorted(SCRIPTS_DIR.glob('*.py')):
        cmds = sorted(set(re.findall(r"cmd == '([a-z-]+)'",
                                     path.read_text(encoding='utf-8', errors='replace'))))
        if cmds:
            out[path.name] = cmds
    return out


def test_每个子命令都在签名块里():
    block = _signature_block()
    table = _scripts_with_subcommands()
    assert table, '一个带子命令的 CLI 都没扫到——扫描口径坏了，这条断言就会空转'
    missing = [f'{name} {cmd}' for name, cmds in table.items()
               for cmd in cmds if f'{name}" {cmd}' not in block]
    assert not missing, (
        f'§14.3 签名块缺 {missing}——这张表写着"照抄即可，不必再跑 --help"，'
        f'漏一条就等于这条能力不存在')


def test_签名块不为空且确实覆盖多数命令():
    """对照面：断言不许因为"块没解析到"而空转通过。"""
    block = _signature_block()
    table = _scripts_with_subcommands()
    total = sum(len(cmds) for cmds in table.values())
    hit = sum(1 for name, cmds in table.items()
              for c in cmds if f'{name}" {c}' in block)
    assert hit >= total - 1, f'签名块只覆盖 {hit}/{total} 条，解析或文档出了问题'
