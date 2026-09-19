"""
Deep Research Ultra v6.6 — 实测缺陷回归测试

全部来自「Linux 命令纠错」深度调研的一次真实端到端跑动：
- D1 effort/preset 归一（见 test_v6.TestEffortPresetMapping）
- D2 reflections 类型契约：research.py 传 list，report.py 要 ReflectionHistory
- D3 _http_get 重试放大：curl_cffi 拿到 HTTP 状态码后贯穿 urllib 再打一轮
- D4 tier 学术白名单缺项：ACL 正式论文集被判 Tier 3
- D5 github-deep-search 长查询整串 AND 致 0 命中且无回落
- D6 ledger 缺「档 B：一手来源 + Lead 反查」判据

运行方式：
    cd scripts
    python -m pytest tests/test_v66_fixes.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# D2 reflections 类型契约
# ============================================================

class TestReflectionsTypeContract:
    """research.py 造的是 list[Reflection]，report.py 契约是 ReflectionHistory，
    reflections.final_coverage 因此抛 AttributeError，HTML 报告直接崩。"""

    def _rounds(self):
        from reflect import Reflection
        return [
            Reflection(round_num=1, coverage_score=0.30,
                       verified_claims_count=3, single_source_count=9,
                       contradictions_count=0),
            Reflection(round_num=2, coverage_score=0.42,
                       verified_claims_count=5, single_source_count=7,
                       contradictions_count=1),
        ]

    def test_normalizer_wraps_plain_list_taking_last_round(self):
        from report import as_reflection_history
        hist = as_reflection_history(self._rounds())
        assert hist.total_rounds == 2
        assert hist.final_coverage == 0.42, 'final_coverage 必须取最后一轮'

    def test_normalizer_is_idempotent_for_history(self):
        from report import as_reflection_history
        from reflect import ReflectionHistory
        hist = as_reflection_history(self._rounds())
        assert isinstance(hist, ReflectionHistory)
        assert as_reflection_history(hist) is hist

    def test_normalizer_passes_through_none(self):
        from report import as_reflection_history
        assert as_reflection_history(None) is None

    def test_html_quality_survives_a_list_of_reflections(self):
        """这是用户实际遇到的崩溃点。"""
        from report import ReportGenerator
        html = ReportGenerator()._html_quality(None, [], None, self._rounds())
        assert '42' in html, f'覆盖率应渲染为 42%，实际:\n{html[:400]}'


# ============================================================
# D3 HTTP 重试放大
# ============================================================

class TestHttpRetryAmplification:
    """_http_get 在 curl_cffi 已拿到 HTTP 状态码后仍贯穿到 urllib 再跑一轮
    max_retries —— 对已返回 429 的端点等于双倍请求量。"""

    def _install_fake_cffi(self, monkeypatch, status, calls):
        import types

        class _Resp:
            def __init__(self, code):
                self.status_code = code
                self.content = b'{}'

        def _get(url, **kw):
            calls.append('cffi')
            if isinstance(status, Exception):
                raise status
            return _Resp(status)

        mod = types.ModuleType('curl_cffi')
        sub = types.ModuleType('curl_cffi.requests')
        sub.get = _get
        mod.requests = sub
        monkeypatch.setitem(sys.modules, 'curl_cffi', mod)
        monkeypatch.setitem(sys.modules, 'curl_cffi.requests', sub)

    def test_http_429_from_cffi_does_not_reach_urllib(self, monkeypatch):
        from engines import fallback
        calls = []
        self._install_fake_cffi(monkeypatch, 429, calls)
        opened = []

        class _Opener:
            def open(self, req, timeout=None):
                opened.append(req)
                raise fallback.urllib.error.URLError('down')

        monkeypatch.setattr(fallback.urllib.request, 'build_opener',
                            lambda *a, **k: _Opener())
        monkeypatch.setattr(fallback.time, 'sleep', lambda s: None)
        assert fallback._http_get('https://api.openalex.org/works', max_retries=3) is None
        assert not opened, f'服务端已回 429，不得再用 urllib 重打：{len(opened)} 次'
        assert calls == ['cffi'] * 3, 'curl_cffi 自身仍按 max_retries 退避重试'

    def test_transport_exception_still_falls_back_to_urllib(self, monkeypatch):
        """TLS 指纹被拦（抛异常）时降级 urllib 是这条链路存在的理由，不得一起砍掉。"""
        from engines import fallback
        calls = []
        self._install_fake_cffi(monkeypatch, OSError('tls blocked'), calls)
        opened = []

        class _Resp:
            headers = {}

            def read(self):
                return b'ok'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _Opener:
            def open(self, req, timeout=None):
                opened.append(req)
                return _Resp()

        monkeypatch.setattr(fallback.urllib.request, 'build_opener',
                            lambda *a, **k: _Opener())
        monkeypatch.setattr(fallback.time, 'sleep', lambda s: None)
        assert fallback._http_get('https://x.test', max_retries=2) == b'ok'
        assert opened, 'curl_cffi 抛异常时仍应尝试 urllib'

    def test_no_sleep_after_the_final_attempt(self, monkeypatch):
        from engines import fallback
        calls = []
        self._install_fake_cffi(monkeypatch, 429, calls)
        slept = []

        class _Opener:
            def open(self, req, timeout=None):
                raise fallback.urllib.error.URLError('down')

        monkeypatch.setattr(fallback.urllib.request, 'build_opener',
                            lambda *a, **k: _Opener())
        monkeypatch.setattr(fallback.time, 'sleep', lambda s: slept.append(s))
        fallback._http_get('https://x.test', max_retries=3)
        assert len(slept) <= 2, f'3 次尝试最多睡 2 次，实际 {len(slept)} 次（末次白等）'


# ============================================================
# D4 学术 Tier 分级
# ============================================================

class TestAcademicTier:
    """ACADEMIC_DOMAINS 缺同行评审域名，ACL 正式论文集落到默认 Tier 3，
    而预印本 arxiv.org 是 Tier 1 —— 分级方向性颠倒。"""

    def test_peer_reviewed_proceedings_are_tier1(self):
        from tier import domain_tier
        for url in ('https://aclanthology.org/2024.acl-long.10.pdf',
                    'https://aclanthology.org/L16-1060/',
                    'https://proceedings.mlr.press/v202/x.html',
                    'https://jmlr.org/papers/v21/20-019.html'):
            assert domain_tier(url) == 1, f'{url} 是同行评审正式出版物'

    def test_openreview_is_tier2(self):
        from tier import domain_tier
        assert domain_tier('https://openreview.net/forum?id=abc') == 2

    def test_preset_key_tables_do_not_drift(self):
        """PRESET_KEYS 与 DEPTH_PRESETS 必须同源，否则新档位会被静默当作未知。"""
        from plan import PRESET_KEYS, DEPTH_TO_EFFORT, EFFORT_TO_DEPTH, PlanGenerator
        assert set(PRESET_KEYS) == set(PlanGenerator.DEPTH_PRESETS)
        assert set(DEPTH_TO_EFFORT) == set(PRESET_KEYS)
        assert set(EFFORT_TO_DEPTH.values()) == set(PRESET_KEYS)


# ============================================================
# D5 GitHub 长查询
# ============================================================

class TestGithubQueryNormalization:
    """长自然语言查询整串进 q=，GitHub 按 AND 匹配 name/description/readme，
    恒 0 命中且无回落。"""

    LONG = 'zsh bash command spelling correction auto-correct mistyped shell commands'

    def test_long_natural_language_query_is_shortened(self):
        from engines.github_deep_search import normalize_repo_query
        q = normalize_repo_query(self.LONG)
        assert len(q.split()) <= 3, f'仍过长: {q!r}'
        assert 'command' in q or 'correction' in q, f'高信号词被丢光: {q!r}'

    def test_short_query_is_left_alone(self):
        from engines.github_deep_search import normalize_repo_query
        assert normalize_repo_query('spelling corrector') == 'spelling corrector'

    def test_all_buckets_use_normalized_query_without_doubling_calls(self, monkeypatch):
        """GitHub 对长 AND 查询恒为 0，先按原查询打 4 桶再回落等于白烧配额
        （与 D3 同一课：不要把重试当补救）。首轮即归一，桶请求次数不变。"""
        from engines.github_deep_search import GitHubDeepSearchEngine
        eng = GitHubDeepSearchEngine()
        seen = []

        def _fake_bucket(query, **kw):
            seen.append(query)
            return []

        monkeypatch.setattr(eng, '_search_bucket', _fake_bucket)
        monkeypatch.setattr(eng, '_search_dependents', lambda *a, **k: [])
        monkeypatch.setattr(eng, '_search_awesome', lambda *a, **k: [])
        eng.search(self.LONG, max_results=8)
        assert len(seen) == len(eng.STAR_BUCKETS), \
            f'桶请求次数应仍为 {len(eng.STAR_BUCKETS)}，实际 {len(seen)}（配额被翻倍）'
        assert all(len(s.split()) <= 3 for s in seen), \
            f'全部桶须用归一后的短查询: {seen}'


# ============================================================
# D6 档 B：一手来源 + Lead 反查
# ============================================================

class TestLedgerPrimaryVerification:
    """归属型 claim（某仓库/论文自身的陈述）无法用「≥2 独立注册域」验证，
    但必须记录 Lead 做了什么反查，否则 verified 就是可任意填的后门。"""

    def _led(self, tmp_path, url='https://github.com/nvbn/thefuck'):
        from ledger import ResearchLedger
        led = ResearchLedger(str(tmp_path / 's')).init()
        c = led.add_claim('nvbn/thefuck README 现状：纯确定性规则引擎', topic='生态')
        led.add_source(c['id'], url, title='thefuck 仓库页', tier=2)
        return led, c['id']

    def test_verify_primary_promotes_and_records_method(self, tmp_path):
        led, cid = self._led(tmp_path)
        ok = led.verify_primary(
            [cid], check_url='https://api.github.com/repos/nvbn/thefuck',
            check_title='GitHub REST API 响应', method='repo_health')
        assert ok == 1
        cl = [c for c in led.claims() if c['id'] == cid][0]
        assert cl['status'] == 'verified'
        assert cl['evidence_tier'] == 'B'
        assert cl['verify_method'] == 'repo_health'
        assert len(led.sources_for_claim(cid)) == 2, '反查来源必须入账'

    def test_refuses_check_url_from_an_unrelated_domain(self, tmp_path):
        """反查必须打在同一个制品上：claim 说的是 thefuck 仓库，
        拿一篇无关博客当"反查"就是自证后门。"""
        led, cid = self._led(tmp_path)
        assert led.verify_primary(
            [cid], check_url='https://someblog.example/post',
            check_title='x', method='web') == 0
        assert [c for c in led.claims() if c['id'] == cid][0]['status'] == 'pending'

    def test_refuses_claim_without_any_source(self, tmp_path):
        from ledger import ResearchLedger
        led = ResearchLedger(str(tmp_path / 's2')).init()
        c = led.add_claim('无来源断言', topic='生态')
        assert led.verify_primary([c['id']], check_url='https://x.test/a',
                                  check_title='t', method='m') == 0

    def test_same_registered_domain_counts_as_primary_artifact(self, tmp_path):
        """github.com 仓库页 + api.github.com 响应同属一个注册域，
        正是档 B 允许的组合（对同一制品的第二条检索通道）。"""
        led, cid = self._led(tmp_path)
        assert led.verify_primary(
            [cid], check_url='https://api.github.com/repos/nvbn/thefuck',
            check_title='api', method='repo_health') == 1


class TestGithubArtifactFamilyAlias:
    """github.com blob 页与 raw.githubusercontent.com 字节流是同一制品的两个入口，
    注册域不同（github.com vs githubusercontent.com），按纯注册域判同会误拒真实反查。"""

    def test_raw_githubusercontent_counts_as_same_artifact_family(self, tmp_path):
        from ledger import ResearchLedger
        led = ResearchLedger(str(tmp_path / 's')).init()
        c = led.add_claim('clap 用 strsim::jaro 而非 Levenshtein', topic='参数层')
        led.add_source(c['id'], 'https://github.com/clap-rs/clap/blob/master/x.rs')
        assert led.verify_primary(
            [c['id']],
            check_url='https://raw.githubusercontent.com/clap-rs/clap/master/x.rs',
            check_title='raw 字节流', method='source-read') == 1

    def test_non_github_domain_still_rejected(self, tmp_path):
        from ledger import ResearchLedger
        led = ResearchLedger(str(tmp_path / 's2')).init()
        c = led.add_claim('clap 用 jaro', topic='参数层')
        led.add_source(c['id'], 'https://github.com/clap-rs/clap/blob/master/x.rs')
        assert led.verify_primary([c['id']], check_url='https://gitlab.com/a/b',
                                  check_title='t', method='m') == 0


class TestGateCitationEvidenceAlignment:
    """发布门主指标换口径：只阻断"报告据以立论但没有验证"的 claim，
    全量覆盖率降级为告警 —— 因为账本分母里混着过程记录。"""

    def _led(self, tmp_path, cited_status='pending'):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        a = L.add_claim('结论A', '主题A', 'verified', 'general', 0.9)
        b = L.add_claim('结论B', '主题A', cited_status, 'general', 0.5)
        # 两条各给两个不同注册域来源：满足既有校验 2b（verified 需 ≥2 独立来源），
        # 否则本测试会被 2b 拦截，测不到 2c 的行为。
        L.add_source(a['id'], 'https://arxiv.org/0', tier=1)
        L.add_source(a['id'], 'https://aclanthology.org/a0', tier=1)
        L.add_source(b['id'], 'https://arxiv.org/100', tier=1)
        L.add_source(b['id'], 'https://aclanthology.org/a100', tier=1)
        for i in range(20):          # 一堆未验证的过程记录，压低全量覆盖率
            # 挂在同一主题下：不让"该主题零 verified"这条既有规则串扰本测试
            c = L.add_claim(f'笔记{i}', '主题A', 'pending', 'general', 0.4)
            L.add_source(c['id'], f'https://blog.example.com/{i}', tier=3)
        return L

    def _report(self, tail=''):
        # [1] 属 verified 的结论A；[3] 属状态可变的结论B（其 primary_index=3）
        return f"""# 报告
