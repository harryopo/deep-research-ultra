"""
tier.py — 来源可信层级（Source Tier）分级  [v6.0 新增]

按域名判断调研来源的可信层级，供 score / validate_report / report 三方共用。

Tier 分级：
    1 = 官方/学术（政府、教育机构、学术出版、厂商官方主域）
    2 = 权威/官方文档（权威媒体、官方文档站、学术数据库平台）
    3 = 一般（普通新闻/博客/聚合站/企业博客）
    4 = 社区/低质（论坛、社交、个人博客、匿名平台、无 TLS）

设计约束：
- 纯确定性规则（域名匹配合并/黑名单/学术表），秒级返回，不依赖 LLM 与网络探测
- 与 score.py 低耦合：score 内可选 import，模块缺失时行为不变
- 支持 --add-tier 持久化白名单覆盖（写入 scripts/tier_overrides.json）
"""

from __future__ import annotations

import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 内置判定表
# ---------------------------------------------------------------------------

# 学术/文献/官方文档平台域名（Tier 1-2 关键，子域名亦命中）
ACADEMIC_DOMAINS = {
    'arxiv.org': 1, 'openalex.org': 1, 'pubmed.ncbi.nlm.nih.gov': 1,
    'doi.org': 1, 'semanticscholar.org': 2, 'scholar.google.com': 2,
    'ncbi.nlm.nih.gov': 1, 'nih.gov': 1, 'osti.gov': 1,
    'core.ac.uk': 1, 'citeseerx.ist.psu.edu': 2, 'dl.acm.org': 1,
    'ieeexplore.ieee.org': 1, 'springer.com': 1, 'sciencedirect.com': 1,
    'wiley.com': 1, 'nature.com': 1, 'science.org': 1, 'cell.com': 1,
    'acm.org': 1,
    # 同行评审正式出版物：缺这些条目会让 ACL/PMLR 论文落到默认 Tier 3，
    # 而预印本 arxiv.org 是 Tier 1 —— 实测分级方向性颠倒。
    'aclanthology.org': 1, 'aclweb.org': 1,
    'proceedings.mlr.press': 1, 'jmlr.org': 1,
    'direct.mit.edu': 1, 'plos.org': 1,
    'biomedcentral.com': 1, 'annualreviews.org': 1,
    'ijcai.org': 1, 'aaai.org': 1, 'openreview.net': 2,
}

# 权威媒体白名单（Tier 2；知名媒体为 Tier 2，旗舰学术刊物并入 ACADEMIC_DOMAINS）
AUTHORITATIVE_MEDIA = {
    # 国际
    'bbc.com': 2, 'bbc.co.uk': 2, 'reuters.com': 2, 'apnews.com': 2,
    'nytimes.com': 2, 'wsj.com': 2, 'bloomberg.com': 2, 'ft.com': 2,
    'economist.com': 2, 'theguardian.com': 2, 'washingtonpost.com': 2,
    'forbes.com': 2, 'techcrunch.com': 2, 'theverge.com': 2,
    'wired.com': 2, 'arstechnica.com': 2, 'spectrum.ieee.org': 2,
    'medium.com': 3,
    # 中文权威
    'people.com.cn': 1, 'gov.cn': 1, 'xinhuanet.com': 1,
    'cctv.com': 2, 'cctv.cn': 2, 'caixin.com': 2, 'yicai.com': 2,
    'chinanews.com.cn': 2, 'gmw.cn': 2, 'southcn.com': 2,
    'thepaper.cn': 2, 'jiecaiapp.com': 3,
    # 科技媒体
    'zhihu.com': 4, '36kr.com': 3, 'ithome.com': 3, 'cnbeta.com': 3,
    'sspai.com': 3, 'infoq.cn': 2, 'oschina.com': 3, 'csdn.net': 3,
    'juejin.cn': 3, 'segmentfault.com': 3,
}

# 官方文档/权威平台（Tier 2）
OFFICIAL_DOCS = {
    'github.com': 2, 'gitlab.com': 2, 'docs.python.org': 1,
    'developer.mozilla.org': 2, 'w3.org': 1, 'openai.com': 1,
    'anthropic.com': 1, 'google.com': 2, 'microsoft.com': 2,
    'apple.com': 2, 'aws.amazon.com': 2, 'cloud.google.com': 2,
    'learn.microsoft.com': 2, 'react.dev': 2, 'nextjs.org': 2,
    'karpathy.ai': 3,
}

# 社区/低质平台（Tier 4，黑名单）
COMMUNITY_DOMAINS = {
    'reddit.com': 4, 'quora.com': 4, 'youtube.com': 4, 'twitter.com': 4,
    'x.com': 4, 'facebook.com': 4, 'instagram.com': 4, 'tiktok.com': 4,
    'bilibili.com': 4, 'douban.com': 4, 'weibo.com': 4, 'weibo.cn': 4,
    'v2ex.com': 4, 'tieba.baidu.com': 4, 'stackoverflow.com': 3,
    'stackexchange.com': 3, 'discord.com': 4, 'telegram.org': 4,
    '4chan.org': 4, '9gag.com': 4, 'gitee.com': 3, 'npmjs.com': 2,
    'pypi.org': 2, 'crates.io': 2, 'huggingface.co': 2,
}

_OVERRIDES_FILE = Path(__file__).resolve().parent / 'tier_overrides.json'


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _normalize_domain(url: str) -> Tuple[str, bool]:
    """从 URL 提取规范化主域（含子域），返回 (domain, is_http)。

    仅返回注册域之下的完整主机名（如 www.example.com → example.com，
    zh.wikipedia.org → wikipedia.org），便于子域名规则命中。
    """
    url = (url or '').strip()
    if not url:
        return '', False
    try:
        parsed = urlparse(url if '://' in url else '//' + url)
        host = (parsed.hostname or '').lower()
        is_http = parsed.scheme in ('http', 'http:')
    except Exception:
        host = re.sub(r'^[a-zA-Z]+://', '', url).split('/')[0].lower()
        is_http = False
    return host, is_http


