"""v6.15.6 回归：环境报告不再用一句"不影响核心调研"把代价盖掉。

起因（X-D12）。实测 academic 档把自己 profile 声明的四个数据源主机全掐断：

    ⚠️ [网络] arxiv.org — arxiv.org:443 不可达
    ⚠️ [网络] api.semanticscholar.org — ...
    ⚠️ [网络] api.openalex.org — ...
    ⚠️ [网络] doi.org — ...
    ✅ 就绪（可选增强项缺失 5 项，不影响核心调研）          ← 论文调研的源全断了
    rc=0

网络探测在 run_env_check 里一律 optional=True（v6.3 为了"降级链兜底、不阻断启动"），
于是主数据源不可达被折进"可选增强项"，还附赠一句"不影响核心调研"。这句话是
无根据的：它同时把"claude 命令没装"和"arxiv 连不上"算进同一个 N，用户既看不出
掉了哪块能力，也不知道该先修哪个——而调研第一步就是这道门。

修法不改退出码（rc 仍只由硬缺失决定：把偶发单点不通变成拒跑，是另一种误伤）。
只把回执说真：主机不通单列一条并写明"这些源回 0 条，不是主题没资料"，
缺配置另列一条并复用 probe.CONFIG_GUIDE 已有的"去哪拿 + 解锁什么"，
未探网络（--no-net）时不许说"完全就绪"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import env_check as EC  # noqa: E402

DEAD = lambda host, timeout=3.0: (False, f'{host}:443 不可达（模拟断网）')
ALIVE = lambda host, timeout=3.0: (True, f'{host}:443 连通')


def _text(profile='academic', net=DEAD, include_net=True):
    old = EC._check_net
    EC._check_net = net
    try:
        rep = EC.run_env_check(profile, include_net=include_net)
        return EC.format_report(rep), rep
    finally:
        EC._check_net = old


# ---------------------------------------------------------------- 主机不通
def test_hosts_down_no_longer_claimed_harmless():
    text, _ = _text()
    assert '不影响核心调研' not in text
    for host in ('arxiv.org', 'api.openalex.org', 'doi.org'):
        assert host in text
    assert '回 0 条' in text          # 说清后果，不是只报个"不可达"


def test_hosts_down_not_counted_as_optional_enhancements():
    """主机不通和"没配增强项"是两件事，不能揉成一个 N。"""
    text, rep = _text()
    assert len([c for c in rep.warnings if c.category == 'net']) == 4
    assert '数据源主机不通 4' in text
    assert '可选增强项缺失 5 项' not in text


# ---------------------------------------------------------------- 缺配置
def test_config_gaps_say_what_you_lose(monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    text, rep = _text('full', net=ALIVE)
    assert not rep.missing, 'Tavily 属可选项，不该变成硬缺失把门关上'
    lines = [ln for ln in text.splitlines() if 'TAVILY_API_KEY' in ln]
    assert lines, '缺的这项得出现在回执里'
    # 判据钉在"同一行"：app.tavily.com 同时也是个被探测的主机名，
    # 只查全文会因为撞对而假绿（第一版就是这么假过的）
    assert any('app.tavily.com' in ln and '申请' in ln for ln in lines), \
        '缺配置要跟着"去哪拿 + 解锁什么"，别让人去猜'


# ---------------------------------------------------------------- 正向对照
def test_positive_control_fully_ready_still_says_so():
    text, rep = _text('minimal', net=ALIVE)
    assert not rep.missing and not rep.warnings
    assert '环境完全就绪' in text


def test_hard_missing_still_fails_loudly(monkeypatch):
    """别为了话术好看把硬缺失也降成警告。"""
    monkeypatch.setattr(EC, '_check_module',
                        lambda m: (False, f'import {m} 失败：模拟未安装'))
    text, rep = _text('minimal', net=ALIVE)
    assert not rep.ready
    assert '尚未就绪' in text and '❌ 缺失' in text


def test_no_net_is_not_reported_as_fully_verified():
    """--no-net 时一个网络都没探，不许说"完全就绪"。"""
    text, rep = _text('academic', net=ALIVE, include_net=False)
    assert rep.net_skipped
    assert '就绪' in text                      # test_console 钉住的关键词
    assert '环境完全就绪' not in text
    assert '--no-net' in text
