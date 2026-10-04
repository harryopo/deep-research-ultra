"""v6.53 回归：注入防线 L1 出口白名单 + L4 canary 哨兵 + L2 引文长度上限。

对应注入防护方案（references/论文-安全章节-注入防护方案.md）S.5 的落地面：
- L1（I2，唯一确定性防线）：所有经公共通道（engines/fallback 的 _http_get/_http_post）
  的 HTTP 出口，目标主机必须在启动时固定的白名单内；拒绝发生在建立任何连接之前。
- L4（I2/I3 可观测性）：会话携带假凭据（DRUX_CANARY_*），出现在 canary.txt 以外
  任何文件＝注入已生效并改变行为或外传的实证。
- L2（I1）：逐字引文 ≤1200 字，超长只告警不阻断（引文是证据引用不是原文搬运）。

已知不归本通道管的出带（有据，见 fallback._EGRESS_ALLOW 注释）：ddgs 库、
MCP 子进程、repo_health 裸 urlopen（X-D11 契约）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================
# L1：出口白名单
# ============================================================

REAL_ENDPOINTS = [
    'https://doi.org/10.1037/a0037559',
    'https://api.crossref.org/works/10.1037/a0037559',
    'https://api.openalex.org/works?search=x',
    'https://api.semanticscholar.org/graph/v1/paper/DOI:10.1037/a0037559',
    'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=1',
    'https://pubmed.ncbi.nlm.nih.gov/16719566/',
    'https://europepmc.org/article/MED/16719566',
    'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
    'https://api.unpaywall.org/v2/10.1037/a0037559?email=x@y.z',
    'https://arxiv.org/abs/2401.00001',
    'https://export.arxiv.org/api/query',
    'https://api.github.com/repos/ankitects/anki',
    'https://github.com/ankitects/anki',
    'https://raw.githubusercontent.com/ankitects/anki/main/README.md',
    'https://gitee.com/a/b',
    'https://modelscope.cn/api/v1/models/x',
    'https://www.baidu.com/s?wd=x',
    'https://xueshu.baidu.com/s?wd=x',
    'https://zhihu.sogou.com/link?url=x',
    'https://weixin.sogou.com/wechat?type=2&query=x',
    'https://cn.bing.com/search?q=x',
    'https://api.tavily.com/search',
    'https://www.firecrawl.dev/v1/scrape',
    'https://r.jina.ai/https://example.org/page',
    'https://api.osv.dev/v1/query',
]


def test_egress_allows_every_real_engine_endpoint():
    from engines.fallback import egress_denied_reason

    for url in REAL_ENDPOINTS:
        assert egress_denied_reason(url) == '', f'{url} 应在白名单内'


def test_egress_denies_unknown_and_lookalike_hosts():
    from engines.fallback import egress_denied_reason

    for url in ('https://203.0.113.1/x',                      # TEST-NET，绝不该发起连接
                'https://evil.example/fetch?u=x',
                'https://evil-github.com/x',                  # 相似名 ≠ 后缀匹配
                'https://github.com.evil.io/x',               # 后缀伪装
                'https://openalex.org.evil.io/x'):
        reason = egress_denied_reason(url)
        assert reason, f'{url} 必须被拒'
        assert '白名单' in reason


def test_egress_env_hosts_are_startup_fixed():
    from engines.fallback import egress_denied_reason

    url = 'http://my-crawl.internal:11235/screenshot'
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv('CRAWL4AI_URL', 'http://my-crawl.internal:11235')
        assert egress_denied_reason(url) == ''
        monkeypatch.delenv('CRAWL4AI_URL', raising=False)
        assert egress_denied_reason(url), '环境变量撤掉后同一主机必须被拒'
    finally:
        monkeypatch.undo()


def test_http_get_denied_before_any_connection(monkeypatch):
    """拒绝必须发生在建立连接之前——被拒主机连不上也拿不到任何回包。"""
    import urllib.request

    from engines import fallback

    url = 'https://blocked-by-policy.example/x'
    assert fallback._http_get(url) is None
    assert '白名单' in (fallback.LAST_HTTP_ERROR or '')
    assert fallback._http_post(url, json_body={'a': 1}) is None
    assert '白名单' in (fallback.LAST_HTTP_ERROR or '')
    # 防呆：同 URL 若白名单放行（不可能在此测试里），也不应真的发请求——
    # 用 urllib 的 opener 打桩确认"拒绝路径不触网"
    opened = []
    monkeypatch.setattr(urllib.request, 'build_opener',
                        lambda *a, **k: opened.append(1) or (_ for _ in ()).throw(
                            AssertionError('被拒请求不该走到 opener')))
    assert fallback._http_get(url) is None
    assert opened == []


# ============================================================
# L4：canary 哨兵
# ============================================================

def _run(*argv):
    from canary import main
    return main(list(argv))


def test_canary_init_token_check_roundtrip(tmp_path, capsys):
    session = str(tmp_path / 's')
    assert _run('init', '--session', session) == 0
    token = Path(session, 'canary.txt').read_text(encoding='utf-8').splitlines()[0]
    assert token.startswith('DRUX_CANARY_')
    assert _run('token', '--session', session) == 0
    # 干净会话：令牌只在 canary.txt → 未外泄
    assert _run('check', '--session', session) == 0
    # 令牌写进了别的文件（报告）＝外泄实证
    (tmp_path / 'report.md').write_text(f'结论引用 {token} 作为凭据。\n', encoding='utf-8')
    assert _run('check', '--session', session,
                '--report', str(tmp_path / 'report.md')) == 1


def test_canary_check_requires_init(tmp_path):
    session = str(tmp_path / 'empty')
    session and Path(session).mkdir()
    assert _run('check', '--session', session) == 2, '没种哨兵＝无从检查，不许报通过'


def test_canary_init_is_idempotent(tmp_path, capsys):
    session = str(tmp_path / 's')
    assert _run('init', '--session', session) == 0
    t1 = Path(session, 'canary.txt').read_text(encoding='utf-8').splitlines()[0]
    assert _run('init', '--session', session) == 0
    assert Path(session, 'canary.txt').read_text(encoding='utf-8').splitlines()[0] == t1, \
        '重复 init 不换令牌（换了旧会话的哨兵就失效）'


# ============================================================
# L2：引文长度上限（超长告警不阻断）
# ============================================================

def test_overlong_quote_is_flagged_but_not_fatal(tmp_path):
    from verify_quotes import check_quotes

    led = tmp_path / 'ledger'
    led.mkdir()
    long_quote = 'A' * 1300
    claim = {'type': 'claim', 'id': 'c-1',
             'text': f'原文整段搬进来『{long_quote}』', 'topic': 't', 'status': 'pending'}
    (led / 'ledger.jsonl').write_text(json.dumps(claim, ensure_ascii=False) + '\n',
                                      encoding='utf-8')
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'page.txt').write_text(long_quote, encoding='utf-8')
    res = check_quotes(str(led), str(raw))
    assert res['misses'] == [], '逐字命中的超长引文不是 MISS'
    assert len(res['overlong']) == 1, '超长引文必须进告警清单'


def test_normal_length_quote_not_flagged(tmp_path):
    from verify_quotes import check_quotes

    led = tmp_path / 'ledger'
    led.mkdir()
    quote = 'B' * 200
    claim = {'type': 'claim', 'id': 'c-1', 'text': f'正常引文『{quote}』',
             'topic': 't', 'status': 'pending'}
    (led / 'ledger.jsonl').write_text(json.dumps(claim, ensure_ascii=False) + '\n',
                                      encoding='utf-8')
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'page.txt').write_text(quote, encoding='utf-8')
    res = check_quotes(str(led), str(raw))
    assert res['overlong'] == []


# ============================================================
# SKILL.md 流程钉：Phase 0 配置停等 + canary 接线 + L2 声明
# ============================================================

def test_skill_md_phase0_stops_for_configuration():
    skill = (Path(__file__).resolve().parents[2] / 'SKILL.md').read_text(encoding='utf-8')
    assert '本轮到此为止' in skill, '缺配置时必须停下等用户配完，不许问完就接着跑'
    assert '重跑 `--probe` 复核' in skill, '配置完成后必须重跑 probe 复核'


def test_skill_md_wires_canary_and_l2():
    skill = (Path(__file__).resolve().parents[2] / 'SKILL.md').read_text(encoding='utf-8')
    assert 'check --session' in skill and 'canary.py' in skill, '发布门前必须过 canary 检查'
    assert 'DRUX_CANARY_' in skill, '派单模板要有 canary 令牌条款'
    assert '不超过 1200 字' in skill, 'L2 引文长度上限要写进硬声明'
