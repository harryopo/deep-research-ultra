"""v6.17.0：Lead 按语料语言给检索词，而不是把同一句中文问题发给所有引擎。

起因（2026-09-23 离线复测）：同一批人工核对过**确实切题**的英文论文，
中文提问下 relevance 23.6 / 34.5 / 28.6，换成英文提问 29.2 / 58.3 / 47.5（均值 +16.1）。
按 relevance<50 判噪的规则，中文提问时 3/3 全被当成噪声——这正是那次实跑
"验证率 0%、带回薄荷醇外泌体论文"的来路。

router 的多语言变体救不了这件事：该主题下它只产出 1 条变体（原查询本身），
因为 zh_to_en 词典只有 34 个通用词（论文/研究/开源/部署/模型），
证据 / 溯源 / 可追溯 / 引用 / 幻觉 / 编码 / 智能体 一个都不在册；即使命中，
得到的也只是中英混排的 `大language model的推理能力`，英文库照样搜不到。

翻译交给 Lead（它会说英文），引擎侧只需要收对方向：
`--source-query 引擎名=查询词` 可重复，未点名的引擎仍用主题查询。
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from engines.base import EngineMetadata, SearchResult  # noqa: E402
import research  # noqa: E402

TOPIC = 'AI 编码 Agent 的证据溯源做法 可追溯 引用对齐 防幻觉'
EN = 'AI coding agent evidence provenance claim source traceability hallucination'
# 一段真实切题的英文摘要：只含英文词，中文主题查询与它在字面上零重叠
ON_TOPIC_EN = ('Maps every claim in an agent produced report back to its source. '
               'Traceability, citation alignment and anti-hallucination checks for '
               'coding agents.')


class _EchoEngine:
    """把收到的查询原样回显在结果里，并记下调用顺序。"""

    def __init__(self, name):
        self.metadata = EngineMetadata(
            name=name, layer=1, description=f'{name} desc',
            requires_config=False, config_keys=[],
            capabilities=['search', 'academic'], priority=1)
        self.calls = []

    def get_name(self):
        return self.metadata.name

    def get_layer(self):
        return self.metadata.layer

    def has_capability(self, cap):
        return cap in self.metadata.capabilities

    def is_available(self):
        return True

    def is_configured(self):
        return True

    def search(self, query, max_results=10, **kwargs):
        self.calls.append(query)
        return [SearchResult(title='Claim to source traceability for coding agents',
                             url=f'https://src.example/{self.metadata.name}/1',
                             content=ON_TOPIC_EN,
                             source=self.metadata.name, score=0.8)]


def _registry(engines):
    from engines.base import EngineRegistry
    reg = EngineRegistry()
    for e in engines:
        reg.register(e)
    return reg


def _args(**over):
    base = dict(query=TOPIC, sources='alpha,beta', source_query=None,
                all=False, limit=10, depth='standard', effort='quick', breadth=1,
                dimensions=None, perspectives=None, reflect_rounds=1,
                language='zh', region='cn', ledger=None, auto_claim=False,
                no_cache=True, no_plan=True, min_score=0, min_relevance=0,
                llm_score=False, format='markdown', output=None)
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """缓存默认落在 ~/.cache/，跨轮次共享会让"有没有命中缓存"这种断言看运气。"""
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, 'CACHE_DIR', tmp_path / 'cache')


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return [_EchoEngine('alpha'), _EchoEngine('beta')]


def test_named_engine_gets_its_own_query(pair):
    """点名的引擎收专用查询词，没点名的仍收主题查询。"""
    research.cmd_search(_args(source_query=[f'alpha={EN}']), _registry(pair))
    assert pair[0].calls == [EN], 'alpha 没拿到专用查询词'
    assert pair[1].calls == [TOPIC], 'beta 未被点名，应沿用主题查询'


def test_result_scored_against_the_query_that_found_it(pair, capsys):
    """端到端：cmd_search 对 alpha 的命中按 EN 打分，对 beta 仍按主题查询。

    两条命中的标题与正文**完全相同**，唯一差别是各自的检索词。
    相关性 76.7（英文词）对 28.0（中文词），所以"低相关"告警该从 2 条降到 1 条；
    打分若仍统一用主题查询，两条会同分，告警条数不变。
    """
    research.cmd_search(_args(source_query=[f'alpha={EN}'], min_relevance=60),
                        _registry(pair))
    err = capsys.readouterr().err
    m = re.search(r'(\d+) 条与查询词几乎无重叠', err)
    assert m, f'没找到低相关告警那行，断言失去意义：{err[-400:]}'
    assert m.group(1) == '1', (
        f'两条相同内容的命中，一条按英文词判、一条按中文词判，低相关应只剩 1 条，'
        f'实际 {m.group(1)} 条——说明打分没跟着各自的检索词走')


def test_unknown_engine_name_in_source_query_warns(pair, capsys):
    """写错引擎名不能静默失效——查询词没送出去，表面看却像"搜过了"。"""
    research.cmd_search(_args(source_query=['nope-engine=' + EN]), _registry(pair))
    err = capsys.readouterr().err
    assert 'nope-engine' in err and ('未匹配' in err or '没有' in err), \
        f'点名了不存在的引擎却没警告：{err[-400:]}'


def test_lead_query_reaches_the_evidence_ledger(tmp_path, monkeypatch):
    """换词要一路走到账本：arxiv 那条证据记的必须是英文检索词。

    与 v6.16.6 拼接：cmd_search 把 Lead 下发的词盖到命中上，_write_ledger 按命中上
    的记录入账。两头任一断了，账本里就又是"主题查询搜出了英文结果"这种没法复现的账。
    """
    import json
    monkeypatch.chdir(tmp_path)
    led = tmp_path / 'led'
    engines = [_EchoEngine('alpha'), _EchoEngine('beta')]
    research.cmd_search(_args(source_query=[f'alpha={EN}'], ledger=str(led)),
                        _registry(engines))
    rows = [json.loads(l) for l in (led / 'evidence.jsonl').read_text(encoding='utf-8').splitlines()
            if l.strip()]
    alpha = [r for r in rows if 'alpha' in r['url']]
    beta = [r for r in rows if 'beta' in r['url']]
    assert alpha and beta, f'两条命中没能都入账：{rows}'
    assert alpha[0]['query'] == EN, f'alpha 入账的查询词不对：{alpha[0]["query"]!r}'
    assert beta[0]['query'] == TOPIC, f'beta 入账的查询词不对：{beta[0]["query"]!r}'


def test_source_query_changes_do_not_hit_stale_cache(tmp_path, monkeypatch):
    """换了专用查询词的二跑不得命中上一跑的缓存，否则改了等于没改。"""
    monkeypatch.chdir(tmp_path)
    e1 = [_EchoEngine('alpha'), _EchoEngine('beta')]
    research.cmd_search(_args(source_query=[f'alpha={EN}'], no_cache=False), _registry(e1))

    e2 = [_EchoEngine('alpha'), _EchoEngine('beta')]
    EN2 = 'agentic AI citation verification source attribution'
    research.cmd_search(_args(source_query=[f'alpha={EN2}'], no_cache=False), _registry(e2))
    assert all(e.calls for e in e2), (
        '换了专用查询词却被上一跑的缓存服务了（缓存命中时引擎不会被叫到）')
    assert e2[0].calls[-1] == EN2, f'专用查询词没生效：{e2[0].calls}'