## 执行摘要
结论A [1]；结论B [3]{tail}。
## 调研范围与方法
多源检索。
## 结论与建议
结论良好。
## 来源
[1] 来源1 https://arxiv.org/0
[3] 来源3 https://arxiv.org/100
"""

    def test_cited_unverified_claim_blocks(self, tmp_path):
        from validate_report import validate_report
        r = validate_report(self._report(), ledger=self._led(tmp_path))
        assert r.passed is False
        assert any('被报告引用但没有验证' in i for i in r.issues), r.issues
        assert r.stats['unverified_cited_claims'] == 1

    def test_cited_conflict_claim_is_allowed(self, tmp_path):
        """冲突本身是结论。拦掉 conflict 等于禁止报告矛盾，方向反了。"""
        from validate_report import validate_report
        r = validate_report(self._report(), ledger=self._led(tmp_path, 'conflict'))
        assert r.passed is True, r.issues
        assert r.stats['unverified_cited_claims'] == 0

    def test_cited_unverified_claim_with_warning_marker_passes(self, tmp_path):
        from validate_report import validate_report
        r = validate_report(self._report('（⚠️ 单源待补）'), ledger=self._led(tmp_path))
        assert r.passed is True, r.issues
        assert r.stats['cited_pending_marked'] == 1
        assert any('已标 ⚠️' in w for w in r.warnings), r.warnings

    def test_low_full_coverage_alone_only_warns(self, tmp_path):
        from validate_report import validate_report
        r = validate_report(self._report('（⚠️ 单源待补）'), ledger=self._led(tmp_path),
                            min_coverage=0.6)
        assert r.stats['coverage'] < 0.6
        assert any('覆盖率' in w for w in r.warnings), r.warnings
        assert not any('覆盖率' in i for i in r.issues), \
            f'全量覆盖率不得再阻断交付：{r.issues}'


# ============================================================
# D8 ledger 写命令静默建空账本
# ============================================================
class TestLedgerWriteRequiresExistingLedger:
    """--session 指错目录时，升/降级必须报错，不能建空账本后返回"0 条"。

    实测踩过：把 session 父目录传给 verify-primary，init() 静默建出
    空 ledger.jsonl + claims/ + sources/，调用方只看到"升级 0 条"，
    完全无从诊断路径写错。
    """

    def _run(self, argv, tmp_path):
        import subprocess
        script = Path(__file__).parent.parent / 'ledger.py'
        return subprocess.run(
            [sys.executable, str(script)] + argv,
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', cwd=str(tmp_path))

    def test_missing_ledger_raises_not_creates(self, tmp_path):
        from ledger import ResearchLedger
        wrong = tmp_path / 'linux-cmd-correction'      # 少写了 /ledger
        import pytest
        with pytest.raises(FileNotFoundError):
            ResearchLedger(str(wrong)).require()
        assert not wrong.exists(), 'require() 不得顺手创建目录或空账本'

    def test_require_passes_on_initialized_ledger(self, tmp_path):
        from ledger import ResearchLedger
        ok = ResearchLedger(str(tmp_path)).init()
        assert ok.require() is ok

    def test_cli_set_status_on_wrong_session_fails_loudly(self, tmp_path):
        r = self._run(['set-status', '--session', str(tmp_path / 'nope'),
                       '--claim-id', 'c-1', '--status', 'verified'], tmp_path)
        assert r.returncode != 0, r.stdout
        assert '账本不存在' in (r.stderr + r.stdout), r.stderr
        assert not (tmp_path / 'nope' / 'ledger.jsonl').exists()

    def test_cli_verify_primary_on_wrong_session_fails_loudly(self, tmp_path):
        r = self._run(['verify-primary', '--session', str(tmp_path / 'nope2'),
                       '--claim-id', 'c-1',
                       '--check-url', 'https://docs.github.com/x'], tmp_path)
        assert r.returncode != 0, r.stdout
        assert '账本不存在' in (r.stderr + r.stdout), r.stderr


# ============================================================
# D9 校验 2b 与「档 B」判据自相矛盾
# ============================================================
class TestGateTierBExemptsCrossSourceRule:
    """档 B（一手来源 + Lead 反查）的 claim 不该再被"≥2 独立来源"卡住。

    归属型断言的对象就是那一个制品，要求第二个注册域来交叉验证它自身是判据
    错配；v6.6 在 ledger 里开了档 B，但 v6.3 的校验 2b 不认识它，
    实测把刚 verify-primary 升上来的 claim 又拦成 issue。
    """

    def _led(self, tmp_path, verify_method='repo_health'):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        url = 'https://docs.github.com/en/copilot/responsible-use/copilot-in-the-cli'
        c = L.add_claim('GitHub 官方文档告诫 CLI 需授权', '主题A', 'pending', 'general', 0.9)
        L.add_source(c['id'], url, title='Responsible use of Copilot in the CLI', tier=2)
        L.verify_primary([c['id']], url,
                         check_title='Responsible use of Copilot in the CLI',
                         method=verify_method)
        if not verify_method:      # 构造"自称档 B 但无反查记录"的越权样本
            entries = list(L._all())
            L.entries_path.write_text('', encoding='utf-8')
            for e in entries:
                if e.get('type') == 'claim':
                    e['evidence_tier'] = 'B'
                    e['verify_method'] = ''
                import json as _j
                with open(L.entries_path, 'a', encoding='utf-8') as f:
                    f.write(_j.dumps(e, ensure_ascii=False) + '\n')
        return L

    def _report(self):
        return """# 报告
