"""v6.16.3 回归：--probe 不许把"连通性超时"报成"缺配置"。

缺陷原貌（本机 2026-09-23 实测）：
  ❌ semantic-scholar   0 条  缺少配置: S2_API_KEY     ← 那个 key 是可选的，真因是连通性探测超时
  ❌ openalex           0 条  依赖/服务未就绪          ← 功能探针根本没跑，被 is_available() 短路

根因：probe_engine 用 is_available() 当闸门，而免配置引擎的 is_available() 发的是
连通性请求；一超时就被当成"引擎不行"，于是（1）真正的功能探针没机会跑，
（2）失败原因靠 config_keys 猜，把可选 key 说成阻塞项。

修法边界：闸门换成"必需配置齐不齐"（与 --list 同一个判据），可选 key 不再充当
阻塞理由；连通性失败改由真实 search() 探针报出实际 HTTP 状态。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os  # noqa: E402

import probe  # noqa: E402
from engines.base import EngineMetadata, SearchResult  # noqa: E402


class _Eng:
    """最小引擎替身：三个判据各自可控，免得把原因混在一起。"""

    def __init__(self, name='fake', requires_config=False, config_keys=(),
                 available=True, results=None, raises=None):
        self.metadata = EngineMetadata(
            name=name, layer=1, description='fake desc',
            requires_config=requires_config, config_keys=list(config_keys),
            capabilities=['search', 'academic'])
        self._available = available
        self._results = results
        self._raises = raises
        self.search_calls = []

    def get_name(self):
        return self.metadata.name

    def has_capability(self, cap):
        return cap in self.metadata.capabilities

    def is_available(self):
        return self._available

    def is_configured(self):
        from engines.base import missing_required_config
        return not missing_required_config(self.metadata)

    def search(self, query, max_results=10, **kwargs):
        self.search_calls.append(query)
        if self._raises:
            raise self._raises
        return self._results


def _hits(n=2):
    return [SearchResult(title=f'论文 {i}', url=f'https://ex/{i}', content='c',
                         source='fake', score=0.9) for i in range(n)]


# ------------------------------------------------------------
# 闸门只看"必需配置"，不再被连通性抢跑
# ------------------------------------------------------------

class TestGateUsesConfigNotConnectivity:

    def test_keyless_engine_still_gets_a_real_functional_probe(self, monkeypatch):
        monkeypatch.delenv('S2_API_KEY', raising=False)
        eng = _Eng('openalex-like', available=False, results=_hits())
        rep = probe.probe_engine(eng, max_results=2)
        assert eng.search_calls, '连通性一说 False，功能探针就被跳过了'
        assert rep['status'] == probe.STATUS_OK, rep

    def test_required_key_missing_is_reported_as_config_and_not_probed(self, monkeypatch):
        monkeypatch.delenv('TAVILY_API_KEY', raising=False)
        eng = _Eng('tavily-like', requires_config=True,
                   config_keys=['TAVILY_API_KEY'], available=True, results=_hits())
        rep = probe.probe_engine(eng, max_results=2)
        assert rep['status'] == probe.STATUS_FAILED
        assert 'TAVILY_API_KEY' in rep['note'], rep
        assert not eng.search_calls, '真缺 key 时不必白跑一次探针'

    def test_optional_key_absent_is_never_called_missing_config(self, monkeypatch):
        """S2_API_KEY 是可选加速项：它不在，不能当成"你去申请个 key"的理由。"""
        monkeypatch.delenv('S2_API_KEY', raising=False)
        eng = _Eng('semantic-scholar-like', requires_config=False,
                   config_keys=['S2_API_KEY'], available=False, results=None)
        rep = probe.probe_engine(eng, max_results=2)
        assert eng.search_calls, '可选 key 不该短路功能探针'
        assert '缺少配置' not in rep['note'], rep['note']


# ------------------------------------------------------------
# 指引文案：可选 key 不许出现在"去申请"清单里
# ------------------------------------------------------------

class TestAdviceDoesNotBlameOptionalKeys:

    def test_optional_key_produces_no_export_instruction(self, monkeypatch):
        monkeypatch.delenv('S2_API_KEY', raising=False)
        eng = _Eng('semantic-scholar-like', requires_config=False,
                   config_keys=['S2_API_KEY'], available=False, results=None)
        rep = probe.probe_engine(eng, max_results=2)
        advice = ' || '.join(probe._advice_for(rep))
        assert 'export S2_API_KEY' not in advice, advice
        assert '缺 S2_API_KEY' not in advice, advice

    def test_required_key_still_produces_export_instruction(self, monkeypatch):
        monkeypatch.delenv('GITEE_TOKEN', raising=False)
        eng = _Eng('gitee-like', requires_config=True, config_keys=['GITEE_TOKEN'],
                   available=False, results=None)
        rep = probe.probe_engine(eng, max_results=2)
        advice = ' || '.join(probe._advice_for(rep))
        assert 'GITEE_TOKEN' in advice, advice


# ------------------------------------------------------------
# 真实引擎：semantic-scholar 不能再被报成缺 key
# ------------------------------------------------------------

class TestRealEngineNoLongerMisdiagnosed:

    def test_semantic_scholar_gets_probed_not_blamed_on_key(self, monkeypatch):
        from engines.academic_engines import SemanticScholarEngine
        monkeypatch.delenv('S2_API_KEY', raising=False)
        eng = SemanticScholarEngine()
        assert eng.metadata.requires_config is False
        calls = []
        monkeypatch.setattr(eng, 'search',
                            lambda q, max_results=10, **kw: calls.append(q) or None)
        monkeypatch.setattr(eng, 'is_available', lambda: False)
        rep = probe.probe_engine(eng, max_results=2)
        assert calls, '真引擎也被连通性短路了'
        assert '缺少配置' not in rep['note'], rep['note']