def _public_suffix(host: str) -> str:
    """取最可能的注册域（去除 www 等二级子域；对 .com.cn 之类尽力）。

    简化处理：去除主机名最左 'www.'/'m.'/'mobile.' 前缀，
    若剩余部分超过 3 段且后两段为 '域名+两字母国别'（如 example.com.cn），
    则尝试去掉最左一段。
    """
    h = host
    for p in ('www.', 'm.', 'mobile.', 'static.'):
        if h.startswith(p):
            h = h[len(p):]
    parts = h.split('.')
    # co.uk / com.cn / org.cn 等复合后缀
    composite = {'com', 'org', 'net', 'gov', 'edu', 'ac', 'co', 'info',
                 'me', 'io', 'ai', 'cn', 'uk', 'jp', 'de', 'fr', 'ru'}
    if len(parts) >= 3 and parts[-1] in composite and parts[-2] in composite:
        return '.'.join(parts[-3:])
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    return h


def domain_tier(url: str) -> int:
    """判定给定 URL 的来源可信层级（1-4）。"""
    host, is_http = _normalize_domain(url)
    if not host:
        return 4

    # 1) 用户覆盖表（最高优先）
    overrides = load_overrides()
    if host in overrides:
        return int(overrides[host])
    reg = _public_suffix(host)
    if reg in overrides:
        return int(overrides[reg])

    # 2) 学术/官方文档精确命中（含子域自举）
    #    v6.3：http 无 TLS 的 Tier 1 学术源降一级（学术域走明文链路可信度打折）
    for domain, tier in ACADEMIC_DOMAINS.items():
        if _host_matches(host, domain, allow_sub=True):
            if is_http and tier == 1:
                return min(tier + 1, 4)
            return tier

    # 3) 官方文档/权威平台（允许子域：docs.github.com 等）
    for domain, tier in OFFICIAL_DOCS.items():
        if _host_matches(host, domain, allow_sub=True):
            return tier

    # 4) 权威媒体
    for domain, tier in AUTHORITATIVE_MEDIA.items():
        if _host_matches(host, domain, allow_sub=True):
            return tier

    # 5) 社区/低质平台
    for domain, tier in COMMUNITY_DOMAINS.items():
        if _host_matches(host, domain, allow_sub=True):
            return tier

    # 6) 政府/教育机构顶级域 → Tier 1
    if host.endswith('.gov') or host.endswith('.gov.cn') or host.endswith('.edu'):
        return 1 if not is_http else 2

    # 7) 学术域名后缀（.edu.cn / .ac.cn）
    if re.search(r'\.(edu|ac)\.(cn|jp|uk|de|fr|au|in|sg|tw|hk)$', host):
        return 1 if not is_http else 2

    # 8) 未知域名：http 无 TLS → 降为 4，其余 → 3
    if is_http:
        return 4
    return 3


def _host_matches(host: str, domain: str, allow_sub: bool) -> bool:
    """判断 host 是否等于或属于 domain。allow_sub=True 时子域名命中。"""
    if host == domain:
        return True
    if allow_sub and host.endswith('.' + domain):
        return True
    return False


def tier_label(tier: int) -> str:
    """Tier 数字 → 中文标签。"""
    return {1: '官方/学术', 2: '权威/官方文档', 3: '一般', 4: '社区/低质'}.get(int(tier), '未知')


def tier_penalty(tier: int) -> float:
    """Tier → 评分权重调节（+0.10 / +0.05 / +0.00 / -0.15），供 score.py 使用。"""
    return {1: 0.10, 2: 0.05, 3: 0.0, 4: -0.15}.get(int(tier), 0.0)


# ---------------------------------------------------------------------------
# 覆盖表持久化
# ---------------------------------------------------------------------------

def load_overrides() -> Dict[str, int]:
    """读取用户覆盖表（domain → tier）。"""
    if not _OVERRIDES_FILE.exists():
        return {}
    try:
        data = json.loads(_OVERRIDES_FILE.read_text(encoding='utf-8'))
        return {str(k).lower(): int(v) for k, v in data.items()}
    except Exception:
        return {}


def add_override(domain: str, tier: int) -> Dict[str, int]:
    """添加/更新覆盖规则并持久化。"""
    overrides = load_overrides()
    overrides[domain.strip().lower().lstrip('.')] = int(tier)
    _OVERRIDES_FILE.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True),
        encoding='utf-8'
    )
    return overrides


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        print('\n用法:')
        print('  python tier.py <url>                 # 打印分级')
        print('  python tier.py --add-tier <domain> <tier>   # 添加覆盖规则')
        print('  python tier.py --list-overrides     # 列出覆盖规则')
        return 0

    if args[0] == '--add-tier' and len(args) == 3:
        overrides = add_override(args[1], int(args[2]))
        print(json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args[0] == '--list-overrides':
        print(json.dumps(load_overrides(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    for url in args:
        if url in ('--add-tier', '--list-overrides'):
            continue
        t = domain_tier(url)
        host, is_http = _normalize_domain(url)
        print(f'{url}\n  → {host}  Tier {t}（{tier_label(t)}）{"（http 无 TLS）" if is_http else ""}')
    return 0


if __name__ == '__main__':
    from console import force_utf8
    force_utf8()
    sys.exit(_main())