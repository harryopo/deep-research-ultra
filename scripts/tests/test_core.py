"""
Deep Research Ultra v4.0 — 单元测试

覆盖核心模块：
- engines/base.py: SearchEngine, EngineMetadata, SearchResult, EngineRegistry
- cache.py: LRUCache
- plan.py: IssueTree, PlanGenerator, DataSourceMatcher
- score.py: CraapScorer
- verify.py: CrossVerifier
- reflect.py: Reflector
- report.py: ReportGenerator, MermaidGenerator
- progress.py: ProgressTracker, QualityAssessor

运行方式：
    cd scripts
    python -m pytest tests/ -v
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# engines/base.py 测试
# ============================================================

class TestEngineMetadata:
    """EngineMetadata 测试"""

    def test_default_values(self):
        from engines.base import EngineMetadata
        m = EngineMetadata(name='test', layer=1, description='测试')
        assert m.name == 'test'
        assert m.layer == 1
        assert m.requires_config is False
        assert m.config_keys == []
        assert m.is_async_supported is True
        assert m.is_china_friendly is True
        assert m.priority == 100
        assert m.capabilities == []

    def test_custom_values(self):
        from engines.base import EngineMetadata
        m = EngineMetadata(
            name='tavily', layer=1, description='AI 搜索',
            requires_config=True, config_keys=['TAVILY_API_KEY'],
            priority=10, capabilities=['search', 'extract']
        )
        assert m.requires_config is True
        assert m.config_keys == ['TAVILY_API_KEY']
        assert m.priority == 10
        assert 'search' in m.capabilities


class TestSearchResult:
    """SearchResult 测试"""

    def test_to_dict(self):
        from engines.base import SearchResult
        r = SearchResult(
            title='测试', url='https://example.com',
            content='内容', source='test', score=85.5
        )
        d = r.to_dict()
        assert d['title'] == '测试'
        assert d['url'] == 'https://example.com'
        assert d['score'] == 85.5
        assert d['source'] == 'test'

    def test_default_values(self):
        from engines.base import SearchResult
        r = SearchResult(title='', url='', content='', source='')
        assert r.score == 0.0
        assert r.craap_score is None
        assert r.published_date == ''
        assert r.raw == {}


class TestEngineRegistry:
    """EngineRegistry 测试"""

    def test_register_and_get(self):
        from engines.base import EngineRegistry, SearchEngine, EngineMetadata

        class TestEngine(SearchEngine):
            @property
            def metadata(self):
                return EngineMetadata(name='test-engine', layer=1, description='测试')

            def is_available(self):
                return True

            def search(self, query, max_results=10, **kwargs):
                return []

        registry = EngineRegistry()
        engine = TestEngine()
        registry.register(engine)
        assert 'test-engine' in registry
        assert registry.get('test-engine') is engine

    def test_duplicate_register(self):
        from engines.base import EngineRegistry, SearchEngine, EngineMetadata

        class TestEngine(SearchEngine):
            @property
            def metadata(self):
                return EngineMetadata(name='dup', layer=1, description='')

            def is_available(self):
                return True

            def search(self, query, max_results=10, **kwargs):
                return []

        registry = EngineRegistry()
        registry.register(TestEngine())
        with pytest.raises(ValueError):
            registry.register(TestEngine())

    def test_get_by_layer(self):
        from engines.base import EngineRegistry, SearchEngine, EngineMetadata

        class Layer1Engine(SearchEngine):
            @property
            def metadata(self):
                return EngineMetadata(name='l1', layer=1, description='', priority=10)

            def is_available(self):
                return True

            def search(self, query, max_results=10, **kwargs):
                return []

        class Layer4Engine(SearchEngine):
            @property
            def metadata(self):
                return EngineMetadata(name='l4', layer=4, description='', priority=300)

            def is_available(self):
                return True

            def search(self, query, max_results=10, **kwargs):
                return []

        registry = EngineRegistry()
        registry.register(Layer1Engine())
        registry.register(Layer4Engine())

        l1 = registry.get_by_layer(1)
        assert len(l1) == 1
        assert l1[0].get_name() == 'l1'

    def test_fallback_chain(self):
        from engines.base import EngineRegistry, SearchEngine, EngineMetadata

        class Engine1(SearchEngine):
            @property
            def metadata(self):
                return EngineMetadata(name='e1', layer=1, description='', priority=10)

            def is_available(self):
                return True

            def search(self, query, max_results=10, **kwargs):
                return []

        class Engine2(SearchEngine):
            @property
            def metadata(self):
                return EngineMetadata(name='e2', layer=4, description='', priority=300)

            def is_available(self):
                return True

            def search(self, query, max_results=10, **kwargs):
                return []

        registry = EngineRegistry()
        registry.register(Engine2())
        registry.register(Engine1())

        chain = registry.get_fallback_chain()
        # Layer 1 应该在 Layer 4 前面
        assert chain[0].get_layer() == 1
        assert chain[1].get_layer() == 4


# ============================================================
# cache.py 测试
# ============================================================

class TestLRUCache:
    """LRUCache 测试"""

    def test_set_and_get(self):
        from cache import LRUCache
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LRUCache(cache_dir=Path(tmpdir))
            key = cache.make_key('test query')
            cache.set(key, {'results': [{'title': 'test'}]})
            data = cache.get(key)
            assert data is not None
            assert data['results'][0]['title'] == 'test'

    def test_miss(self):
        from cache import LRUCache
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LRUCache(cache_dir=Path(tmpdir))
            data = cache.get('nonexistent')
            assert data is None

    def test_cache_key_includes_language(self):
        from cache import LRUCache
        key_zh = LRUCache.make_key('AI', language='zh')
        key_en = LRUCache.make_key('AI', language='en')
        assert key_zh != key_en

    def test_cache_key_includes_region(self):
        from cache import LRUCache
        key_cn = LRUCache.make_key('AI', region='cn')
        key_global = LRUCache.make_key('AI', region='global')
        assert key_cn != key_global

    def test_ttl_expiration(self):
        from cache import LRUCache
        from datetime import timedelta
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LRUCache(cache_dir=Path(tmpdir), ttl=timedelta(seconds=0.1))
            key = cache.make_key('test')
            cache.set(key, {'data': 'test'})
            time.sleep(0.2)
            data = cache.get(key)
            assert data is None  # 已过期

    def test_clear(self):
        from cache import LRUCache
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LRUCache(cache_dir=Path(tmpdir))
            cache.set('key1', {'data': 1})
            cache.set('key2', {'data': 2})
            count = cache.clear()
            assert count == 2

    def test_stats(self):
        from cache import LRUCache
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LRUCache(cache_dir=Path(tmpdir))
            cache.set('key1', {'data': 1})
            cache.get('key1')  # hit
            cache.get('key2')  # miss
            stats = cache.stats()
            assert stats['hits'] == 1
            assert stats['misses'] == 1
            assert stats['entries'] == 1


# ============================================================
# plan.py 测试
# ============================================================

class TestDataSourceMatcher:
    """DataSourceMatcher 测试"""

    def test_match_academic(self):
        from plan import DataSourceMatcher
        sources = DataSourceMatcher.match('搜索 AI 论文')
        assert 'arxiv' in sources or 'paper-search' in sources

    def test_match_community(self):
        from plan import DataSourceMatcher
        sources = DataSourceMatcher.match('搜索 Reddit 讨论')
        assert 'agent-reach' in sources or 'last30days' in sources

    def test_match_opensource(self):
        from plan import DataSourceMatcher
        sources = DataSourceMatcher.match('搜索 GitHub 开源项目')
        assert 'oss-finder' in sources

    def test_match_default(self):
        from plan import DataSourceMatcher
        sources = DataSourceMatcher.get_default_sources()
        assert len(sources) > 0
        assert 'tavily' in sources


class TestIssueTree:
    """IssueTree 测试"""

    def test_add_root(self):
        from plan import IssueTree
        tree = IssueTree()
        q = tree.add_root('根问题', hypothesis='假设1')
        assert q.question == '根问题'
        assert q.depth == 0
        assert len(tree.roots) == 1

    def test_add_child(self):
        from plan import IssueTree
        tree = IssueTree()
        root = tree.add_root('根问题')
        child = tree.add_child(root, '子问题')
        assert child.depth == 1
        assert child.parent_id == root.id
        assert len(root.children) == 1

    def test_validate_mece(self):
        from plan import IssueTree
        tree = IssueTree()
        root = tree.add_root('根问题', hypothesis='假设')
        tree.add_child(root, '子问题1', hypothesis='假设1')
        tree.add_child(root, '子问题2', hypothesis='假设2')
        result = tree.validate_mece()
        assert 'is_mece' in result
        assert 'total_questions' in result

    def test_to_mermaid(self):
        from plan import IssueTree
        tree = IssueTree()
        root = tree.add_root('根问题')
        tree.add_child(root, '子问题')
        mermaid = tree.to_mermaid()
        assert 'graph TD' in mermaid
        assert '-->' in mermaid


class TestPlanGenerator:
    """PlanGenerator 测试"""

    def test_clarify_topic_short(self):
        from plan import PlanGenerator
        gen = PlanGenerator()
        result = gen.clarify_topic('AI')
        assert result['needs_clarification'] is True

    def test_clarify_topic_comparison(self):
        from plan import PlanGenerator
        gen = PlanGenerator()
        result = gen.clarify_topic('FastAPI vs Django 性能对比')
        assert result['detected_dimension'] == 'comparison'

    def test_clarify_topic_academic(self):
        from plan import PlanGenerator
        gen = PlanGenerator()
        result = gen.clarify_topic('大语言模型微调技术研究')
        assert result['detected_dimension'] == 'academic'

    def test_generate_plan(self):
        from plan import PlanGenerator
        gen = PlanGenerator()
        plan = gen.generate_plan(
            topic='Python Web 框架调研',
            goal='技术选型',
            depth='standard',
        )
        assert plan.topic == 'Python Web 框架调研'
        assert plan.depth == 'standard'
        assert len(plan.issue_tree) > 0

    def test_depth_presets(self):
        from plan import PlanGenerator
        gen = PlanGenerator()
        assert 'quick' in gen.DEPTH_PRESETS
        assert 'standard' in gen.DEPTH_PRESETS
        assert 'deep' in gen.DEPTH_PRESETS

    def test_plan_save_load(self):
        from plan import PlanGenerator, ResearchPlan
        gen = PlanGenerator()
        plan = gen.generate_plan(topic='测试', depth='quick')
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
            path = f.name
        try:
            plan.save(path)
            loaded = ResearchPlan.load(path)
            assert loaded.topic == '测试'
        finally:
            os.unlink(path)


# ============================================================
# score.py 测试
# ============================================================

class TestCraapScorer:
    """CraapScorer 测试"""

    def test_score_basic(self):
        from score import CraapScorer
        scorer = CraapScorer()
        result = {
            'title': 'FastAPI 性能测试',
            'url': 'https://arxiv.org/abs/2025.12345',
            'content': 'FastAPI 性能比 Flask 快 3 倍，2025 年最新测试',
            'published_date': '2025-06-01',
        }
        score = scorer.score(result, query='FastAPI 性能')
        assert 'currency' in score
        assert 'relevance' in score
        assert 'authority' in score
        assert 'accuracy' in score
        assert 'purpose' in score
        assert 'total' in score
        assert 'grade' in score

    def test_score_authority_arxiv(self):
        from score import CraapScorer
        scorer = CraapScorer()
        result = {
            'title': '论文', 'url': 'https://arxiv.org/abs/1234',
            'content': '学术内容', 'published_date': '2025-01-01',
        }
        score = scorer.score(result, query='论文')
        assert score['authority'] >= 90  # arxiv 是权威源

    def test_score_currency_recent(self):
        from score import CraapScorer
        scorer = CraapScorer()
        result = {
            'title': '测试', 'url': 'https://example.com',
            'content': '内容', 'published_date': '2025-06-01',
        }
        score = scorer.score(result)
        assert score['currency'] >= 90  # 2025 年是近期

    def test_score_chinese_query(self):
        """测试中文查询（修复 v3 的 split() 失效问题）"""
        from score import CraapScorer
        scorer = CraapScorer()
        result = {
            'title': 'FastAPI性能测试报告',
            'url': 'https://example.com',
            'content': 'FastAPI性能测试',
            'published_date': '',
        }
        score = scorer.score(result, query='FastAPI性能')
        assert score['relevance'] > 0  # 不应因中文无空格而失效

    def test_grade_conversion(self):
        from score import CraapScorer
        assert CraapScorer._get_grade(80) == 'high'
        assert CraapScorer._get_grade(60) == 'medium'
        assert CraapScorer._get_grade(30) == 'low'


# ============================================================
# verify.py 测试
# ============================================================

class TestCrossVerifier:
    """CrossVerifier 测试"""

    def test_get_domain(self):
        from verify import CrossVerifier
        assert CrossVerifier.get_domain('https://www.example.com/path') == 'example.com'
        assert CrossVerifier.get_domain('https://arxiv.org/abs/1234') == 'arxiv.org'
        assert CrossViewer_safe_get_domain(CrossVerifier, '')

    def test_is_independent(self):
        from verify import CrossVerifier
        v = CrossVerifier()
        assert v.is_independent_source('https://a.com', 'https://b.com') is True
        assert v.is_independent_source('https://a.com/x', 'https://a.com/y') is False

    def test_verify_basic(self):
        from verify import CrossVerifier
        v = CrossVerifier()
        results = [
            {'title': 'FastAPI 快', 'url': 'https://a.com', 'content': 'FastAPI 性能好'},
            {'title': 'FastAPI 性能测试', 'url': 'https://b.com', 'content': 'FastAPI 性能确实好'},
            {'title': 'Flask 也不错', 'url': 'https://c.com', 'content': 'Flask 适合小项目'},
        ]
        result = v.verify(results, query='FastAPI 性能')
        assert result.total_results == 3
        assert result.total_claims > 0

    def test_verification_result_summary(self):
        from verify import VerificationResult
        r = VerificationResult(query='test', total_results=10, total_claims=5)
        r.verified_claims = []
        r.single_source_claims = []
        r.contradictions = []
        summary = r.summary()
        assert summary['total_results'] == 10


def CrossViewer_safe_get_domain(verifier, url):
    """安全测试空 URL"""
    try:
        result = verifier.get_domain(url)
        return result == ''
    except Exception:
        return True


# ============================================================
# reflect.py 测试
# ============================================================

class TestReflector:
    """Reflector 测试"""

    def test_reflect_basic(self):
        from reflect import Reflector

        class MockPlan:
            topic = '测试'
            dimensions = ['维度1', '维度2']
            issue_tree = []

        results = [
            type('R', (), {
                'title': '结果1', 'source': 'tavily',
                'content': '维度1 的内容', 'craap_score': {'grade': 'high'},
            })(),
        ]

        reflector = Reflector(max_rounds=3)
        reflection = reflector.reflect(MockPlan(), results, 0)
        assert reflection.round_num == 0
        assert 0 <= reflection.coverage_score <= 1

    def test_should_continue_low_coverage(self):
        from reflect import Reflector
        reflector = Reflector(max_rounds=3, coverage_threshold=0.75)
        should, stop, drill = reflector._should_continue(0, 0.3, [], 3)
        assert should is True

    def test_should_stop_high_coverage(self):
        from reflect import Reflector
        reflector = Reflector(max_rounds=3, coverage_threshold=0.75)
        should, stop, drill = reflector._should_continue(0, 0.8, [], 20)
        assert should is False
        assert '覆盖率已达标' in stop

    def test_should_stop_max_rounds(self):
        from reflect import Reflector
        reflector = Reflector(max_rounds=3)
        should, stop, drill = reflector._should_continue(2, 0.3, [], 5)
        assert should is False
        assert '最大反思轮次' in stop


# ============================================================
# report.py 测试
# ============================================================

class TestReportGenerator:
    """ReportGenerator 测试"""

    def test_generate_html(self):
        from report import ReportGenerator

        class MockPlan:
            topic = '测试调研'
            goal = '测试'
            depth = 'standard'
            estimated_duration = '3-5 分钟'
            dimensions = ['维度1']
            issue_tree = []

        results = [
            type('R', (), {
                'title': '结果1', 'url': 'https://example.com',
                'content': '内容', 'source': 'tavily',
                'published_date': '2025-01-01', 'author': '',
                'craap_score': {'total': 85, 'grade': 'high'},
            })(),
        ]

        reporter = ReportGenerator()
        html = reporter.generate(MockPlan(), results, format='html')
        assert '<html' in html
        assert '测试调研' in html

    def test_generate_markdown(self):
        from report import ReportGenerator

        class MockPlan:
            topic = '测试'
            goal = ''
            depth = 'quick'
            estimated_duration = ''
            dimensions = []
            issue_tree = []

        results = [
            type('R', (), {
                'title': '结果', 'url': 'https://example.com',
                'content': '', 'source': 'test',
                'craap_score': {'total': 70, 'grade': 'medium'},
            })(),
        ]

        reporter = ReportGenerator()
        md = reporter.generate(MockPlan(), results, format='markdown')
        assert '# 测试' in md
        assert '结果' in md

    def test_generate_csv(self):
        from report import ReportGenerator
        results = [
            type('R', (), {
                'title': '结果', 'url': 'https://example.com',
                'content': '', 'source': 'test',
                'published_date': '', 'author': '',
                'craap_score': {'total': 70, 'grade': 'medium',
                                'currency': 70, 'relevance': 70,
                                'authority': 70, 'accuracy': 70, 'purpose': 70},
            })(),
        ]
        reporter = ReportGenerator()
        csv = reporter.generate(None, results, format='csv')
        assert 'Title' in csv
        assert '结果' in csv


class TestMermaidGenerator:
    """MermaidGenerator 测试"""

    def test_timeline(self):
        from report import MermaidGenerator
        events = [
            {'date': '2025-01', 'event': '事件1', 'source': ''},
            {'date': '2025-06', 'event': '事件2', 'source': ''},
        ]
        mermaid = MermaidGenerator.timeline(events)
        assert 'timeline' in mermaid
        assert '2025-01' in mermaid

    def test_source_distribution(self):
        from report import MermaidGenerator
        results = [
            type('R', (), {'source': 'tavily'})(),
            type('R', (), {'source': 'tavily'})(),
            type('R', (), {'source': 'arxiv'})(),
        ]
        mermaid = MermaidGenerator.source_distribution(results)
        assert 'pie' in mermaid
        assert 'tavily' in mermaid


# ============================================================
# progress.py 测试
# ============================================================

class TestProgressTracker:
    """ProgressTracker 测试"""

    def test_basic_flow(self):
        from progress import ProgressTracker
        tracker = ProgressTracker(depth='quick')
        tracker.start_phase('plan', 'step1')
        tracker.update('working', 0.5)
        tracker.complete_step('done')
        assert len(tracker.steps) == 1
        assert tracker.steps[0].status == 'completed'

    def test_eta(self):
        from progress import ProgressTracker
        tracker = ProgressTracker(depth='quick')
        eta = tracker.get_eta()
        assert 'elapsed_seconds' in eta
        assert 'remaining_seconds' in eta
        assert 'progress_percent' in eta

    def test_summary(self):
        from progress import ProgressTracker
        tracker = ProgressTracker(depth='standard')
        tracker.start_phase('plan', 'step1')
        tracker.complete_step()
        summary = tracker.summary()
        assert 'depth' in summary
        assert summary['total_steps'] == 1
        assert summary['completed_steps'] == 1


class TestQualityAssessor:
    """QualityAssessor 测试"""

    def test_assess_basic(self):
        from progress import QualityAssessor

        class MockPlan:
            dimensions = ['维度1', '维度2']

        results = [
            type('R', (), {
                'source': 'tavily', 'content': '维度1',
                'craap_score': {'total': 80},
            })(),
            type('R', (), {
                'source': 'arxiv', 'content': '维度2',
                'craap_score': {'total': 90},
            })(),
        ]

        assessor = QualityAssessor()
        result = assessor.assess(MockPlan(), results)
        assert 'scores' in result
        assert 'total_score' in result
        assert 'grade' in result
        assert 'improvements' in result

    def test_grade_conversion(self):
        from progress import QualityAssessor
        assert QualityAssessor._get_grade(90) == 'A'
        assert QualityAssessor._get_grade(75) == 'B'
        assert QualityAssessor._get_grade(60) == 'C'
        assert QualityAssessor._get_grade(45) == 'D'
        assert QualityAssessor._get_grade(30) == 'F'


# ============================================================
# engines/mcp_client.py 测试
# ============================================================

class TestMcpClient:
    """McpClient 测试"""

    def test_load_mcp_config_empty(self):
        """测试加载配置（可能为空）"""
        from engines.mcp_client import load_mcp_config
        config = load_mcp_config()
        assert isinstance(config, dict)

    def test_client_not_configured(self):
        """测试未配置的 MCP 服务器"""
        from engines.mcp_client import McpClient
        client = McpClient('nonexistent-mcp-server-12345')
        assert client.is_configured() is False
        assert client.is_available() is False


# ============================================================
# engines/skill_engines.py 测试
# ============================================================

class TestSkillEngines:
    """Skill 引擎测试"""

    def test_agent_reach_metadata(self):
        from engines.skill_engines import AgentReachEngine
        engine = AgentReachEngine()
        m = engine.metadata
        assert m.name == 'agent-reach'
        assert m.layer == 2
        assert 'community' in m.capabilities

    def test_oss_finder_metadata(self):
        from engines.skill_engines import OssFinderEngine
        engine = OssFinderEngine()
        m = engine.metadata
        assert m.name == 'oss-finder'
        assert m.layer == 2

    def test_skill_invocation_template(self):
        from engines.skill_engines import AgentReachEngine
        engine = AgentReachEngine()
        template = engine.get_invocation_template(query='AI', max_results=5)
        assert template['skill_name'] == 'agent-reach'
        assert 'instruction' in template


# ============================================================
# engines/builtin.py 测试
# ============================================================

class TestBuiltinEngines:
    """内置引擎测试"""

    def test_websearch_always_available(self):
        from engines.builtin import WebSearchEngine
        engine = WebSearchEngine()
        assert engine.is_available() is True
        assert engine.metadata.layer == 3

    def test_webfetch_always_available(self):
        from engines.builtin import WebFetchEngine
        engine = WebFetchEngine()
        assert engine.is_available() is True
        assert engine.metadata.layer == 3


# ============================================================
# engines/fallback.py 测试
# ============================================================

class TestFallbackEngines:
    """降级引擎测试"""

    def test_baidu_metadata(self):
        from engines.fallback import BaiduHtmlEngine
        engine = BaiduHtmlEngine()
        m = engine.metadata
        assert m.name == 'baidu-html'
        assert m.layer == 4
        assert m.is_china_friendly is True

    def test_bing_metadata(self):
        from engines.fallback import BingHtmlEngine
        engine = BingHtmlEngine()
        m = engine.metadata
        assert m.name == 'bing-html'
        assert m.layer == 4

    def test_baidu_available(self):
        from engines.fallback import BaiduHtmlEngine
        engine = BaiduHtmlEngine()
        # 百度始终可用（不实际测试连通性）
        assert engine.is_available() is True

    def test_searxng_not_configured(self):
        from engines.fallback import SearXNGEngine
        engine = SearXNGEngine()
        # 未配置 SEARXNG_URL 时应不可用
        if not os.environ.get('SEARXNG_URL'):
            assert engine.is_available() is False


# ============================================================
# router.py 测试（v5.0 智能路由）
# ============================================================

class TestQueryPreprocessor:
    """QueryPreprocessor 测试"""

    def test_detect_language_chinese(self):
        from router import QueryPreprocessor
        pp = QueryPreprocessor()
        assert pp.detect_language('最新论文') == 'zh'
        assert pp.detect_language('什么是 RAG') == 'mixed'

    def test_detect_language_english(self):
        from router import QueryPreprocessor
        pp = QueryPreprocessor()
        assert pp.detect_language('latest LLM paper') == 'en'

    def test_rewrite_normalizes_whitespace(self):
        from router import QueryPreprocessor
        pp = QueryPreprocessor()
        assert pp.rewrite('  hello   world  ') == 'hello world'

    def test_generate_variants_chinese(self):
        from router import QueryPreprocessor
        pp = QueryPreprocessor()
        variants = pp.generate_variants('最新论文')
        assert len(variants) >= 1
        assert variants[0]['q'] == '最新论文'
        # 应该有英文变体
        en_variants = [v for v in variants if v['lang'] == 'en']
        assert len(en_variants) >= 1

    def test_preprocess_returns_tuple(self):
        from router import QueryPreprocessor
        pp = QueryPreprocessor()
        rewritten, variants = pp.preprocess('最新论文')
        assert isinstance(rewritten, str)
        assert isinstance(variants, list)


class TestRuleRouter:
    """RuleRouter 测试"""

    def test_strong_keyword_academic(self):
        from router import RuleRouter
        rr = RuleRouter()
        result = rr.match('最新 arxiv 论文')
        assert result is not None
        assert result['query_type'] == 'academic'
        assert result['confidence'] >= 0.9

    def test_strong_keyword_opensource(self):
        from router import RuleRouter
        rr = RuleRouter()
        result = rr.match('github 开源项目')
        assert result is not None
        assert result['query_type'] == 'opensource'

    def test_comparison_vs(self):
        from router import RuleRouter
        rr = RuleRouter()
        result = rr.match('LangChain vs LlamaIndex')
        assert result is not None
        assert result['query_type'] == 'comparison'

    def test_no_match_returns_none(self):
        from router import RuleRouter
        rr = RuleRouter(accept_threshold=0.99)
        # 无任何关键词命中
        result = rr.match('xyz abc qwe')
        assert result is None

    def test_regex_doi(self):
        from router import RuleRouter
        rr = RuleRouter()
        result = rr.match('论文 10.1038/nature12373')
        assert result is not None
        assert result['query_type'] == 'academic'


class TestCircuitBreaker:
    """CircuitBreaker 测试"""

    def test_initial_state_closed(self):
        from router import CircuitBreaker
        cb = CircuitBreaker()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.can_call() is True

    def test_trip_to_open(self):
        from router import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.can_call() is False

    def test_success_resets(self):
        from router import CircuitBreaker
        cb = CircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.failure_count == 0

    def test_half_open_after_timeout(self):
        from router import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        time.sleep(0.15)
        assert cb.can_call() is True
        assert cb.state == CircuitBreaker.HALF_OPEN


class TestQueryRouter:
    """QueryRouter 主类测试"""

    def test_route_academic(self):
        from router import QueryRouter
        r = QueryRouter()
        d = r.route('最新 LLM 论文', {})
        assert d.query_type == 'academic'
        assert 'arxiv' in d.engine_chain
        assert d.confidence >= 0.8

    def test_route_opensource(self):
        from router import QueryRouter
        r = QueryRouter()
        d = r.route('RAG 开源实现', {})
        assert d.query_type == 'opensource'
        assert 'oss-finder' in d.engine_chain

    def test_route_definition(self):
        from router import QueryRouter
        r = QueryRouter()
        d = r.route('什么是 RAG', {})
        assert d.query_type == 'definition'

    def test_route_comparison(self):
        from router import QueryRouter
        r = QueryRouter()
        d = r.route('LangChain vs LlamaIndex', {})
        assert d.query_type == 'comparison'

    def test_route_general_fallback(self):
        from router import QueryRouter
        r = QueryRouter()
        d = r.route('量子计算原理', {})
        assert d.query_type == 'general'
        assert d.confidence < 0.8  # 低置信度

    def test_time_sensitivity_realtime(self):
        from router import QueryRouter
        r = QueryRouter()
        d = r.route('今天 AI 新闻', {})
        assert d.time_sensitivity == 'realtime'

    def test_authority_high(self):
        from router import QueryRouter
        r = QueryRouter()
        d = r.route('arxiv 论文', {})
        assert d.authority_need == 'high'

    def test_build_engine_chain_dedup(self):
        from router import QueryRouter
        chain = QueryRouter.build_engine_chain('academic', ['opensource'])
        assert 'arxiv' in chain
        assert 'oss-finder' in chain
        # 无重复
        assert len(chain) == len(set(chain))

    def test_filter_engines_by_breaker(self):
        from router import QueryRouter
        r = QueryRouter()
        # 打开 arxiv 断路器
        r.get_breaker('arxiv').record_failure()
        r.get_breaker('arxiv').record_failure()
        r.get_breaker('arxiv').record_failure()
        filtered = r.filter_engines_by_breaker(['arxiv', 'tavily'])
        assert 'arxiv' not in filtered
        assert 'tavily' in filtered


# ============================================================
# engines/academic_fulltext.py 测试（v5.1 新增）
# ============================================================

class TestArxivFulltextEngine:
    """ArxivFulltextEngine 测试"""

    def test_metadata(self):
        from engines.academic_fulltext import ArxivFulltextEngine
        e = ArxivFulltextEngine()
        m = e.metadata
        assert m.name == 'arxiv-fulltext'
        assert m.layer == 1
        assert m.is_china_friendly is True
        assert m.requires_config is False
        assert 'fulltext' in m.capabilities
        assert 'latex' in m.capabilities

    def test_rate_limit_delays(self):
        from engines.academic_fulltext import ArxivFulltextEngine
        e1 = ArxivFulltextEngine()
        e2 = ArxivFulltextEngine()
        # 类变量共享，连续调用应被限速
        e1._rate_limit()
        start = time.time()
        e2._rate_limit()
        elapsed = time.time() - start
        # 至少等待了部分时间（允许一些误差）
        assert elapsed >= 0.5  # 宽松断言，避免 CI 不稳定

    def test_pdf_url_template(self):
        from engines.academic_fulltext import ArxivFulltextEngine
        e = ArxivFulltextEngine()
        assert '2404.19756' in e.PDF_URL_TEMPLATE.format(paper_id='2404.19756')


class TestUnpaywallEngine:
    """UnpaywallEngine 测试"""

    def test_metadata(self):
        from engines.academic_fulltext import UnpaywallEngine
        e = UnpaywallEngine()
        m = e.metadata
        assert m.name == 'unpaywall'
        assert m.layer == 1
        assert m.is_china_friendly is True
        assert 'oa' in m.capabilities
        assert 'UNPAYWALL_EMAIL' in m.config_keys

    def test_get_email_from_env(self):
        from engines.academic_fulltext import UnpaywallEngine
        e = UnpaywallEngine()
        old = os.environ.get('UNPAYWALL_EMAIL')
        try:
            os.environ['UNPAYWALL_EMAIL'] = 'test@example.com'
            email = e._get_email()
            assert email == 'test@example.com'
        finally:
            if old is None:
                os.environ.pop('UNPAYWALL_EMAIL', None)
            else:
                os.environ['UNPAYWALL_EMAIL'] = old

    def test_get_email_default(self):
        from engines.academic_fulltext import UnpaywallEngine
        e = UnpaywallEngine()
        old = os.environ.pop('UNPAYWALL_EMAIL', None)
        try:
            email = e._get_email()
            assert email  # 应该有默认值
        finally:
            if old is not None:
                os.environ['UNPAYWALL_EMAIL'] = old


class TestCitationGraphEngine:
    """CitationGraphEngine 测试"""

    def test_metadata(self):
        from engines.academic_fulltext import CitationGraphEngine
        e = CitationGraphEngine()
        m = e.metadata
        assert m.name == 's2-citation-graph'
        assert m.layer == 1
        assert 'citation_graph' in m.capabilities
        assert 'intents' in m.capabilities


# ============================================================
# engines/crawl4ai_engine.py 测试（v5.1 新增）
# ============================================================

class TestCrawl4aiEngine:
    """Crawl4aiEngine 测试"""

    def test_metadata(self):
        from engines.crawl4ai_engine import Crawl4aiEngine
        e = Crawl4aiEngine()
        m = e.metadata
        assert m.name == 'crawl4ai'
        assert m.layer == 3
        assert m.requires_config is True
        assert 'CRAWL4AI_URL' in m.config_keys
        assert 'extract' in m.capabilities
        assert 'crawl' in m.capabilities

    def test_not_configured_when_no_env(self):
        from engines.crawl4ai_engine import Crawl4aiEngine
        e = Crawl4aiEngine()
        old = os.environ.pop('CRAWL4AI_URL', None)
        try:
            assert e.is_available() is False
        finally:
            if old is not None:
                os.environ['CRAWL4AI_URL'] = old


class TestLayeredCrawler:
    """LayeredCrawler 测试"""

    def test_can_instantiate(self):
        from engines.crawl4ai_engine import LayeredCrawler
        crawler = LayeredCrawler()
        assert crawler is not None


if __name__ == "__main__":
    pytest.main([__file__, '-v'])