## 执行摘要
官方文档要求执行前授权 [1]。
## 调研范围与方法
多源检索。
## 结论与建议
结论良好。
## 来源
[1] Responsible use of Copilot in the CLI https://docs.github.com/en/copilot/responsible-use/copilot-in-the-cli
"""

    def test_tier_b_claim_with_recheck_passes(self, tmp_path):
        from validate_report import validate_report
        r = validate_report(self._report(), ledger=self._led(tmp_path))
        assert r.stats['weak_verified_claims'] == 0, r.issues
        assert r.passed is True, r.issues

    def test_tier_b_claim_without_recheck_still_blocks(self, tmp_path):
        """无 method 不得享受豁免，否则档 B 成了想升就升的后门。"""
        from validate_report import validate_report
        r = validate_report(self._report(), ledger=self._led(tmp_path, verify_method=''))
        assert r.stats['weak_verified_claims'] == 1
        assert any('独立来源不足' in i for i in r.issues), r.issues


# ============================================================
# D10 「引用编号存在重复」必亮误报
# ============================================================
class TestGateCitationNumberConflict:
    """重复引用同一编号是正常写作；编号在登记表里指向两个 URL 才是真缺陷。"""

    def _led(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        for i, (url, dom) in enumerate(
                [('https://arxiv.org/0', 'arxiv.org'),
                 ('https://aclanthology.org/a0', 'aclanthology.org')]):
            c = L.add_claim(f'结论{i}', '主题A', 'verified', 'general', 0.9)
            L.add_source(c['id'], url, tier=1)
            L.add_source(c['id'], f'https://{dom}/x{i}', tier=1)
        return L

    def _report(self, registry):
        return f"""# 报告
