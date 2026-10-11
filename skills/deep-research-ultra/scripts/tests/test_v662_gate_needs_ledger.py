"""v6.62.0：校验门必须绑账本，输出必须能自己建目录（体检报告 P0-1 / P0-2）。

体检时实测到一条完整的伪造链，全程 exit 0：

    造一份 100% 编造、引用三篇不存在文献、零证据的报告
      → validate_report.py --report fake.md          passed:true  EXIT=0
      → --stamp                                       ✅ 已盖防伪戳
      → --verify-stamp                                ✅ 戳有效  EXIT=0

而盖出来的戳自己写着 `ledger=none`——它不是"验证通过"的凭证，是"没验证过"的收据。
机理在 validate_report.py 的 text-only 分支：没有账本时，引用一致性（报告里的 [N]
对账本里的 sources）、覆盖率、逐字对账**一项都没跑**，却按"没有 issue 即通过"处理。
于是这个 skill 的核心卖点（可溯源）在最终交付点可以被完整跳过，交付物上还挂着一枚
"已验证"的章。

这组用例把三个门焊死：
1. 没账本 → 不许报通过（退出码非 0），并且要点明"没跑什么"；
2. 没账本 → 不许盖章；`ledger=none` 的戳（哪怕正文指纹完全正确）→ 验戳一律拒绝；
3. 正路不许被误伤：带账本、报告合格时照样盖章、照样验过（收紧不是把门焊死）。

外加 P0-2：`--output` 指向不存在的父目录时要自己建——实测这里原本直接
FileNotFoundError，检索和落账全做完了，最后一步崩掉，退出码 1 还被读成"调研失败"。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ledger import ResearchLedger
from validate_report import STAMP_RE, _main, validate_report, verify_stamp

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

# 体检时实际用来攻门的那份报告：章节齐全、引用规范、内容全编造。
FAKE = '''# 量子计算对药物发现的影响

## 一页拍板
量子计算将显著加速药物发现，推荐立即投入 [1]。这是完全虚构的内容，用于攻击测试。

## 执行摘要
量子计算在分子模拟上比经典计算快 10^8 倍 [1][2]。全球药企 2025 年投入 120 亿美元 [2]。
上述数字均为本测试编造，不对应任何真实来源。

## 调研范围与方法
通过检索 arXiv 与 PubMed，纳入 2020-2026 年文献 [3]。检索式见附录。

## 结论与建议
1. 立即成立量子药物研发部门 [1]。
2. 采购 5000 量子比特设备 [2]。

## 来源
[1] Zhang et al. Quantum Advantage in Drug Discovery. Nature, 2025.（不存在）
[2] Smith J. Quantum Pharma Investment Report. (不存在)
[3] 王某. 量子计算药物发现综述. 虚构期刊, 2026.（不存在）
'''

# 正路：账本里有对应的已验证 claim + 独立来源。
# 文件名必须叫 report.md —— guard.DEFAULT_ALLOW 白名单里是这个名字，
# 换成 honest.md 会被判成"会话目录里的未申报文件"（那是越权写判据，不是本用例要测的）。
HONEST = '''# RAG 评测基准现状

## 一页拍板
主流评测基准分检索与生成两层，选型要看是否分层 [1][2]。迁移成本尚未验证。
下一步：拿自己的查询集跑一遍对比。

## 执行摘要
现有基准以英文单跳为主 [1]，多跳场景另有专门数据集 [2]。

## 调研范围与方法
检索 arXiv 与 PubMed 纳入 2020-2026 年文献。

## 结论与建议
1. 选型先看是否区分检索/生成两层 [1][2]。

## 来源
[1] 基准综述A https://arxiv.org/0
[2] 多跳基准B https://arxiv.org/100
'''


@pytest.fixture()
def fake_report(tmp_path):
    p = tmp_path / 'fake.md'
    p.write_text(FAKE, encoding='utf-8')
    return p


@pytest.fixture()
def honest_env(tmp_path):
    """一份带真账本的合格报告。"""
    led = ResearchLedger(str(tmp_path / 'ledger')).init()
    c1 = led.add_claim('基准分层', 'RAG 评测', 'verified', 'general', 0.9)
    c2 = led.add_claim('多跳数据集', 'RAG 评测', 'verified', 'general', 0.8)
    for i in range(2):
        led.add_source(c1['id'], f'https://arxiv.org/{i}', tier=1)
        led.add_source(c2['id'], f'https://arxiv.org/{i + 100}', tier=1)
    report = tmp_path / 'report.md'
    report.write_text(HONEST, encoding='utf-8')
    return report, str(tmp_path / 'ledger')


# ---------------------------------------------------------------------------
# P0-1 第 1 门：没账本不许报通过
# ---------------------------------------------------------------------------

def test_no_ledger_is_not_a_pass(fake_report):
    """原行为：无账本时文本干净即 passed=true（→ exit 0）。"""
    r = validate_report(FAKE)
    assert not r.passed, (
        '没给账本就报了通过——引用一致性/覆盖率/逐字对账一项都没跑，'
        '这个「通过」不是可溯源凭证')
    assert any('--ledger' in i for i in r.issues), r.issues


def test_no_ledger_issue_says_what_did_not_run(fake_report):
    """只说"失败了"不够，要让人知道缺账本意味着哪些校验没做。"""
    r = validate_report(FAKE)
    msg = ' '.join(r.issues)
    assert '引用一致性' in msg and '未执行' in msg, msg


def test_no_ledger_exits_nonzero_from_cli(fake_report):
    assert _main(['--report', str(fake_report)]) != 0


# ---------------------------------------------------------------------------
# P0-1 第 2 门：没账本不许盖章
# ---------------------------------------------------------------------------

def test_stamp_without_ledger_is_refused(fake_report, capsys):
    assert _main(['--report', str(fake_report), '--stamp']) != 0
    assert '--ledger' in capsys.readouterr().err
    assert not STAMP_RE.search(fake_report.read_text(encoding='utf-8')), \
        '没账本却盖出了戳'


def test_ledger_none_stamp_never_verifies(fake_report):
    """v6.61 时代盖出来的戳：正文指纹完全正确，只是没有账本指纹。

    这是最危险的形状——它骗得过任何"戳对不对正文"的检查，
    所以验戳必须显式拒绝 ledger=none。"""
    import validate_report as vr
    body = vr._body_of(fake_report.read_text(encoding='utf-8'))
    fake_stamp = (f'<!-- drux:validated v={vr.STAMP_FMT} '
                  f'body={vr._sha(body)} ledger=none claims=? sources=? -->')
    fake_report.write_text(body + '\n\n' + fake_stamp + '\n', encoding='utf-8')

    ok, reason = verify_stamp(fake_report.read_text(encoding='utf-8'), None)
    assert not ok, 'ledger=none 的戳被验过了——它是"没验证过"的收据，不是凭证'
    assert 'ledger=none' in reason, reason


# ---------------------------------------------------------------------------
# P0-1 第 3 门：正路不许被误伤
# ---------------------------------------------------------------------------

def test_ledger_backed_report_still_gets_and_verifies_a_stamp(honest_env):
    report, ledger_dir = honest_env
    assert _main(['--report', str(report), '--ledger', ledger_dir, '--stamp']) == 0
    md = report.read_text(encoding='utf-8')
    stamp = STAMP_RE.search(md)
    assert stamp and 'ledger=none' not in stamp.group(0), '正路的戳里必须有账本指纹'
    assert _main(['--verify-stamp', '--report', str(report),
                  '--ledger', ledger_dir]) == 0


# ---------------------------------------------------------------------------
# P0-2：--output 的父目录要自己建
# ---------------------------------------------------------------------------

def test_write_out_creates_missing_parent_dirs(tmp_path):
    from research import _write_out
    dest = tmp_path / 'no' / 'such' / 'dir' / 'report.md'
    _write_out('正文', str(dest))
    assert dest.read_text(encoding='utf-8') == '正文'


def test_plan_only_output_creates_missing_parent_dirs(tmp_path):
    """走真实命令行：--plan-only -o 到两级不存在的目录。"""
    dest = tmp_path / 'new' / 'deep' / 'plan.json'
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / 'research.py'), '目录自建回归主题',
         '--plan-only', '--effort', 'quick', '--output', str(dest)],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(SCRIPTS))
    assert out.returncode == 0, (out.stdout or '')[-500:] + (out.stderr or '')[-500:]
    assert dest.exists(), '--plan-only 没有建出父目录'
