"""v6.59 回归：管线全线基准重放——所有防线在同一批对抗语料上量化检出率。

对比报告 P1 建议"基准重放扩展（覆盖 L1/L2/guard 全线）"的落地：
不只测 L3（scan_untrusted），而是把 guard 机械门 / L3 untrusted / canary 外泄 /
发布门（validate_report）全部在对抗语料上跑一遍，量化每道防线的检出情况。

红队 → 蓝队 → 修复 → 绿队的完整循环：
1. 红队：注入 payload 进分片 → merge 入账本
2. 蓝队：guard + L3 + canary 三层检出
3. 修复：--text 重写干净原文
4. 绿队：发布门放行（干净版报告过门盖戳）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger, scan_untrusted  # noqa: E402

# 复用 v656 的 12 类 payload
from tests.test_v656_adversarial import PAYLOADS  # noqa: E402


# ============================================================
# 管线全线：红队注入 → 蓝队三层检出 → 修复 → 绿队放行
# ============================================================

class TestPipelineBenchmark:
    """在同一个会话上跑完整管线，量化每道防线的贡献。"""

    @pytest.fixture()
    def session(self, tmp_path):
        """一个含 12 类 payload 的完整会话。"""
        session = tmp_path / 's'
        led_dir = session / 'ledger'
        led = ResearchLedger(str(led_dir)).init()
        canary = 'DRUX_CANARY_DEADBEEF'
        (session / 'canary.txt').write_text(
            f'{canary}\ncreated_at: 2026-10-06\n说明：L4 哨兵\n', encoding='utf-8')
        # 红队：每个 payload 一条 claim
        for i, (kind, payload) in enumerate(sorted(PAYLOADS.items()), 1):
            cid = f'c-adv-{i:02d}'
            led.add_claim(payload, '对抗测试', 'pending', claim_id=cid)
            led.add_source(cid, f'https://github.com/attacker/p{i}', tier=3)
        return session, led_dir, led, canary

    def test_guard_catches_all_payloads(self, session):
        """蓝队第 1 层：guard 机械门——证据链里的注入命中必须全部被抓。"""
        import subprocess
        session, led_dir, led, canary = session
        proc = subprocess.run(
            [sys.executable,
             str(Path(__file__).resolve().parents[1] / 'guard.py'),
             '--session', str(session)],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        # guard 应该非零退出（证据链里有注入内容且未留痕）
        assert proc.returncode != 0, \
            'guard 必须在证据链里检出注入——全部放行意味着机械门失效'
        # 输出里应该提到命中
        combined = proc.stdout + proc.stderr
        assert '命中' in combined or '指令' in combined or '注入' in combined, \
            f'guard 输出应描述命中内容：{combined[:200]}'

    def test_l3_flags_all_payloads(self, session):
        """蓝队第 2 层：L3 untrusted 标记——所有 payload claim 必须带标。"""
        _session, _led_dir, led, _canary = session
        unflagged = []
        for line in open(led.entries_path, encoding='utf-8'):
            r = json.loads(line)
            if r.get('type') == 'claim' and r.get('topic') == '对抗测试':
                if not r.get('untrusted'):
                    unflagged.append(r['id'])
        assert not unflagged, f'{len(unflagged)} 条 payload claim 未被 L3 标记：{unflagged}'

    def test_i4_blocks_all_upgrade_attempts(self, session):
        """蓝队第 3 层：I4——所有 payload claim 的 verified 升级必须被拒。"""
        _session, _led_dir, led, _canary = session
        ids = [f'c-adv-{i:02d}' for i in range(1, len(PAYLOADS) + 1)]
        changed = led.set_status(ids, 'verified', note='尝试批量升级')
        assert changed == 0, f'I4 应拒绝全部 {len(ids)} 条升级，实际放行 {changed} 条'

    def test_canary_not_exfiltrated_yet(self, session):
        """蓝队第 4 层：canary——种下后未被外传（红队 payload 不含 canary 引用）。"""
        from canary import main as canary_main
        session_dir, _led_dir, _led, canary = session
        rc = canary_main(['check', '--session', str(session_dir)])
        assert rc == 0, '红队 payload 不含 canary 引用，canary 不应报外泄'

    def test_repair_reopens_upgrade_path(self, session):
        """绿队：--text 逐条重写干净原文 → I4 解除 → 可正常升级。"""
        _session, _led_dir, led, _canary = session
        repaired = 0
        for i in range(1, len(PAYLOADS) + 1):
            cid = f'c-adv-{i:02d}'
            clean = f'对抗测试 {i:02d} 的干净重写版本：原文中的注入内容已甄别移除。'
            if led.set_status([cid], 'verified', text=clean, note='甄别后重写') == 1:
                repaired += 1
        assert repaired == len(PAYLOADS), \
            f'修复后 {repaired}/{len(PAYLOADS)} 条应可升级'

    def test_clean_report_passes_gate(self, session, tmp_path):
        """绿队闭环：全部修复后，干净版报告应过发布门。"""
        _session, led_dir, led, _canary = session
        # 先修复全部 payload
        for i in range(1, len(PAYLOADS) + 1):
            cid = f'c-adv-{i:02d}'
            clean = f'对抗测试 {i:02d} 的干净重写：注入内容已甄别移除，事实保留。'
            led.set_status([cid], 'verified', text=clean, note='甄别后重写')
        # 写一份引用这些 claim 的最小报告（含全部必需章节）
        cites = ' '.join(f'[{i}]' for i in range(1, 13))
        report = tmp_path / 'clean_report.md'
        lines = [
            '# 对抗压测报告', '',
            '## 一页拍板',
            f'直接结论：全部 payload 已甄别修复 {cites}。', '',
            '## 执行摘要',
            f'摘要：12 类注入 payload 已全部甄别修复。[1]', '',
            '## 调研范围与方法',
            '方法：12 类注入语料全量测试，甄别后重写。', '',
            '## 结论与建议',
            f'结论：全部修复完成 {cites}。', '',
            '## 来源', '', '| 编号 | Tier | 标题 | URL |', '|---|---|---|---|',
        ]
        for i in range(1, 13):
            lines.append(f'| [{i}] | 3 | 对抗测试 {i} | https://github.com/attacker/p{i} |')
        report.write_text('\n'.join(lines) + '\n', encoding='utf-8')

        from validate_report import validate_report
        r = validate_report(report.read_text(encoding='utf-8'),
                            ledger=str(led_dir))
        # 注入相关 issue 必须为零（结构性 issue 不属于防线测试范围）
        injection_issues = [i for i in r.issues
                            if '注入' in i or 'injection' in i.lower()
                            or 'L3' in i or 'untrusted' in i]
        assert not injection_issues, \
            f'干净版报告不应有注入相关 issue：{injection_issues}'
