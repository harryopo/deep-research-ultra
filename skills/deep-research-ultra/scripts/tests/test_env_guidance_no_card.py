"""X-新规矩：环境指引只许推荐"注册即可用、不绑银行卡"的数据源。

使用者明确交代过：需要注册的搜索源，哪怕每月有免费限量，只要注册要绑银行卡就一概不要。
所以"有免费额度"这句话不能裸着写——必须带着绑卡自查的提醒，否则 Lead 会照着抄给用户。
"""

from __future__ import annotations

from pathlib import Path

import probe

SKILL_MD = Path(__file__).resolve().parents[2] / 'SKILL.md'


def test_free_quota_guidance_carries_the_no_card_caveat():
    offenders = [k for k, v in probe.CONFIG_GUIDE.items()
                 if ('免费' in v or 'credits' in v) and '绑卡' not in v]
    assert not offenders, f'这些免费额度指引没写绑卡自查：{offenders}'
    # 哪些源需要盯绑卡，由 CONFIG_GUIDE 自己说了算（它的指引里写了"确认免绑卡"）；
    # README 是用户最先读到的那份指引，同一个源不能在这边省掉这句
    import re
    flagged = set()
    for v in probe.CONFIG_GUIDE.values():
        if '绑卡' in v:
            m = re.search(r'https?://(?:www\.)?([a-z0-9-]+)\.', v)
            if m:
                flagged.add(m.group(1))
    assert flagged, 'CONFIG_GUIDE 里一条绑卡提醒都没有，判据失效了'
    readme = (SKILL_MD.parents[2] / 'README.md').read_text(encoding='utf-8')
    naked = [ln.strip() for ln in readme.splitlines()
             if ('免费' in ln or 'credits' in ln) and '绑卡' not in ln
             and any(s in ln.lower() for s in flagged)]
    assert not naked, f'README 里有裸写的商业源免费额度：{naked}'


def test_skill_md_bans_card_required_sources():
    md = SKILL_MD.read_text(encoding='utf-8')
    assert '绑卡' in md, 'SKILL.md 里得写着这条规矩，不然下次又推给用户要绑卡的源'


def test_every_required_engine_config_is_named_by_env_check():
    """引擎的必需变量必须至少出现在一个 profile 的清单里，否则 --env-check 永远不提它。

    实测缺陷清单 A4（2026-09-28）：GITEE_TOKEN 是 gitee 引擎的必需项，
    而 opensource profile 的 envs 只有 GITHUB_TOKEN，SEARXNG_URL 同样没人提——
    回执上说"环境就绪"，用户要等到运行中"国内仓库那一路 0 条"才发现缺它，
    而那时候看起来像"这个主题没资料"。
    """
    from research import build_registry
    from env_check import PROFILES

    need = set()
    for e in build_registry().get_all():
        m = getattr(e, 'metadata', None)
        if m is None or not getattr(m, 'requires_config', False):
            continue
        need |= set(getattr(m, 'config_keys', []) or [])
    assert need, '一个必需变量都没扫到，这条断言是空转的'

    have = {k for p in PROFILES.values() for k in p['envs']}
    missing = sorted(need - have)
    assert not missing, f'引擎必需但 --env-check 从不提到的变量：{missing}'
    # 提到了还得说得出"去哪拿 + 解锁什么"，否则等于多一行了不明所以的变量名
    unexplained = sorted(k for k in have if k not in probe.CONFIG_GUIDE)
    assert not unexplained, f'--env-check 会点名要、却没有配置指引的变量：{unexplained}'


def test_local_crawl4ai_without_token_is_not_called_misconfigured(monkeypatch):
    """只在 Docker 部署时用得上的鉴权令牌，不能算"没配好"。

    顺带抓到的同类（A4 的假不可用形态）：Crawl4aiEngine 把 CRAWL4AI_API_TOKEN 和
    CRAWL4AI_URL 一起列进必需项，于是本地起了服务、URL 已配、当天能爬的机器上，
    `--probe` 仍回 ❌「缺少配置: CRAWL4AI_API_TOKEN」——这条源被闸门当成不存在。
    """
    from engines import crawl4ai_engine
    from engines.base import missing_required_config

    monkeypatch.setenv('CRAWL4AI_URL', 'http://localhost:11235')
    monkeypatch.delenv('CRAWL4AI_API_TOKEN', raising=False)

    assert missing_required_config(crawl4ai_engine.Crawl4aiEngine().metadata) == []
