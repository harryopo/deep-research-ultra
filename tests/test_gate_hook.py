"""计划 B2：Stop 钩子 gate_hook.py 的验收。

按宿主真实契约测：stdin 喂一段 Stop 载荷（字段名取自 2026-09-21 本机抓到的
hooks/.drux-hook-stop.raw：cwd / stop_hook_active / last_assistant_message），
断言退出码与 stderr。不用 import 调函数的方式测——钩子的失效方式（编码、
崩溃、退出码没被宿主认）全都发生在进程边界上，import 测不到。

放行 = 退 0；拦下 = 退 2 且 stderr 说清哪一条不成立、怎么修。
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks' / 'gate_hook.py'
sys.path.insert(0, str(ROOT / 'skills' / 'deep-research-ultra' / 'scripts'))

from validate_report import write_stamp  # noqa: E402

BODY = ('# 边缘推理调研\n\n## 核心结论\n\n延迟中位数 8ms [1]。\n\n'
        '## 来源\n\n[1] https://arxiv.org/abs/2601.00001\n')


def _session(tmp_path: Path, *, started: datetime = None) -> Path:
    """造一个和 drux_session_start 产出同形的会话目录。"""
    sess = tmp_path / '.research' / 'drux-20260921-120000-abc123'
    sess.mkdir(parents=True)
    started = started or datetime.now() - timedelta(minutes=5)
    (sess / 'session.json').write_text(
        json.dumps({'session_id': sess.name, 'started_at': started.isoformat(timespec='seconds'),
                    'query': '边缘推理调研', 'effort': 'standard', 'dimensions': ['性能']},
                   ensure_ascii=False), encoding='utf-8')
    (sess / 'ledger.jsonl').write_text(
        '{"type":"claim","id":"C1","status":"verified","topic":"性能","text":"延迟中位数 8ms"}\n'
        '{"type":"source","claim_id":"C1","url":"https://arxiv.org/abs/2601.00001",'
        '"title":"Edge Inference","tier":1}\n', encoding='utf-8')
    return sess


def _report(sess: Path, *, stamp: bool = False, edit_after_stamp: bool = False,
            first_line: str = '', ledger_dir: Path = None) -> Path:
    path = sess / 'report.md'
    text = (f'{first_line}\n' if first_line else '') + BODY
    path.write_text(text, encoding='utf-8')
    if stamp:
        write_stamp(str(path), str(ledger_dir or sess), {'claims': 1, 'sources': 1})
        if edit_after_stamp:
            # 盖戳之后偷改正文：戳与正文不再相符，这正是防伪戳要抓的那一件事
            path.write_text(path.read_text(encoding='utf-8').replace('8ms', '3ms'),
                            encoding='utf-8')
    return path


def _cli_session(tmp_path: Path) -> Path:
    """CLI（research.py --ledger ...）跑出来的会话形状：账本在 <会话>/ledger/ 下一层。"""
    sess = _session(tmp_path)
    ledger = sess / 'ledger'
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / 'ledger.jsonl').write_text((sess / 'ledger.jsonl').read_text(encoding='utf-8'),
                                         encoding='utf-8')
    (sess / 'ledger.jsonl').unlink()
    info = json.loads((sess / 'session.json').read_text(encoding='utf-8'))
    info['ledger_dir'] = 'ledger'
    (sess / 'session.json').write_text(json.dumps(info, ensure_ascii=False), encoding='utf-8')
    return sess


def _run(cwd: Path, *, stop_hook_active: bool = False,
         last_message: str = '') -> subprocess.CompletedProcess:
    payload = {'session_id': '1b344a1d-af71', 'transcript_path': str(cwd / 't.jsonl'),
               'cwd': str(cwd), 'hook_event_name': 'Stop',
               'stop_hook_active': stop_hook_active,
               'last_assistant_message': last_message}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode('utf-8'),
                          capture_output=True, cwd=str(cwd), timeout=30)


def test_hook_file_exists():
    assert HOOK.exists(), '缺 hooks/gate_hook.py —— 计划 B 的防假交付门还没落地'


def test_hook_leaves_no_trace_when_there_is_nothing_to_judge(tmp_path):
    """普通项目（没有 .research）里钩子必须一声不响：一有输出就成了每次收尾都冒出来的噪声。"""
    r = _run(tmp_path)
    assert r.returncode == 0, f'没有 .research 的普通项目被钩子干扰：{r.stderr}'
    assert r.stderr == b'', f'无话可说时也在输出：{r.stderr.decode("utf-8", "replace")}'


def test_hook_records_its_verdict_when_it_judges(tmp_path):
    """反馈第 15 条：拦截过没拦截过看得见，但"跑过了且放行"过去是静默的——
    实跑里"钩子放行"与"钩子根本没被调起/自己崩了"完全同形，所以永远观测不到。
    判过哪个会话就必须留一行判定记录（不含报告正文）。"""
    sess = _session(tmp_path)
    _report(sess, stamp=True)
    r = _run(tmp_path, last_message='报告已交付，校验门 passed')
    err = r.stderr.decode('utf-8', errors='replace')
    assert r.returncode == 0, f'真戳被拦：{err}'
    assert 'gate_hook' in err, f'跑过了却没留任何记录，仍然无法与"没跑"区分：{err}'
    assert sess.name in err, f'记录了判定但没说是哪个会话：{err}'
    assert '延迟中位数' not in err, f'判定记录里回显了报告正文：{err}'


def test_valid_stamped_report_is_allowed(tmp_path):
    sess = _session(tmp_path)
    _report(sess, stamp=True)
    r = _run(tmp_path, last_message='报告已交付，校验门 passed')
    assert r.returncode == 0, f'真戳被拦：{r.stderr.decode("utf-8", "replace")}'


def test_stamp_edited_afterwards_is_blocked(tmp_path):
    sess = _session(tmp_path)
    _report(sess, stamp=True, edit_after_stamp=True)
    r = _run(tmp_path, last_message='报告已交付，校验门 passed')
    err = r.stderr.decode('utf-8', errors='replace')
    assert r.returncode == 2, f'盖戳后偷改正文却没拦住：exit={r.returncode} err={err}'
    assert '正文与戳不符' in err, f'没点明是哪一半不成立：{err}'


def test_handwritten_stamp_is_blocked(tmp_path):
    sess = _session(tmp_path)
    path = _report(sess)
    path.write_text(path.read_text(encoding='utf-8')
                    + '\n<!-- drux:validated v=1 body=deadbeefdeadbeef '
                      'ledger=deadbeefdeadbeef claims=1 sources=1 -->\n', encoding='utf-8')
    r = _run(tmp_path)
    err = r.stderr.decode('utf-8', errors='replace')
    assert r.returncode == 2, f'手写的戳被当成真戳放行了：exit={r.returncode} err={err}'
    assert '正文与戳不符' in err, err


def test_claim_without_stamp_is_blocked(tmp_path):
    sess = _session(tmp_path)
    _report(sess)
    r = _run(tmp_path, last_message='已完成深度调研并交付，校验通过')
    err = r.stderr.decode('utf-8', errors='replace')
    assert r.returncode == 2, f'只有自述交付、没有机器戳，却没拦住：{err}'
    assert 'drux:validated' in err, f'没告诉 Lead 怎么补上凭据：{err}'


def test_cli_shaped_session_is_judged_not_skipped(tmp_path):
    """反馈第 15 条的根因：钩子原先只认 drux_session_start 建的会话（账本直接在会话根），
    而 CLI 跑出来的是 `.research/<会话>/ledger/ledger.jsonl` + 会话根的 report.md，
    且没有 session.json——实跑里 Lead 走的正是 CLI，所以钩子一条都没看过，
    报告里写的"钩子没有拦截机会"其实是"钩子不在场"。"""
    sess = _cli_session(tmp_path)
    _report(sess, stamp=True, ledger_dir=sess / 'ledger')
    r = _run(tmp_path, last_message='报告已交付，校验门 passed')
    err = r.stderr.decode('utf-8', errors='replace')
    assert r.returncode == 0, f'CLI 形状的会话里真戳被拦：{err}'
    assert '放行' in err, f'钩子压根没看到这个会话（跳过=不在场）：{err}'
    assert '账本与戳不符' not in err, f'把 CLI 的账本目录认错了一层：{err}'


def test_cli_shaped_ledger_edit_after_stamp_is_blocked(tmp_path):
    """上一条证明"看得见"，这一条证明"看得对"：账本换一层后仍能指纹绑定，
    否则改出来的放行只是因为指纹永远算成 absent。"""
    sess = _cli_session(tmp_path)
    _report(sess, stamp=True, ledger_dir=sess / 'ledger')
    entries = sess / 'ledger' / 'ledger.jsonl'
    entries.write_text(entries.read_text(encoding='utf-8')
                       + '{"type":"claim","id":"C2","status":"verified","topic":"性能",'
                         '"text":"临时插进账本的结论"}\n', encoding='utf-8')
    r = _run(tmp_path, last_message='报告已交付，校验门 passed')
    err = r.stderr.decode('utf-8', errors='replace')
    assert r.returncode == 2, f'盖戳后往账本插了一条却没拦住：exit={r.returncode} err={err}'
    assert '账本与戳不符' in err, err


def test_no_delivery_claim_is_not_blocked(tmp_path):
    """没声称交付就不该管——否则每次普通对话收尾都被卡住。"""
    sess = _session(tmp_path)
    _report(sess)
    r = _run(tmp_path, last_message='先记这几条，剩下的等下一轮再补')
    assert r.returncode == 0, f'没声称交付却被拦：{r.stderr.decode("utf-8", "replace")}'


def test_draft_report_is_not_blocked(tmp_path):
    sess = _session(tmp_path)
    _report(sess, first_line='DRAFT: 半成品，未过校验门')
    r = _run(tmp_path, last_message='本轮把结论都交付了')
    assert r.returncode == 0, f'DRAFT: 明示未完成的稿子仍被拦：{r.stderr.decode("utf-8", "replace")}'


def test_no_research_dir_is_not_blocked(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, f'没有 .research 的普通项目被钩子干扰：{r.stderr}'


def test_report_older_than_session_is_not_blocked(tmp_path):
    """上一轮遗留的旧报告不该让本轮收不了工：判据是 report.md 早于会话开始时间。"""
    sess = _session(tmp_path, started=datetime.now() + timedelta(days=1))
    _report(sess, edit_after_stamp=False)
    r = _run(tmp_path, last_message='交付完成')
    assert r.returncode == 0, f'旧报告被当成本轮交付：{r.stderr.decode("utf-8", "replace")}'


def test_stop_hook_active_never_blocks():
    """宿主用这个字段告知「上一次拦完你已经改过一轮了」。再拦就是死循环。"""
    r = _run(Path.cwd(), stop_hook_active=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize('raw', [b'', b'not json at all', b'{"cwd": null}'])
def test_malformed_payload_fails_open(raw):
    """载荷坏了是宿主的事，不是 Agent 的罪：崩在这里会把整个会话卡死。"""
    r = subprocess.run([sys.executable, str(HOOK)], input=raw,
                       capture_output=True, cwd=str(ROOT), timeout=30)
    assert r.returncode == 0, (raw, r.stderr.decode('utf-8', 'replace'))


def test_hook_never_prints_the_report_body(tmp_path):
    """钩子只报「哪条不成立 + 怎么修」。把正文回显进 stderr 等于把用户内容再抄一份进日志。"""
    sess = _session(tmp_path)
    _report(sess)
    r = _run(tmp_path, last_message='已交付')
    err = r.stderr.decode('utf-8', errors='replace')
    assert r.returncode == 2
    assert '延迟中位数' not in err, f'stderr 里回显了报告正文：{err}'
    assert re.search(r'gate_hook|drux', err), f'没说是谁拦的：{err}'
