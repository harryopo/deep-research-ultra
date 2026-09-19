"""
Deep Research Ultra v6.0 — 新增模块单元测试

覆盖 v6.0 模块与增强：
- tier.py: domain_tier / tier_label / tier_penalty / 覆盖表
- ledger.py: ResearchLedger（init/append/merge/status/export，多子Agent并发写）
- panel.py: PanelReviewer（perspectives / review_outline / review_draft / supplement_questions）
- validate_report.py: validate_report（引用一致性/覆盖率/章节/Tier4占比/摘要长度）
- plan.py: 多视角注入 / evidence_count / unanswered_questions
- reflect.py: evidence_sufficiency / new_claim_marginal 停止信号
- score.py: Tier 加权 / has_low_quality_ratio

运行方式：
    cd scripts
    python -m pytest tests/ -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# tier.py
# ============================================================

class TestTier:
    """来源 Tier 分级"""

    def test_gov_edu_academic_tier1(self):
        from tier import domain_tier
        assert domain_tier('https://www.gov.cn/xinwen') == 1
        assert domain_tier('https://www.whitehouse.gov/x') == 1
        assert domain_tier('https://arxiv.org/abs/2402.14207') == 1
        assert domain_tier('https://www.stanford.edu/x') == 1
        assert domain_tier('https://content.example.edu.cn/x') == 1

    def test_authoritative_tier2(self):
        from tier import domain_tier
        assert domain_tier('https://docs.github.com/x') == 2
        assert domain_tier('https://www.reuters.com/x') == 2

    def test_community_tier4(self):
        from tier import domain_tier
        assert domain_tier('https://www.zhihu.com/question/1') == 4
        assert domain_tier('https://www.reddit.com/r/x') == 4

    def test_unknown_tier3_and_http_downgrade(self):
        from tier import domain_tier
        assert domain_tier('https://unknown-blog-abc.example.com/x') == 3
        # http 无 TLS → 降级
        assert domain_tier('http://old.example.edu.cn/x') == 2  # Tier1 → 2

    def test_override_persist(self, tmp_path, monkeypatch):
        import tier
        overrides_file = tmp_path / 'tier_overrides.json'
        monkeypatch.setattr(tier, '_OVERRIDES_FILE', overrides_file)
        tier.add_override('mycorp.example', 1)
        assert tier.domain_tier('https://mycorp.example/docs') == 1


# ============================================================
# ledger.py
# ============================================================

class TestLedger:
    """证据账本"""

    def test_init_structure(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        assert (tmp_path / 'ledger' / 'ledger.jsonl').exists()
        assert (tmp_path / 'ledger' / 'claims').is_dir()
        assert (tmp_path / 'ledger' / 'sources').is_dir()

    def test_add_claim_and_source(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('主流架构', 'topic-a', 'verified', 'domain_expert', 0.9)
        assert c['id'].startswith('c-')
        s = L.add_source(c['id'], 'https://arxiv.org/x', title='方案', tier=1)
        assert s['tier'] == 1
        # 未指定 tier 时自动分级
        s2 = L.add_source(c['id'], 'https://www.gov.cn/x')
        assert s2['tier'] == 1

    def test_status_sufficient(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('结论', 'topic-a', 'verified', 'general', 0.8)
        L.add_source(c['id'], 'https://arxiv.org/1')
        L.add_source(c['id'], 'https://arxiv.org/2')
        st = L.status('topic-a')
        assert st['independent_sources'] == 2
        assert st['sufficient'] is True
        # 单源 topic → 不充分
        c2 = L.add_claim('单源', 'topic-b', 'verified', 'general', 0.5)
        L.add_source(c2['id'], 'https://arxiv.org/3')
        assert L.status('topic-b')['sufficient'] is False

    def test_merge_subagent_artifacts(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        sub = tmp_path / 'sub'
        sub.mkdir()
        (sub / 'a.jsonl').write_text(
            json.dumps({'type': 'claim', 'id': 'c-sub1', 'text': '子A发现',
                        'topic': 't', 'status': 'verified', 'perspective': 'p', 'confidence': 0.6})
            + '\n', encoding='utf-8')
        (sub / 'a.jsonl').write_text(
            json.dumps({'type': 'claim', 'id': 'c-sub1', 'text': '子A发现',
                        'topic': 't', 'status': 'verified', 'perspective': 'p', 'confidence': 0.6})
            + '\n'
            + json.dumps({'type': 'source', 'claim_id': 'c-sub1', 'url': 'https://a.com/1',
                          'title': 'src', 'tier': 2}) + '\n', encoding='utf-8')
        c, s = L.merge(str(sub))
        assert c == 1 and s == 1
        # 再 merge 一次 → 幂等去重
        c2, s2 = L.merge(str(sub))
        assert c2 == 0 and s2 == 0

    def test_export_md(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('结论', 'topic-a', 'verified', 'general', 0.8)
        L.add_source(c['id'], 'https://arxiv.org/1', title='Attention')
        md = L.export_md()
        assert '## topic-a' in md
        assert '格式' in md or 'Attention' in md


# ============================================================
# panel.py
# ============================================================

class TestPanel:
    """专家团评审清单"""

    def test_default_perspectives_roles(self):
        from panel import PanelReviewer
        ps = PanelReviewer().default_perspectives()
        assert len(ps) == 5
        labels = [p['label'] for p in ps]
        assert '域专家' in labels and '怀疑者（红队）' in labels

    def test_review_outline_contract(self):
        from panel import PanelReviewer
        out = PanelReviewer().review_outline('1. 主题A', ['skeptic', 'practitioner'])
        assert set(out['perspectives'][0].keys()) == {'role', 'label', 'focus', 'questions'}
        assert all(q for p in out['perspectives'] for q in p['questions'])

    def test_review_draft_findings(self):
        from panel import PanelReviewer
        d = PanelReviewer().review_draft('草稿内容', 'domain_expert')
        assert set(d.keys()) == {'role', 'label', 'focus', 'findings', '_note'}
        assert all(f['type'] in ('gap', 'contradiction', 'evidence_needed')
                   for f in d['findings'])
        assert all('action' in f for f in d['findings'])


# ============================================================
# validate_report.py
# ============================================================

class TestValidateReport:
    """发布前校验门"""

    def _ledger_with_sources(self, tmp_path, n=3):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c1 = L.add_claim('结论A', '主题A', 'verified', 'general', 0.9)
        c2 = L.add_claim('结论B', '主题A', 'verified', 'general', 0.8)
        for i in range(n):
            L.add_source(c1['id'], f'https://arxiv.org/{i}', tier=1)
        for i in range(n):
            L.add_source(c2['id'], f'https://arxiv.org/{i+100}', tier=1)
        return L

    def _good_report(self):
        return '''# 报告
## 执行摘要
结论A [1] 与结论B [2]。
## 调研范围与方法
多源检索。
## 结论与建议
结论良好。
## 来源
[1] 来源1 https://arxiv.org/0
[2] 来源2 https://arxiv.org/100
'''

    def test_pass(self, tmp_path):
        from validate_report import validate_report
        L = self._ledger_with_sources(tmp_path)
        r = validate_report(self._good_report(), ledger=L)
        assert r.passed is True

    def test_missing_section_fails(self, tmp_path):
        from validate_report import validate_report
        L = self._ledger_with_sources(tmp_path)
        bad = self._good_report().replace('## 来源', '## 附录')
        r = validate_report(bad, ledger=L)
        assert r.passed is False
        assert any('来源' in i for i in r.issues)

    def test_citation_out_of_range_fails(self, tmp_path):
        from validate_report import validate_report
        L = self._ledger_with_sources(tmp_path)
        bad = self._good_report().replace('[2]', '[99]')
        r = validate_report(bad, ledger=L)
        assert r.passed is False
        assert any('越界' in i for i in r.issues)

    def test_low_coverage_warns(self, tmp_path):
        """v6.7 口径变更：全量覆盖率不再阻断交付，只告警。
        真正阻断的是「报告引用了但没验证」的 claim，见 test_v66_fixes
        ::TestGateCitationEvidenceAlignment。"""
        from validate_report import validate_report
        L = self._ledger_with_sources(tmp_path)          # 被引用的两条都 verified
        for i in range(5):                                # 过程记录压低全量覆盖率
            L.add_claim(f'过程记录{i}，报告未引用', '主题A', 'pending', 'general', 0.5)
        r = validate_report(self._good_report(), ledger=L, min_coverage=0.6)
        assert r.stats['coverage'] < 0.6, r.stats['coverage']
        assert r.passed is True, r.issues
        assert any('覆盖率' in w for w in r.warnings), r.warnings

    def test_low_quality_warning(self, tmp_path):
        from validate_report import validate_report
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('结论', '主题A', 'verified', 'general', 0.8)
        for i in range(4):
            L.add_source(c['id'], f'http://junk-{i}.example.com/x', tier=4)
        r = validate_report(self._good_report(), ledger=L)
        assert '告警' in str(r.warnings) or '低质源' in str(r.warnings)


# ============================================================
# plan.py（v6.0 增强）
# ============================================================

class TestPlanV6:
    """多视角注入 + unanswered_questions"""

    def test_perspectives_injected_by_default(self):
        from plan import PlanGenerator, DEFAULT_PERSPECTIVES
        plan = PlanGenerator().generate_plan('测试主题', depth='quick')
        assert plan.issue_tree
        assert plan.issue_tree[0].perspectives == DEFAULT_PERSPECTIVES

    def test_perspectives_disabled(self):
        from plan import PlanGenerator
        plan = PlanGenerator().generate_plan('测试主题', depth='quick', perspectives=[])
        assert plan.issue_tree[0].perspectives == []

    def test_perspectives_custom(self):
        from plan import PlanGenerator
        plan = PlanGenerator().generate_plan('测试主题', depth='quick', perspectives=['skeptic'])
        assert plan.issue_tree[0].perspectives == ['skeptic']

    def test_unanswered_questions_populated(self):
        from plan import PlanGenerator
        plan = PlanGenerator().generate_plan('测试主题', depth='quick')
        assert plan.unanswered_questions
        assert len(plan.unanswered_questions) == len(plan.get_leaf_questions())


# ============================================================
# reflect.py（v6.0 增强）
# ============================================================

class TestReflectV6:
    """证据充分性 / 边际 claim 收敛"""

    def test_insufficient_topics_continue(self, tmp_path):
        from reflect import Reflector
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('单源结论', '主题A', 'verified', 'general', 0.6)
        L.add_source(c['id'], 'https://arxiv.org/1', tier=1)  # 仅 1 独立来源
        plan = type('P', (), {'dimensions': ['主题A'], 'issue_tree': [],
                              'get_leaf_questions': lambda self: []})()
        ref = Reflector().reflect(plan, [], 0, None, ledger=L)
        assert '主题A' in ref.insufficient_topics
        assert ref.should_drill_down is True  # 证据不足 → 继续

    def test_low_quality_sources_reported(self, tmp_path):
        from reflect import Reflector
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('结论', '主题A', 'verified', 'general', 0.8)
        L.add_source(c['id'], 'https://arxiv.org/1', tier=1)
        L.add_source(c['id'], 'http://junk.example.com/x', tier=4)
        plan = type('P', (), {'dimensions': ['主题A'], 'issue_tree': [],
                              'get_leaf_questions': lambda self: []})()
        ref = Reflector().reflect(plan, [], 0, None, ledger=L)
        assert any('junk' in u for u in ref.low_quality_sources)

    def test_marginal_convergence(self):
        from reflect import Reflector
        plan = type('P', (), {'dimensions': [], 'issue_tree': [],
                              'get_leaf_questions': lambda self: []})()
        # 覆盖率 0.6（达标线之上但低于阈值）+ 无空白 + 边际率 0.1 → 收敛停止
        r = Reflector()
        ok, reason, _ = r._should_continue(0, 0.6, [], 20,
                                           insufficient_topics=None, new_claim_marginal=0.1)
        assert ok is False
        assert '边际收益低' in reason or '收敛' in reason


# ============================================================
# score.py（v6.0 增强）
# ============================================================

class TestScoreV6:
    """Tier 加权 + 低质源占比"""

    def _score(self, url):
        from score import CraapScorer
        return CraapScorer().score({'title': 't', 'url': url, 'content': 'c' * 10,
                                    'published_date': '2026-01-01'}, query='t')

    def test_tier_field(self):
        s1 = self._score('https://www.gov.cn/x')
        s2 = self._score('http://junk-zz.example.com/x')
        assert s1['tier'] == 1 and s1['tier_label'] == '官方/学术'
        assert s2['tier'] == 4

    def test_tier_adjustment(self):
        s1 = self._score('https://www.gov.cn/x')
        s4 = self._score('http://junk-zz.example.com/x')
        assert s1['total'] > s4['total']  # Tier1 加权高于 Tier4

    def test_has_low_quality_ratio(self):
        from score import has_low_quality_ratio
        from score import CraapScorer
        scorer = CraapScorer()
        r1 = {'title': 'a', 'url': 'http://junk-1.example.com/x', 'content': 'x' * 5,
              'published_date': '2026-01-01'}
        r2 = {'title': 'b', 'url': 'https://arxiv.org/x', 'content': 'y' * 5,
              'published_date': '2026-01-01'}
        scored = [r1, r2]
        for r in scored:
            r['craap_score'] = scorer.score(r, 'x')
        assert has_low_quality_ratio(scored, 0.5) is True
        assert has_low_quality_ratio([r2], 0.3) is False


# ============================================================
# env_check.py（v6.1 环境分级门控）
# ============================================================

class TestEnvCheck:
    """环境分级清单 + 验证器"""

    def test_profiles_defined(self):
        from env_check import PROFILES
        for p in ('minimal', 'opensource', 'academic', 'full'):
            assert p in PROFILES
            assert 'desc' in PROFILES[p]

    def test_opensource_ready_without_optional(self, monkeypatch):
        from env_check import run_env_check
        # 核心必备通过（engines 真实可导入）；可选项缺失仅告警
        monkeypatch.setattr('env_check.shutil.which', lambda name: 'C:\\python.exe')
        monkeypatch.setattr('env_check._check_skill',
                            lambda name: (name == 'oss-finder', 'OK' if name == 'oss-finder' else 'missing'))
        monkeypatch.setattr('env_check._check_net', lambda host, timeout=3.0: (True, 'OK'))
        r = run_env_check('opensource', include_net=True)
        assert r.ready is True          # 可选缺失不阻断
        assert r.warnings               # GITHUB_TOKEN/agent-reach 等为告警

    def test_missing_core_blocks(self, monkeypatch):
        from env_check import run_env_check
        monkeypatch.setattr('env_check.shutil.which', lambda name: None)   # python 缺失 → 阻断
        monkeypatch.setattr('env_check._check_skill', lambda name: (True, 'OK'))
        monkeypatch.setattr('env_check._check_net', lambda host, timeout=3.0: (True, 'OK'))
        r = run_env_check('minimal', include_net=False)
        assert r.ready is False
        assert any(c.name == 'python' for c in r.missing)


# ============================================================
# engines/platform_engines.py（v6.1 国内开源平台）
# ============================================================

class TestPlatformEngines:
    """Gitee / ModelScope 引擎（mock 网络，不依赖外网）

    真实性契约（v6.5）：实测 Gitee v5 搜索端点匿名返回 `[]`、带无效 token 返回 401，
    ModelScope 的 dolphin 列表端点已 404 —— 引擎必须如实上报"拿不到数据"，
    不能伪装成可用（旧实现把空结果当 None、把域名可达当可用，导致 --list 全绿）。
    """

    def _mock_get_json(self, monkeypatch, payload):
        import engines.platform_engines as pe
        monkeypatch.setattr(pe, '_http_get_json', lambda url: payload)
        monkeypatch.setattr(pe, '_host_reachable', lambda host, port=443, timeout=3.0: True)

    def test_gitee_without_token_is_unavailable(self, monkeypatch):
        from engines.platform_engines import GiteeEngine
        self._mock_get_json(monkeypatch, {'items': []})
        monkeypatch.delenv('GITEE_TOKEN', raising=False)
        assert GiteeEngine().is_available() is False

    def test_gitee_with_token_sends_access_token(self, monkeypatch):
        from engines.platform_engines import GiteeEngine
        import engines.platform_engines as pe
        seen = {}

        def fake_get(url):
            seen['url'] = url
            return [{'full_name': 'oschina/x', 'html_url': 'https://gitee.com/oschina/x'}]

        monkeypatch.setattr(pe, '_http_get_json', fake_get)
        monkeypatch.setattr(pe, '_host_reachable', lambda host, port=443, timeout=3.0: True)
        monkeypatch.setenv('GITEE_TOKEN', 'tok123')
        engine = GiteeEngine()
        assert engine.is_available() is True
        results = engine.search('向量数据库', max_results=3)
        assert 'access_token=tok123' in seen['url']
        assert results and results[0].source == 'gitee'
        assert results[0].title == 'oschina/x'

    def test_gitee_empty_array_means_zero_results(self, monkeypatch):
        """裸数组空响应 ≠ 引擎不可用：必须返回 []（空结果），不得折叠成 None"""
        from engines.platform_engines import GiteeEngine
        self._mock_get_json(monkeypatch, [])
        monkeypatch.setenv('GITEE_TOKEN', 'tok123')
        assert GiteeEngine().search('x') == []

    def test_modelscope_has_no_keyword_search(self, monkeypatch):
        """无关键词搜索端点 → 不声明 search 能力，关键词查询返回空而非假结果"""
        from engines.platform_engines import ModelScopeEngine
        self._mock_get_json(monkeypatch, {'Code': 200, 'Data': {}})
        engine = ModelScopeEngine()
        assert engine.has_capability('search') is False
        assert engine.search('Qwen') == []

    def test_modelscope_exact_model_id_lookup(self, monkeypatch):
        from engines.platform_engines import ModelScopeEngine
        self._mock_get_json(monkeypatch, {
            'Code': 200,
            'Data': {'Path': 'Qwen', 'Name': 'Qwen2.5-7B',
                     'ChineseName': '通义千问2.5-7B',
                     'Description': '测试模型', 'License': 'Apache License 2.0',
                     'Downloads': 42},
        })
        engine = ModelScopeEngine()
        results = engine.search('Qwen/Qwen2.5-7B')
        assert results and results[0].source == 'modelscope'
        assert results[0].url == 'https://modelscope.cn/models/Qwen/Qwen2.5-7B'
        assert 'Apache' in results[0].content

    def test_network_failure_returns_none(self, monkeypatch):
        from engines.platform_engines import GiteeEngine
        import engines.platform_engines as pe
        monkeypatch.setattr(pe, '_http_get_json', lambda url: None)   # 网络失败
        monkeypatch.setattr(pe, '_host_reachable', lambda host, port=443, timeout=3.0: False)
        engine = GiteeEngine()
        assert engine.search('x') is None
        assert engine.is_available() is False


# ============================================================
# engines/academic_fulltext.py（arXiv 查询契约）
# ============================================================

class TestArxivFulltextQuery:
    """arXiv 直连的端点与参数约定（防回退）。

    实测事实：SEARCH_URL 必须是 https（http 每次多吃一个 301 跳转）；
    服务端还会对部分查询返回 HTTP 406（宽查询、累计请求量下更易触发，规则未见文档
    说明），因此引擎失败时把原因写进 engines.fallback.LAST_HTTP_ERROR，由 --probe 透出。
    """

    def _capture_url(self, monkeypatch):
        import engines.academic_fulltext as af
        seen = {}

        def fake_get(url, **kwargs):
            seen['url'] = url
            return b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

        monkeypatch.setattr(af, '_http_get', fake_get)
        return af, af.ArxivFulltextEngine(), seen

    def test_endpoint_is_https(self):
        import engines.academic_fulltext as af
        assert af.ArxivFulltextEngine.SEARCH_URL.startswith('https://')

    def test_search_query_precedes_max_results(self, monkeypatch):
        _, engine, seen = self._capture_url(monkeypatch)
        engine.search('transformer', max_results=3)
        query_string = seen['url'].split('?', 1)[1]
        assert query_string.index('search_query=') < query_string.index('max_results=')

    def test_search_failure_exposes_http_reason_for_probe(self, monkeypatch):
        """引擎返回 None 时，--probe 必须能说出为什么（而不是"所有引擎都不可用"）。"""
        import engines.academic_fulltext as af
        import engines.fallback as fb

        def fake_get(url, **kwargs):
            fb.LAST_HTTP_ERROR = 'HTTP 406'
            return None

        monkeypatch.setattr(af, '_http_get', fake_get)
        assert af.ArxivFulltextEngine().search('transformer', max_results=3) is None
        assert fb.LAST_HTTP_ERROR == 'HTTP 406'


# ============================================================
# plan.py 维度兜底 + research.py 相关性过滤（v6.5）
# ============================================================

class TestPlanDimensionFallback:
    """未命中主题模板时必须回退到通用 MECE 骨架。

    旧实现回退 ['综合'] → 即使 --effort deep 也只生成 1 个子问题，
    breadth=8 的并行子 Agent 编排整体落空（实测）。
    """

    def test_unmatched_topic_still_yields_multiple_subquestions(self):
        from plan import PlanGenerator
        plan = PlanGenerator().generate_plan(
            '大模型微调的成本与效率', depth='deep')
        assert len(plan.dimensions) >= 4
        assert len(plan.issue_tree) >= 4
        assert plan.dimensions != ['综合']

    def test_quick_depth_truncates_to_preset_size(self):
        from plan import PlanGenerator
        gen = PlanGenerator()
        quick = gen.generate_plan('随便一个主题', depth='quick')
        cap = gen.DEPTH_PRESETS['quick']['max_sub_questions']
        assert len(quick.issue_tree) <= cap

    def test_matched_template_still_wins_over_generic(self):
        from plan import PlanGenerator
        plan = PlanGenerator().generate_plan('LangChain vs LlamaIndex 对比', depth='standard')
        assert '特性对比' in plan.dimensions


class TestRelevanceFilter:
    """低相关结果过滤：够用才丢，不够用就保留并告警（避免误杀整份报告）。

    返回 (保留列表, 实际丢弃数, 低相关条数)。跨语言查询（中文主题 + 英文源）
    相关性天然偏低，无脑过滤会把报告清空，所以只在高相关结果够数时才丢弃。
    """

    def _mk(self, relevance, title='t'):
        return type('R', (), {'craap_score': {'relevance': relevance},
                              'title': title})()

    def test_drops_low_relevance_when_enough_strong_results(self):
        from research import filter_by_relevance
        results = [self._mk(80), self._mk(60), self._mk(50),
                   self._mk(45), self._mk(40), self._mk(10), self._mk(5)]
        kept, dropped, weak = filter_by_relevance(results, 30, 5)
        assert (dropped, weak) == (2, 2)
        assert len(kept) == 5
        assert all(r.craap_score['relevance'] >= 30 for r in kept)

    def test_keeps_everything_when_strong_results_insufficient(self):
        from research import filter_by_relevance
        results = [self._mk(12), self._mk(8), self._mk(5)]
        kept, dropped, weak = filter_by_relevance(results, 30, 5)
        assert dropped == 0 and weak == 3 and len(kept) == 3

    def test_missing_score_counts_as_low_relevance(self):
        from research import filter_by_relevance
        results = [type('R', (), {'craap_score': None})(), self._mk(90)]
        _, _, weak = filter_by_relevance(results, 30, 1)
        assert weak == 1

    def test_disabled_when_floor_zero(self):
        from research import filter_by_relevance
        results = [self._mk(1)]
        assert filter_by_relevance(results, 0, 5) == (results, 0, 0)


# ============================================================
# 文档一致性与执行模型（防再次漂移）
# ============================================================

class TestDocConsistency:
    ROOT = Path(__file__).resolve().parents[2]

    def _skill_md(self):
        return (self.ROOT / 'SKILL.md').read_text(encoding='utf-8')

    def test_skill_does_not_run_forked(self):
        """context: fork 会让 skill 在 10 turn 预算里被掐死（实测 reason=max_turns），
        四阶段工作流跑不完 → 调研失败。这条断言守住执行模型不回退。"""
        head = self._skill_md().split('---')[1]
        assert 'context: fork' not in head
        assert 'agent:' not in head

    def test_reference_links_exist(self):
        """SKILL.md 引用的 references/*.md 必须真实存在（曾有 14 份只在安装目录、未进版本库）。"""
        import re
        links = set(re.findall(r'references/([^\s)\]|]+\.md)', self._skill_md()))
        missing = [l for l in sorted(links) if not (self.ROOT / 'references' / l).exists()]
        assert not missing, f'SKILL.md 引用了不存在的参考文档: {missing}'

    def test_skill_version_is_single_source(self):
        """CLI banner 的版本号取自 SKILL.md frontmatter，不得再各写各的。"""
        import re
        from research import skill_version
        m = re.search(r'^version:\s*(\S+)', self._skill_md(), re.M)
        assert m and skill_version() == m.group(1)


class TestLedgerSetStatus:
    """Lead 归并阶段的状态升级通道。

    SKILL 要求"达标 claim 由 Lead 升 verified"，但没有命令可执行；
    又因 status() 按条目计数（不做 id 去重），绝不能用"追加同 id 新行"实现，
    否则该 claim 会被数两次。故 set-status 必须原地改写。
    """

    def _mk(self, tmp_path):
        from ledger import ResearchLedger
        led = ResearchLedger(str(tmp_path / 's')).init()
        c1 = led.add_claim('换位零代价最贴合命令 typo', topic='算法', status='pending')
        c2 = led.add_claim('flag 纠错没有现成地基', topic='参数层', status='pending')
        led.add_source(c1['id'], 'https://git.example/help.c')
        led.add_source(c1['id'], 'https://zsh.example/lex.c')
        led.add_source(c2['id'], 'https://gnu.example/getopt.c')
        return led, c1['id'], c2['id']

    def test_promote_rewrites_in_place_without_double_counting(self, tmp_path):
        from ledger import ResearchLedger
        led, c1, _c2 = self._mk(tmp_path)
        changed = led.set_status([c1], 'verified', note='交叉验证 2 独立来源')
        assert changed == 1
        algo = led.status()['算法']          # status() 无参 → 按主题嵌套
        assert algo['claims'] == 1, '同一条 claim 不得被计两次'
        assert algo['verified'] == 1

    def test_source_links_survive_promotion(self, tmp_path):
        from ledger import ResearchLedger
        led, c1, _ = self._mk(tmp_path)
        led.set_status([c1], 'verified')
        assert len(led.sources_for_claim(c1)) == 2

    def test_batch_and_illegal_status(self, tmp_path):
        from ledger import ResearchLedger
        led, c1, c2 = self._mk(tmp_path)
        assert led.set_status([c1, c2], 'supplementing') == 2
        assert led.set_status([c1], 'not-a-status') == 0
        assert led.status()['参数层']['supplementing'] == 1


# ============================================================
# repo_health.py（v6.2 开源仓库健康/合规/风险扫描）
# ============================================================

class TestRepoHealth:
    """许可证分级 / 维护预警 / OSV 集成（mock API）"""

    def test_license_risk_levels(self):
        from repo_health import license_risk
        assert license_risk('MIT')[0] == 'permissive'
        assert license_risk('Apache-2.0')[0] == 'permissive'
        assert license_risk('LGPL-3.0')[0] == 'weak'
        assert license_risk('GPL-3.0')[0] == 'strong'
        assert license_risk('AGPL-3.0')[0] == 'strong'
        assert license_risk('')[0] == 'unknown'
        # v6.3：or-later 变体不再被 'gpl' 子串误判为 strong
        assert license_risk('LGPL-3.0-or-later')[0] == 'weak'
        assert license_risk('GPL-3.0-or-later')[0] == 'strong'

    def test_parse_repo_ref(self):
        from repo_health import _parse_repo_ref
        assert _parse_repo_ref('langchain-ai/langchain')['host'] == 'github'
        r = _parse_repo_ref('https://gitee.com/oschina/hello-world')
        assert r == {'host': 'gitee', 'owner': 'oschina', 'repo': 'hello-world'}
        assert _parse_repo_ref('not-a-valid-ref!') is None

    def test_stale_repo_high_risk(self, monkeypatch):
        from repo_health import scan_repo
        import repo_health as rh
        monkeypatch.setattr(rh, '_get_json', lambda url: {
            'full_name': 'a/b', 'description': 'd', 'language': 'Python',
            'stargazers_count': 5, 'pushed_at': '2020-01-01T00:00:00Z',
            'archived': False, 'license': {'spdx_id': 'GPL-3.0'}})
        monkeypatch.setattr(rh, '_post_json', lambda url, p: {'vulnerabilities': [
            {'id': 'GHSA-x', 'summary': 's', 'aliases': ['CVE-2024-1']}]})
        h = scan_repo('a/b', with_cve_package='pypi:demo')
        assert h.api_ok
        assert h.overall() == 'high'
        cats = {r['category'] for r in h.risks}
        assert {'maintenance', 'license', 'security', 'adoption'} <= cats

    def test_archived_flag(self, monkeypatch):
        from repo_health import scan_repo
        import repo_health as rh
        monkeypatch.setattr(rh, '_get_json', lambda url: {
            'full_name': 'a/b', 'pushed_at': '2026-08-01T00:00:00Z', 'archived': True,
            'stargazers_count': 100, 'license': {'spdx_id': 'MIT'}})
        monkeypatch.setattr(rh, '_post_json', lambda url, p: None)
        h = scan_repo('a/b')
        assert any(r['category'] == 'maintenance' and '归档' in r['detail'] for r in h.risks)

    def test_api_unavailable(self, monkeypatch):
        from repo_health import scan_repo
        import repo_health as rh
        monkeypatch.setattr(rh, '_get_json', lambda url: None)
        h = scan_repo('a/b')
        assert h.api_ok is False
        assert any(r['category'] == 'api_unavailable' for r in h.risks)


# ============================================================
# v6.3 真实性验证强化（落盘分流 / 引用反查 / 六维）
# ============================================================

class TestTruthV63:
    """verified 语义链：分流落盘 / 引用→来源强契约 / 六维要素"""

    def _verify_stub(self):
        """构造 verification 桩（对象属性形态，兼容 _write_ledger）"""
        Claim = type('C', (), {})
        c1, c2, c3 = Claim(), Claim(), Claim()
        c1.statement = 'Transformer 是主流架构'
        c2.statement = '某低质说法'
        c3.statement = '唯一单源结论'
        Con = type('K', (), {})
        k = Con()
        k.claim_a, k.claim_b = '性能提升 3 倍', '性能提升 2 倍'
        Ver = type('V', (), {})
        v = Ver()
        v.verified_claims, v.single_source_claims, v.contradictions = [c1], [c3], [k]
        return v

    def test_write_ledger_status_split(self, tmp_path):
        from ledger import ResearchLedger
        import research as rz
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        results = [
            type('R', (), {'title': 'Transformer 是主流架构',
                           'url': 'https://arxiv.org/a', 'content': 'c',
                           'craap_score': {'tier': 1, 'total': 80}})(),
            type('R', (), {'title': '唯一单源结论',
                           'url': 'https://arxiv.org/b', 'content': 'c',
                           'craap_score': {}})(),
            type('R', (), {'title': '性能提升 3 倍',
                           'url': 'https://x.example/c', 'content': 'c',
                           'craap_score': {}})(),
            type('R', (), {'title': '完全未被验证的第三条',
                           'url': 'https://x.example/d', 'content': 'c',
                           'craap_score': {}})(),
        ]
        # v6.10：默认不再自动建 claim，这里显式要 auto-claim，测的仍是分流逻辑
        n = rz._write_ledger(L, results, self._verify_stub(), '主题', auto_claim=True)
        assert n['claims'] == 4
        statuses = {c['text']: c['status'] for c in L.claims()}
        assert statuses['Transformer 是主流架构'] == 'verified'
        assert statuses['唯一单源结论'] == 'pending'
        assert statuses['性能提升 3 倍'] == 'conflict'
        assert statuses['完全未被验证的第三条'] == 'pending'   # 未验证不再标 verified

    def test_citation_without_url_traced_fails(self, tmp_path):
        from validate_report import validate_report
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c1 = L.add_claim('结论A', '主题A', 'verified', 'general', 0.9)
        for i in range(3):
            L.add_source(c1['id'], f'https://arxiv.org/{i}', tier=1)
        # 报告引用 [1] 但正文/附录没有该来源 URL → 反查失败
        bad = '''# 报告
## 执行摘要
结论 [1]。
## 调研范围与方法
m
## 结论与建议
c
## 来源
[1] 完全没写 URL 的来源
'''
        r = validate_report(bad, ledger=L)
        assert r.passed is False
        assert any('无法追溯' in i for i in r.issues)

    def test_opensource_six_dims_missing(self, tmp_path):
        from validate_report import validate_report
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c1 = L.add_claim('项目X 可用', '开源', 'verified', 'general', 0.9)
        L.add_source(c1['id'], 'https://github.com/a/b', tier=2)
        L.add_source(c1['id'], 'https://gitee.com/a/b2', tier=2)
        # 报告含仓库链接但缺六维要素（无风险标签/许可证/适配性等）
        sparse = '''# 报告
## 执行摘要
推荐项目X [1] https://github.com/a/b。
## 调研范围与方法
m
## 结论与建议
c
## 来源
[1] https://github.com/a/b [2] https://gitee.com/a/b2
'''
        r = validate_report(sparse, ledger=L)
        assert r.passed is False
        assert any('六维' in i for i in r.issues)

    def test_primary_index_stable(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c1 = L.add_claim('A', 't', 'verified')
        c2 = L.add_claim('B', 't', 'verified')
        L.add_source(c1['id'], 'https://a/1')
        L.add_source(c1['id'], 'https://a/2')
        L.add_source(c2['id'], 'https://b/1')
        srcs = L.export_json()['sources']
        idx = [s['primary_index'] for s in srcs]
        assert idx == [1, 2, 3]

    def test_ledger_default_pending(self, tmp_path):
        from ledger import ResearchLedger
        L = ResearchLedger(str(tmp_path / 'ledger')).init()
        c = L.add_claim('未指定状态的 claim', 't')          # 默认
        c2 = L.add_claim('非法状态值', 't', status='bogus')  # 非法值
        assert c['status'] == 'pending'
        assert c2['status'] == 'pending'


# ============================================================
# similarity.py + v6.4 语义级（转载指纹 / 数值矛盾 / 近义聚类）
# ============================================================

class TestSimilarityV64:
    """语义级聚类的三个核心场景"""

    def test_same_content_detection(self):
        from similarity import is_same_content
        assert is_same_content('OpenAI 发布 GPT-5 模型',
                               'OpenAI 发布 GPT-5 模型|新浪') is True
        assert is_same_content('某地发生地震(转载)',
                               '某地发生地震（转载站）') is True
        assert is_same_content('苹果发布新手机',
                               '特斯拉股价暴涨') is False

    def test_effective_independent_dedupes_syndication(self):
        from similarity import effective_independent_count
        syndicated = [
            {'title': 'OpenAI 发布 GPT-5 模型', 'url': 'https://reuters.com/a', 'tier': 2},
            {'title': 'OpenAI 发布 GPT-5 模型|新浪', 'url': 'https://sina.com/a', 'tier': 3},
            {'title': '完全不同的另一篇调研', 'url': 'https://arxiv.org/x', 'tier': 1},
        ]
        assert effective_independent_count(syndicated) == 2   # 转载合并
        assert effective_independent_count(syndicated[:2]) == 1  # 纯转载

    def test_group_by_similarity_paraphrase(self):
        from similarity import group_by_similarity
        sents = [
            'Transformer 是主流 LLM 架构',
            'Transformer 是当下主流的大模型架构',   # 近义改写
            '性能提升 10 倍',
            '性能提升 2 倍',                        # 数值差异(仍同主题)
            'MoE 混合专家降低推理成本',
        ]
        groups = group_by_similarity(sents)
        flat = [sorted(g) for g in groups]
        assert [0, 1] in flat          # 近义聚
        assert [2, 3] in flat          # 数值聚(供矛盾检测)
        assert [4] in flat

    def test_numeric_conflict(self):
        from similarity import numeric_conflict
        c = numeric_conflict('性能提升 10 倍', '性能提升 2 倍')
        assert c is not None and c['ratio'] > 0.5
        assert numeric_conflict('性能提升 2.8 倍', '性能提升 3 倍') is None  # <20% 不算矛盾


class TestVerifyV64:
    """verify 集成：近义聚合 + 数值矛盾入 contradictions"""

    def _mk_claim(self, sid, statement):
        from verify import Claim
        c = Claim(id=sid, statement=statement)
        return c

    def test_group_similar_claims_paraphrase(self):
        from verify import CrossVerifier
        v = CrossVerifier()
        claims = [
            self._mk_claim('c1', 'Transformer 是主流 LLM 架构'),
            self._mk_claim('c2', 'Transformer 是当下主流的大模型架构'),
            self._mk_claim('c3', 'MoE 降低推理成本'),
        ]
        groups = v._group_similar_claims(claims)
        assert any(len(g) == 2 for g in groups)

    def test_numeric_contradiction_detected(self):
        from verify import CrossVerifier
        v = CrossVerifier()
        claims = [
            self._mk_claim('c1', '性能提升 10 倍'),
            self._mk_claim('c2', '性能提升 2 倍'),
        ]
        cons = v._detect_numeric_contradictions(claims)
        assert len(cons) == 1
        assert '数值矛盾' in cons[0].possible_reason

# ============================================================
# v6.6：--effort 与 DEPTH_PRESETS 的映射（实测缺陷 D1）
# ============================================================

class TestEffortPresetMapping:
    """SKILL 约定「--effort 与 --depth 同时给出时以 --effort 为准」，
    且 effort 词表用 exhaustive、depth 词表用 extreme。

    实测 --effort deep --dimensions <8 个> 只得到 5 个子问题：
    research.py 两条 generate_plan 路径只传 depth，effort 从未参与；
    plan.py 再按 DEPTH_PRESETS[depth].max_sub_questions 静默切片。
    """

    DIMS8 = ['算法基础', 'shell 实现', '词典来源', '参数层', '工程约束',
             '评测指标', '开源生态', 'LLM 路线']

    def test_effort_deep_keeps_all_eight_dimensions(self):
        from plan import PlanGenerator
        plan = PlanGenerator().generate_plan(
            topic='Linux 命令纠错', depth='standard', effort='deep',
            dimensions=list(self.DIMS8))
        assert len(plan.dimensions) == 8, '--effort deep 允许 7-10 个子问题，不得截为 5'
        assert len(plan.issue_tree) == 8, 'issue_tree 数量须与 dimensions 一致'

    def test_exhaustive_effort_maps_to_extreme_preset(self):
        """effort 的 exhaustive 与 depth 的 extreme 是同一档；
        不映射则 DEPTH_PRESETS 无 'exhaustive' 键、静默回落 standard。"""
        from plan import resolve_preset_key
        assert resolve_preset_key(effort='exhaustive') == 'extreme'
        from plan import PlanGenerator
        plan = PlanGenerator().generate_plan(
            topic='x', effort='exhaustive', dimensions=[f'd{i}' for i in range(12)])
        assert len(plan.dimensions) == 12

    def test_effort_takes_precedence_over_depth(self):
        from plan import resolve_preset_key
        assert resolve_preset_key(effort='deep', depth='standard') == 'deep'
        assert resolve_preset_key(effort=None, depth='extreme') == 'extreme'
        assert resolve_preset_key(effort=None, depth=None) == 'standard'

    def test_unknown_preset_key_raises_instead_of_silently_standard(self):
        """静默回落 standard 是本类 bug 的架构性成因（typo 不报错）。"""
        from plan import resolve_preset_key
        import pytest
        with pytest.raises(ValueError):
            resolve_preset_key(effort='ultra')

    def test_truncation_is_reported_not_silent(self):
        from plan import PlanGenerator
        plan = PlanGenerator().generate_plan(
            topic='x', effort='deep', dimensions=[f'd{i}' for i in range(11)])
        assert len(plan.dimensions) == 8, 'deep 上限 8'
        assert plan.dropped_dimensions == ['d8', 'd9', 'd10'], \
            '被丢弃的维度必须留痕，不能静默消失'

    def test_plan_only_cli_honors_effort_deep(self):
        """端到端：这是用户实际看到的症状（8 维只出 5 个子问题）。"""
        import subprocess
        cmd = [sys.executable, str(Path(__file__).parent.parent / 'research.py'),
               'Linux 命令纠错', '--plan-only', '--effort', 'deep',
               '--dimensions', ','.join(self.DIMS8)]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        assert r.returncode == 0, r.stderr
        import re
        items = re.findall(r'^\s+(\d+)\.\s', r.stdout, re.M)
        assert len(items) >= 8, \
            f'--effort deep 下 8 个维度必须全部展开，实际 {len(items)}:\n{r.stdout[:2000]}'
        assert 'LLM 路线' in r.stdout, '最后一个维度不得被截掉'
