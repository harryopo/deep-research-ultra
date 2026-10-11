"""v6.71：端到端验收发现的两个缺口，各钉一组回归。

## 缺口 1｜`ledger.py` 把 flag 当 session 目录静默创建

来源：验收时我在 PowerShell 里把 `$L=` 写成 `L=`，变量落空，命令变成
`add-claim --session --text "..."`。实测后果是 `--text/` 目录被创建、
账本写进去、exit 0、打印成功回执。**全程无报错**——调用方看到"写成功了"，
账本"有数据"，一路走到下游才被说"账本为空"。

比崩溃更糟的地方是它长得像成功。本组测试只钉一件事：**错一个就停，不落盘**。

## 缺口 2｜验戳不比对戳内的声明数字

防伪戳是 `body=… ledger=… claims=N sources=M`，`verify_stamp` 只算前两个指纹，
后两个是装饰。实测把戳改成 `claims=99` 照样验戳通过。

要紧的不是数字本身，是 `weak_allowed`：v6.62 把它写进戳的理由是
"这个决定必须跟着交付物走，交接的人只看到'过了校验门'看不到这是单源采信的"。
验戳不查它，就等于**无声删除即可让降级事实不可见**——承诺定在盖戳那一刻，
没落实到交付那一刻。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parents[1]
LEDGER = SCRIPTS / 'ledger.py'
VALIDATE = SCRIPTS / 'validate_report.py'
sys.path.insert(0, str(SCRIPTS))


def run_ledger(*args):
    r = subprocess.run([sys.executable, str(LEDGER), *args],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------------------
# 缺口 1：参数错位必须停住，且不落盘
# ---------------------------------------------------------------------------

def test_flag_cannot_pose_as_a_session_directory(tmp_path):
    """原样复刻那次事故：--session 的值落空，下一个选项顶上来当了目录名。"""
    before = set(p.name for p in SCRIPTS.iterdir())
    code, out = run_ledger('add-claim', '--session', '--text', '一条 claim', '--id', 'cx')
    after = set(p.name for p in SCRIPTS.iterdir())
    assert code == 2, f'exit={code}——盖戳前就漏过去了：{out[:160]}'
    assert not (after - before), f'落盘了垃圾目录：{sorted(after - before)}'
    assert '--text' in out, f'报错里没点名被顶上来的是哪个选项：{out[:160]}'


def test_trailing_option_reports_instead_of_traceback(tmp_path):
    """--session 放在末尾时旧版越界抛裸 IndexError，对调用方等于白屏。"""
    code, out = run_ledger('status', '--session')
    assert code == 2, f'exit={code}：{out[:120]}'
    assert 'Traceback' not in out, f'还在抛裸 traceback：{out[:200]}'
    assert 'IndexError' not in out
    assert '缺值' in out, f'没说要补什么：{out[:160]}'


def test_same_guard_covers_every_option_not_just_session(tmp_path):
    """_opt 有 10+ 处调用，同一个坑必须一起堵上，不能只补 --session。"""
    good = tmp_path / 'led'
    run_ledger('add-claim', '--session', str(good), '--text', 'x', '--id', 'c1')
    code, out = run_ledger('add-source', '--session', str(good), '--claim-id', 'c1',
                           '--url', '--title', 'T', '--craap', '70')
    assert code == 2, f'--url 落空却放行了：{out[:160]}'
    assert '--title' in out, out[:160]


def test_the_error_message_does_not_assume_paths(tmp_path):
    """报错内容本身在说错话，比不报错更容易把人带偏。

    _value 是所有选项共用的，第一版文案写死了"不是路径 / <目录>"，
    于是 --url 落空时会提示"该收目录"。
    """
    good = tmp_path / 'led2'
    run_ledger('add-claim', '--session', str(good), '--text', 'x', '--id', 'c1')
    _, out = run_ledger('add-source', '--session', str(good), '--claim-id', 'c1',
                        '--url', '--title', 'T')
    assert '目录' not in out, f'给 --url 报错却说它该收目录：{out[:200]}'
    assert '--url 该收的值' in out or '不是 --url' in out, out[:200]


def test_normal_usage_still_works(tmp_path):
    """守门不能变成门本身：正常写法必须照旧通过。"""
    good = tmp_path / 'led3'
    for args in (
            ('add-claim', '--session', str(good), '--text', '一条 claim',
             '--id', 'c1', '--topic', 'T'),
            ('add-source', '--session', str(good), '--claim-id', 'c1',
             '--url', 'https://example.org/a', '--title', 'T', '--craap', '70'),
            ('set-status', '--session', str(good), '--claim-id', 'c1', '--status', 'verified'),
            ('status', '--session', str(good)),
    ):
        code, out = run_ledger(*args)
        assert code == 0, f'{args[0]} 正常用法被新守卫挡住：{out[:200]}'


# ---------------------------------------------------------------------------
# 缺口 2：戳里的声明数字不能手改
# ---------------------------------------------------------------------------

def _build_single_source_report(tmp_path):
    """造一份"单源采信"且带真戳的报告：账本里确有独立来源不足的 verified claim。"""
    from validate_report import write_stamp
    from ledger import ResearchLedger

    led = tmp_path / 'ledger'
    led.mkdir()
    run_ledger('add-claim', '--session', str(led), '--text', '单源结论',
               '--topic', 'T', '--id', 'c1', '--confidence', '0.8')
    run_ledger('add-source', '--session', str(led), '--claim-id', 'c1',
               '--url', 'https://example.org/only', '--title', 'S', '--tier', '2', '--craap', '70')
    run_ledger('set-status', '--session', str(led), '--claim-id', 'c1', '--status', 'verified')

    body = ('# T\n\n## 一页拍板\n\n单源采信，按低置信处理 [1]。\n\n'
            '## 执行摘要\n\n仅一处来源 [1]。\n\n'
            '## 调研方法\n\n单次检索。\n\n'
            '## 结论与建议\n\n可试水 [1]。\n\n'
            '## 来源\n\n[1] https://example.org/only\n')
    report = tmp_path / 'report.md'
    report.write_text(body, encoding='utf-8')

    data = ResearchLedger(str(led)).export_json()
    weak = 1  # 这份账本按构造就有 1 条单源 verified claim
    write_stamp(str(report), str(led),
                {'claims': len(data['claims']), 'sources': len(data['sources']),
                 'weak_allowed': weak})
    return report, led


def _verify(report, ledger):
    r = subprocess.run(
        [sys.executable, str(VALIDATE), '--report', str(report),
         '--ledger', str(ledger), '--verify-stamp'],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout + r.stderr).strip()


def test_deleting_weak_allowed_is_rejected(tmp_path):
    """**这一条是 v6.71 存在的理由。**

    v6.62 让"放宽单源采信"进戳，是为了让交接的人看见这份报告是单源采信的。
    验戳以前不查它，于是无声删掉即可让这个事实不可见。
    """
    report, led = _build_single_source_report(tmp_path)
    original = report.read_text(encoding='utf-8')
    assert 'weak_allowed=' in original, '前置条件：这本来就是一份放宽过的报告'

    report.write_text(re.sub(r'\s*weak_allowed=\d+', '', original), encoding='utf-8')
    code, out = _verify(report, led)
    assert code != 0, f'删掉 weak_allowed 仍然验戳通过——降级事实可以被无声抹掉'
    assert 'weak_allowed' in out, f'没点明少了什么：{out[:200]}'
    assert '单源' in out, f'没说清这份报告的性质变了：{out[:200]}'


def test_intact_weak_allowed_still_passes(tmp_path):
    """反向：带 weak_allowed 的合法戳不能被误杀，否则没人敢用这个旋钮。"""
    report, led = _build_single_source_report(tmp_path)
    code, out = _verify(report, led)
    assert code == 0, f'合法戳被误杀：{out[:200]}'


def test_inflated_claim_count_is_rejected(tmp_path):
    report, led = _build_single_source_report(tmp_path)
    original = report.read_text(encoding='utf-8')
    report.write_text(re.sub(r'claims=\d+', 'claims=99', original), encoding='utf-8')
    code, out = _verify(report, led)
    assert code != 0, '把 claims 改成 99 仍然通过——戳里的数字是装饰'
    assert 'claims' in out, out[:200]


def test_inflated_source_count_is_rejected(tmp_path):
    report, led = _build_single_source_report(tmp_path)
    original = report.read_text(encoding='utf-8')
    report.write_text(re.sub(r'sources=\d+', 'sources=99', original), encoding='utf-8')
    code, out = _verify(report, led)
    assert code != 0, '把 sources 改成 99 仍然通过'
    assert 'sources' in out, out[:200]


def test_verification_and_gating_share_one_weak_rule(tmp_path):
    """盖戳前算 weak_allowed 与验戳时重算，必须是同一份规则。

    两处各写一份的话，改了门槛只改一处，验戳就会拿旧规则去质疑新戳——
    那比不查更糟：假阳性会让人以为戳失效了，于是去重新盖，
    真正的篡改反而混在噪音里。
    """
    src = VALIDATE.read_text(encoding='utf-8')
    assert src.count('_weak_verified_ids(') >= 3, (
        '主流程与验戳应共用 _weak_verified_ids，'
        f'实际只调用了 {src.count("_weak_verified_ids(")} 次')


def test_the_v671_fix_is_documented_where_it_happened():
    """缺口的更正要留在能查到的地方，不能只写在提交信息里。"""
    handoff = (REPO / '.ai' / 'HANDOFF.md').read_text(encoding='utf-8')
    assert 'v6.71' in handoff, 'HANDOFF 没记 v6.71'