"""v6.72：账本参数的两种叫法收敛（零破坏性）+ 一条彻底误导的错误消息。

## 先把问题说准——"三不统一"是只数了表象

| 脚本 | 账本参数 | 实际收的东西 |
|---|---|---|
| research / validate_report / claim_support / verify_quotes | `--ledger` | 账本目录 |
| ledger.py | `--session` | **账本目录**（名字与内容不符） |
| guard.py | `--session` | 会话目录（名副其实） |
| skeleton.py | 位置参数 `args[0]` | 账本目录 |

`--ledger`（账本目录）与 `--session`（会话目录）是**两个真概念**，guard 要的是后者；
但 `ledger.py` 的 `--session` 收的其实是账本目录（`ResearchLedger.root` 直接等于它，
`entries_path = root / 'ledger.jsonl'`）——名不副实；skeleton.py 走位置参数，
三者凑成三副面孔。

## 最误导的一条

    $ python skeleton.py --ledger /path -o out.md
    ❌ 账本不存在: --ledger\\ledger.jsonl（--session 应指向 ledger 目录；先执行 init...）

① `--ledger` 被当成**目录名**拼进路径，看着像"账本文件丢了"，真实原因只是参数形式不对；
② 它建议去用 `--session` —— 而 **skeleton.py 根本不收 `--session`**，照做只会再错一次。

## 为什么是收敛而不是改名

`--session` 在 SKILL.md 的派单模板与 MCP 调用里出现很多次，直接改名会打断现用法。
所以：加别名（零破坏）、旧写法继续有效、改消息。

**本组测试最看重的是旧写法照跑**——破坏旧用法是最容易犯、又最容易被自己漏掉的回归。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
S = Path(__file__).resolve().parents[1]
SKELETON = S / 'skeleton.py'
LEDGER = S / 'ledger.py'
ENTRY = ('research.py', 'validate_report.py', 'skeleton.py', 'ledger.py',
         'claim_support.py', 'verify_quotes.py', 'guard.py', 'probe.py',
         'env_check.py', 'score.py', 'panel.py', 'doc_pin_audit.py')


def run(script, *args):
    r = subprocess.run([sys.executable, str(S / script), *args],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout + r.stderr).strip()


def _led(tmp_path, name='ledger'):
    L = tmp_path / name
    L.mkdir(parents=True, exist_ok=True)
    run('ledger.py', 'add-claim', '--session', str(L), '--text', '一条 claim',
        '--id', 'c1', '--topic', 'T')
    run('ledger.py', 'add-source', '--session', str(L), '--claim-id', 'c1',
        '--url', 'https://example.org/a', '--title', 'T', '--craap', '70')
    return L


# ---------------------------------------------------------------------------
# 旧写法必须照跑
# ---------------------------------------------------------------------------

def test_positional_form_still_works(tmp_path):
    L = _led(tmp_path)
    code, out = run('skeleton.py', str(L), '-o', str(tmp_path / 'a.md'))
    assert code == 0, f'位置参数被改坏——这是文档里教了两处的写法：{out[:200]}'


def test_session_flag_still_works_on_ledger_py(tmp_path):
    """`--session` 在 SKILL.md 派单模板与 MCP 调用里大量出现，不能收走。"""
    L = _led(tmp_path)
    code, out = run('ledger.py', 'status', '--session', str(L))
    assert code == 0, f'旧名 --session 被改坏：{out[:200]}'


# ---------------------------------------------------------------------------
# 新写法
# ---------------------------------------------------------------------------

def test_ledger_flag_now_accepted_and_produces_identical_output(tmp_path):
    """不只是"能用"——两种写法必须产出**完全相同**的文件。"""
    L = _led(tmp_path)
    code_a, out_a = run('skeleton.py', str(L), '-o', str(tmp_path / 'pos.md'))
    code_b, out_b = run('skeleton.py', '--ledger', str(L), '-o', str(tmp_path / 'flag.md'))
    assert code_a == 0 and code_b == 0, f'位置={out_a[:120]} / --ledger={out_b[:120]}'
    a = (tmp_path / 'pos.md').read_text(encoding='utf-8')
    b = (tmp_path / 'flag.md').read_text(encoding='utf-8')
    assert a == b, '两种写法产出了不同的骨架——加别名不该改变任何输出'


def test_ledger_flag_on_ledger_py(tmp_path):
    L = _led(tmp_path)
    code, out = run('ledger.py', 'status', '--ledger', str(L))
    assert code == 0, f'ledger.py --ledger 不可用：{out[:200]}'


# ---------------------------------------------------------------------------
# 错误信息不许再骗人
# ---------------------------------------------------------------------------

def test_unknown_flag_gets_usage_not_a_traceback(tmp_path):
    """旧版把 `--ledger` 当目录名拼路径，报"账本不存在"；再往前还会抛裸 traceback。

    traceback 那条是 v6.72 自己引入的：补丁脚本里用 `NL = chr(10)` 占位，
    占位符被原样写进目标文件，目标文件里没有这个变量 → NameError。
    所以这一条钉的不只是"要有用法提示"，还包括"不许崩"。
    """
    code, out = run('skeleton.py', '--ledgerdir', str(tmp_path))
    assert 'Traceback' not in out, f'抛了裸 traceback：{out[-300:]}'
    assert code == 2, f'exit={code}：{out[:200]}'
    assert '不是本脚本的用法' in out, f'没给出用法：{out[:200]}'


def test_error_never_concatenates_a_flag_into_a_path(tmp_path):
    """`--ledger` 被拼成 `--ledger\\ledger.jsonl` 会让人以为账本文件丢了。"""
    code, out = run('skeleton.py', '--ledgerdir', str(tmp_path))
    assert '--ledgerdir' not in re.sub(r'用法错误：[^\n]*', '', out), \
        f'flag 名被拼进了路径类文本：{out[:250]}'
    assert not re.search(r'--ledger[\\/]', out), f'flag 名被拼成了路径：{out[:250]}'


def test_missing_flag_value_is_a_usage_error(tmp_path):
    code, out = run('skeleton.py', '--ledger')
    assert code == 2, f'exit={code}：{out[:160]}'
    assert '缺' in out or '后面要跟' in out, out[:200]


def test_ledger_missing_message_does_not_hardcode_one_clis_flag(tmp_path):
    """ResearchLedger 被 6 个脚本共用，异常里硬写 `--session` 会把人引到用不了的写法。"""
    src = LEDGER.read_text(encoding='utf-8')
    i = src.find('账本不存在')
    assert i != -1, '找不到"账本不存在"这条消息'
    seg = src[i:i + 900]
    assert '--session 应指向' not in seg, (
        '消息里仍在硬编码 --session——这个类被 6 个脚本共用，'
        '各家参数名不同，硬写一个会把人引到用不了的写法上')
    assert 'init --ledger' in seg, '应给出真正能用的建账本命令'


def test_no_placeholder_leaked_into_any_entry_script():
    """补丁脚本里的内部占位符不能流进目标文件。

    v6.72 自己踩过：用 `NL = chr(10)` 拼补丁，被原样写进 skeleton.py 的 f-string，
    目标文件里没有 NL → NameError → traceback。语法能过、只有运行才炸，
    所以静态检查抓不到，只能钉住"这些文件里不该有裸占位符"。
    """
    bad = re.compile(r'\{(NL|Q|DQ|ESC)\}')
    offenders = []
    for name in ENTRY:
        p = S / name
        if not p.exists():
            continue
        hit = bad.search(p.read_text(encoding='utf-8', errors='replace'))
        if hit:
            offenders.append(f'{name}: {hit.group(0)}')
    assert not offenders, f'目标脚本里残留了补丁脚本的占位符：{offenders}'


def test_every_entry_script_survives_a_bare_invocation(tmp_path):
    """兜底：所有对外脚本被单独调用时不得抛未捕获异常。

    上一条只能抓特定占位符，这条抓的是整类——包括下一批我自己写错的。
    """
    broken = []
    for name in ENTRY:
        p = S / name
        if not p.exists():
            continue
        r = subprocess.run([sys.executable, str(p), '--help'],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=60, cwd=str(S))
        blob = (r.stdout + r.stderr)
        if 'Traceback (most recent call last)' in blob:
            broken.append(f'{name} --help')
    assert not broken, f'这些脚本 --help 就崩：{broken}'