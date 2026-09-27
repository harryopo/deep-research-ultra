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