## 执行摘要
同一来源反复引用 [1][1][2]。
## 调研范围与方法
多源检索。
## 结论与建议
结论良好。
## 来源
{registry}
"""

    def test_repeated_citation_of_same_number_no_longer_warns(self, tmp_path):
        from validate_report import validate_report
        reg = ('| [1] | https://arxiv.org/0 | arxiv.org | T1 | 论文一 |\n'
               '| [2] | https://aclanthology.org/a0 | aclanthology.org | T1 | 论文二 |')
        r = validate_report(self._report(reg), ledger=self._led(tmp_path))
        assert not any('重复' in w for w in r.warnings), r.warnings
        assert r.stats['citation_number_conflicts'] == 0

    def test_number_mapped_to_two_urls_in_registry_warns(self, tmp_path):
        from validate_report import validate_report
        reg = ('| [1] | https://arxiv.org/0 | arxiv.org | T1 | 论文一 |\n'
               '| [1] | https://blog.example.com/other | blog.example.com | T3 | 串号 |')
        r = validate_report(self._report(reg), ledger=self._led(tmp_path))
        assert r.stats['citation_number_conflicts'] == 1
        assert any('编号' in w and '不同来源' in w for w in r.warnings), r.warnings


# ============================================================
# D11 claim 文本无法就地更正
# ============================================================
class TestLedgerAmendClaimText:
    """反查时发现 claim 原文有一句写错，只能改文本，不能只加 note。

    实测：argparse 那条 claim 写"color 从 False 翻到 True"，逐行读两个分支的
    `__init__` 签名都是 `color=True`（翻的是 docstring 与代码不一致，不是版本）。
    账本只有 set_status 改状态，错误原文会作为 verified 结论永久留在交付物里。
    """

    def test_set_status_can_amend_text_and_keeps_note(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('argparse color 从 False 翻到 True', '参数层')
        L.set_status([c['id']], 'verified', note='Lead 反查（source-read）：u')
        n = L.set_status([c['id']], 'verified',
                         text='argparse 两分支签名均 color=True，docstring 仍写 False')
        assert n == 1
        got = [e for e in L.export_json()['claims'] if e['id'] == c['id']][0]
        assert '两分支签名均 color=True' in got['text']
        assert '翻到 True' not in got['text']
        assert got['note'].startswith('Lead 反查'), '不传 --note 时应保留反查留痕'
        assert got.get('amended_at')

    def test_text_only_amend_leaves_status_untouched(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('原文', '参数层', 'conflict')
        L.set_status([c['id']], 'conflict', text='改后原文')
        got = [e for e in L.export_json()['claims'] if e['id'] == c['id']][0]
        assert got['status'] == 'conflict' and got['text'] == '改后原文'


# ============================================================
# D12 verify-primary 批量升级会把一个制品的证据记到别的 claim 上
# ============================================================
class TestVerifyPrimaryArtifactBinding:
    """只比注册域不够：一次传 7 个 arXiv claim + 1 个 check-url，域全对，
    但其中 6 条会把"另一篇论文存在"当成自己的反查凭据——门与账本一起被污染。"""

    def _L(self, tmp_path):
        from ledger import ResearchLedger
        return ResearchLedger(str(tmp_path / 'ledger')).init()

    def test_batch_rejects_claims_whose_artifact_differs(self, tmp_path):
        from ledger import ResearchLedger, ResearchLedger as R  # noqa: F401
        L = self._L(tmp_path)
        a = L.add_claim('NL2Bash 说了 X', 'LLM', 'pending')
        b = L.add_claim('NaSh 说了 Y', 'LLM', 'pending')
        L.add_source(a['id'], 'https://arxiv.org/abs/1802.08979')
        L.add_source(b['id'], 'https://arxiv.org/abs/2506.13028')
        changed = L.verify_primary(
            [a['id'], b['id']], 'https://arxiv.org/abs/1802.08979',
            check_title='NL2Bash', method='abs-page')
        assert changed == 1, '只应升级真正反查过的那一条'
        st = {c['id']: c['status'] for c in L.export_json()['claims']}
        assert st[a['id']] == 'verified' and st[b['id']] == 'pending'

    def test_github_blob_and_raw_are_same_artifact(self, tmp_path):
        L = self._L(tmp_path)
        c = L.add_claim('help.c 的延时换算', '参数层', 'pending')
        L.add_source(c['id'], 'https://github.com/git/git/blob/master/help.c')
        assert L.verify_primary([c['id']],
                                'https://raw.githubusercontent.com/git/git/'
                                'master/help.c', check_title='help.c',
                                method='source-read') == 1

    def test_different_branch_is_a_different_artifact(self, tmp_path):
        """3.14 的源码不能当作 main 默认值的凭据——版本差异正是结论本身。"""
        L = self._L(tmp_path)
        c = L.add_claim('main 分支 argparse 默认开建议', '参数层', 'pending')
        L.add_source(c['id'], 'https://github.com/python/cpython/blob/3.14/Lib/argparse.py')
        assert L.verify_primary([c['id']],
                               'https://raw.githubusercontent.com/python/cpython/'
                               'main/Lib/argparse.py', check_title='argparse',
                               method='source-read') == 0


# ============================================================
# D13 --env-check 不提示 OpenAlex polite pool
# ============================================================
class TestEnvCheckOpenAlexMailto:
    """引擎早就支持 OPENALEX_MAILTO，但 --env-check 从不提，
    用户只在 8 路并发撞 429 之后才知道有这档配置。"""

    def test_openalex_mailto_is_declared_optional_env(self):
        import env_check
        assert 'OPENALEX_MAILTO' in env_check.OPTIONAL_ENVS
        for profile in ('academic', 'full'):
            assert 'OPENALEX_MAILTO' in env_check.PROFILES[profile]['envs'], profile

    def test_missing_mailto_hint_names_the_consequence(self, monkeypatch):
        import env_check
        monkeypatch.delenv('OPENALEX_MAILTO', raising=False)
        ok, detail = env_check._check_env('OPENALEX_MAILTO')
        assert ok is False
        assert 'polite pool' in detail and '429' in detail, detail

    def test_configured_mailto_keeps_normal_detail(self, monkeypatch):
        import env_check
        monkeypatch.setenv('OPENALEX_MAILTO', 'me@example.org')
        ok, detail = env_check._check_env('OPENALEX_MAILTO')
        assert ok is True and 'me@example' in detail
