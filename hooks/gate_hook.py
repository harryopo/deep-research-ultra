"""Stop 钩子：报告自称"已交付/过了校验门"，机器验戳却不过 → 不许收工。

为什么要有这个钩子：防伪戳（v6.11）已经能判真伪，但判完只是打印一行字，
Lead 不看照样能宣称交付。钩子把"看没看"变成"能不能停下"。

载荷字段取自本机抓到的真实 Stop 载荷（hooks/.drux-hook-stop.raw）：
cwd / stop_hook_active / last_assistant_message。退出码按宿主已确证的约定：
0 = 放行，2 + stderr = 拦下并把原因交给 Agent。

三条不许越的线：
- 只读文件 + 验戳，预算 0.5s；超预算一律放行（钩子把会话卡住比放过假交付更糟）
- 载荷坏了/自己崩了 → 放行并说明。那是宿主或我们的故障，不该由本轮交付背锅
- 不回显报告正文；stderr 只说"哪条不成立 + 怎么修"
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'deep-research-ultra' / 'scripts'

BUDGET = 0.5
# 「交付」这个词在无关对话里也出现，但本钩子只在 cwd 下有 .research 会话目录时才判，
# 命中面已经窄到"这个目录确实是我们调研产出的地方"。
CLAIM_RE = re.compile(r'(交付|验收通过|校验通过|校验门|已通过校验|全部通过|passed|verified)')
STAMP_RE = re.compile(r'^<!--\s*drux:validated\b.*-->\s*$', re.M)
DRAFT_RE = re.compile(r'^\s*DRAFT\b', re.I)


def _allow(why: str = '') -> int:
    if why:
        sys.stderr.buffer.write(f'[drux gate_hook] 放行：{why}\n'.encode('utf-8', 'replace'))
    return 0


def _block(report: Path, reason: str) -> int:
    hint = (f'[drux gate_hook] 拦住了一次自称完成但没过机器门的交付\n'
            f'  报告：{report.as_posix()}\n'
            f'  原因：{reason}\n'
            f'  怎么修：补证据后重跑 validate_report.py --report <路径> --stamp'
            f'（盖出带 drux:validated 的戳），或把该结论显式降级为待补证据、'
            f'或在报告首行写 DRAFT: 表明本轮未完成\n')
    sys.stderr.buffer.write(hint.encode('utf-8', 'replace'))
    return 2


def _started_at(sess_dir: Path) -> float:
    """会话起点：report.md 比它早就是上一次的遗留，不该让本轮收不了工。"""
    try:
        info = json.loads((sess_dir / 'session.json').read_text(encoding='utf-8'))
        return datetime.fromisoformat(str(info.get('started_at', ''))).timestamp()
    except Exception:
        return (sess_dir / 'session.json').stat().st_mtime


def _sessions(cwd: Path):
    for sess in sorted((cwd / '.research').glob('*/session.json')):
        yield sess.parent


def _verdict(md: str, sess: Path):
    sys.path.insert(0, str(SCRIPTS))
    from validate_report import verify_stamp
    return verify_stamp(md, str(sess))


def main() -> int:
    deadline = time.monotonic() + BUDGET
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        return _allow()
    try:
        payload = json.loads(raw.decode('utf-8', errors='replace'))
        cwd = Path(str(payload.get('cwd') or '')).expanduser()
    except Exception as exc:
        return _allow(f'载荷解析失败（{type(exc).__name__}），不替宿主的故障买单')
    if not isinstance(payload, dict) or not str(payload.get('cwd') or '').strip():
        return _allow('载荷里没有 cwd，无法定位工作区')
    if payload.get('stop_hook_active'):
        return _allow('上一次拦截后已经改过一轮，再拦就是死循环')
    if not (cwd / '.research').is_dir():
        return _allow()

    claim_text = str(payload.get('last_assistant_message') or '')
    for sess in _sessions(cwd):
        if time.monotonic() > deadline:
            return _allow(f'超出 {BUDGET}s 预算，不为门让会话等着')
        report = sess / 'report.md'
        if not report.exists():
            continue
        md = report.read_text(encoding='utf-8', errors='ignore')
        if md.startswith('\ufeff'):
            md = md.lstrip('\ufeff')
        if DRAFT_RE.match(md):
            continue
        if report.stat().st_mtime < _started_at(sess):
            continue
        has_stamp = bool(STAMP_RE.search(md))
        if not (has_stamp or CLAIM_RE.search(md) or CLAIM_RE.search(claim_text)):
            continue
        ok, reason = _verdict(md, sess)
        if not ok:
            return _block(report, reason)
    return _allow()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:  # 钩子自身炸了不能变成"这个会话停不下来"
        sys.exit(_allow(f'门自检异常（{type(exc).__name__}: {exc}），本轮放行'))
