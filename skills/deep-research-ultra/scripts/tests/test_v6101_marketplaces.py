# -*- coding: utf-8 -*-
"""v6.101：Skill/MCP 市场与 OSS 生态注册表 —— 每条能力有离线判据。

起因（用户实测反馈，2026-10-20）：
  ① 「只会从官方去找官方 skill，不会去 skill 相关的市场找 skill」
     —— 根因：来源面 0 个市场源 + 路由 STRONG/WEAK 关键词表里没有 skill/mcp，
     这类查询掉进 general 链走通用网搜，官方文档自然占满结果。
  ② 「开源方案搜索能力低」
     —— 根因：ENGINE_CHAIN_MAP['opensource'] 只有 GitHub(深度) + Gitee(需
     token) + ModelScope(仅 lookup)，npm/crates/GitLab 这类免 key 注册表全无。

先量后写的承诺在 fixtures 里：market_skills_sh.json / market_smithery.json /
oss_npm.json / oss_crates.json / oss_gitlab.json 是 2026-10-20 对真实端点
各抓一次的**完整响应**（scripts/tests/fixtures/）。解析器照这些真实形状写，
改坏形状这批测试会红。所有测试不打网络 —— 网络抓取的环节在测试里被
monkeypatch 指到 fixtures。
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

import pytest                                    # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIX = {
    "skills_sh": "market_skills_sh.json",
    "smithery": "market_smithery.json",
    "npm": "oss_npm.json",
    "crates": "oss_crates.json",
    "gitlab": "oss_gitlab.json",
}
_mod = importlib.import_module("engines.marketplaces")


def _data(key: str):
    return json.loads((FIXTURES / FIX[key]).read_text(encoding="utf-8"))


def _feed(monkeypatch, key: str) -> None:   # type: ignore[no-untyped-def]
    """把 _http_get_json 指到 fixture —— 测试不发网络请求。"""
    data = _data(key)
    monkeypatch.setattr(_mod, "_http_get_json", lambda url, **kw: data)


def _sr(tag: str, extra_raw: dict):   # type: ignore[no-untyped-def]
    return _mod.SearchResult(title=tag, url=f"u://{tag}", content="",
                             source="x", score=0.0, engine="e", raw=extra_raw)


# ============================================================ 解析器（fixtures 实证）


@pytest.fixture()
def mkt():
    return _mod.SkillMarketEngine()


@pytest.fixture()
def oss():
    return _mod.OssRegistryEngine()


def test_skills_sh_parser_carries_real_installs(mkt, monkeypatch):
    """实测响应解析：安装量是真数、GitHub 源仓库链接可派生、页 URL 实测形状。"""
    _feed(monkeypatch, "skills_sh")
    got = mkt._skills_sh("deep research", 5)
    assert isinstance(got, list) and got, "真实响应必须解析出条目"
    first = got[0]
    # 实测第一条：firecrawl/firecrawl-workflows，installs=35224
    assert first.raw["installs"] == 35224, first.raw["installs"]
    assert "35224" in first.content, "安装量没进摘要：%r" % first.content
    assert first.raw["github_repo"] == ("https://github.com/"
                                        "firecrawl/firecrawl-workflows")
    assert first.url == ("https://skills.sh/firecrawl/firecrawl-workflows/"
                         "firecrawl-deep-research"), first.url


def test_skills_sh_item_without_installs_does_not_fake_zero(mkt, monkeypatch):
    """端点没给 installs 就明示没有，不许编 0（编 0 会被当成「没安装」的假信号）。"""
    monkeypatch.setattr(_mod, "_http_get_json",
                        lambda url, **kw: {"skills": [
                            {"id": "x/y/z", "source": "x/y", "skillId": "z"}]})
    got = mkt._skills_sh("q", 5)
    assert got and got[0].raw["installs"] is None, got[0].raw
    assert got[0].score == 0.0
    assert "安装量" not in got[0].content, "没数据的字段不许出摘要"


def test_smithery_parser_uses_api_self_attested_homepage(mkt, monkeypatch):
    """URL 只信 API 自证 homepage；orbisapi 条目证明项目官网也照实用。"""
    _feed(monkeypatch, "smithery")
    got = mkt._smithery("research", 5)
    assert got and got[0].raw["useCount"] == 95, got[0].raw["useCount"]
    assert got[0].url == "https://smithery.ai/servers/consensus", got[0].url
    assert got[0].raw["constructed_url"] is False
    # 实测第二条 homepage=https://orbisapi.com —— 平台给的门户字段原样保留
    assert got[1].raw["homepage"] == "https://orbisapi.com", got[1].raw
    assert got[1].url == "https://orbisapi.com"


def test_smithery_missing_homepage_constructs_and_flags(mkt, monkeypatch):
    """smithery 对任意 slug 都回 200 SPA 壳（实测 bogus 也 200）—— 构造链接
    无从自证，必须打标：raw.constructed_url=True 且正文写明它是构造值。"""
    monkeypatch.setattr(_mod, "_http_get_json", lambda url, **kw: {
        "servers": [{"qualifiedName": "no-homepage-x", "useCount": 3}]})
    got = mkt._smithery("q", 5)
    assert got and got[0].raw["constructed_url"] is True, got[0].raw
    assert got[0].url == "https://smithery.ai/servers/no-homepage-x"
    assert "构造" in got[0].content, "构造链接必须在正文里说清楚"


def test_npm_parser_tolerates_string_dependents(oss, monkeypatch):
    """实测 dependents 有时是字符串（"129"）有时是整数 —— 统一成 int。"""
    _feed(monkeypatch, "npm")
    got = oss._npm("evaluator", 3)
    assert got and got[0].raw["dependents"] == 129, got[0].raw
    assert got[0].raw["monthly_downloads"] == 12419728, got[0].raw
    assert got[0].url == ("https://www.npmjs.com/package/"
                          "math-expression-evaluator"), got[0].url
    # npm 的 repository 实测是 git+https://…​.git —— 规范化成可打开的 https 链接
    assert got[0].raw["github_repo"] == ("https://github.com/redhivesoftware/"
                                         "math-expression-evaluator"), got[0].raw


def test_crates_parser_slug_url_and_real_downloads(oss, monkeypatch):
    _feed(monkeypatch, "crates")
    got = oss._crates("html parser", 3)
    # fixture 首条实测是 fast-html-parser —— 期望取自 fixture 自证字段，不写死
    expect_id = _data("crates")["crates"][0]["id"]
    assert got and got[0].url == f"https://crates.io/crates/{expect_id}", got[0].url
    expect = _data("crates")["crates"][0]["downloads"]
    assert got[0].raw["downloads"] == expect, "下载量要原样带出"
    assert f"[总下载] {expect}" in got[0].content
    assert got[0].raw["github_repo"].startswith("https://"), got[0].raw


def test_gitlab_parser_uses_web_url_and_stars(oss, monkeypatch):
    _feed(monkeypatch, "gitlab")
    data = _data("gitlab")
    got = oss._gitlab("research", 3)
    assert got and got[0].url == data[0]["web_url"], got[0].url
    assert got[0].raw["star_count"] == data[0]["star_count"]
    assert f"[Stars] {data[0]['star_count']}" in got[0].content


# ============================================================ 多子源合并


def test_market_interleaves_both_markets_within_quota():
    """实测缺陷回归：第一版拼接+截断会把 smithery 全吃掉（5 条全是 skills.sh）。
    轮转合并后两个市场在限额内都要露面 —— 市场生态本来就是要补的东西。"""
    a = [_sr(f"A{i}", {"marketplace": "A"}) for i in range(5)]
    b = [_sr("B0", {"marketplace": "B"})]
    out = _mod._interleave([a, b])[:5]
    tags = {x.raw["marketplace"] for x in out}
    assert tags == {"A", "B"}, "两个市场都该在限额内露面：%s" % tags


def test_oss_registry_interleaves_three_registries():
    batches = [
        [_sr(f"npm{i}", {"registry": "npm"}) for i in range(3)],
        [_sr("cr0", {"registry": "crates.io"})],
        [_sr(f"gl{i}", {"registry": "gitlab"}) for i in range(2)],
    ]
    out = _mod._interleave(batches)[:4]
    tags = {x.raw["registry"] for x in out}
    assert tags == {"npm", "crates.io", "gitlab"}, "三家注册表都要露面：%s" % tags


# ============================================================ 通道语义（[]≠None）


def test_all_channels_down_returns_none_not_empty(monkeypatch, mkt):
    """两个市场都崩 = 通道级失败 → None（上层才好降级）；[] 留给「查无」。"""
    monkeypatch.setattr(_mod.SkillMarketEngine, "_skills_sh",
                        lambda self, q, n: None)
    monkeypatch.setattr(_mod.SkillMarketEngine, "_smithery",
                        lambda self, q, n: None)
    assert mkt.search("任意") is None


def test_all_channels_empty_returns_empty_list(monkeypatch, mkt):
    monkeypatch.setattr(_mod.SkillMarketEngine, "_skills_sh",
                        lambda self, q, n: [])
    monkeypatch.setattr(_mod.SkillMarketEngine, "_smithery",
                        lambda self, q, n: [])
    assert mkt.search("任意") == []


def test_one_market_down_still_partial(monkeypatch, mkt):
    """skills.sh 挂了 smithery 还在 —— 半数通道失败不算引擎失败，但要写在
    channel_note 里让人看得见，不许静默吞掉。"""

    def boom(self, q, n):
        raise RuntimeError("net down")

    monkeypatch.setattr(_mod.SkillMarketEngine, "_skills_sh", boom)
    monkeypatch.setattr(_mod.SkillMarketEngine, "_smithery",
                        lambda self, q, n: [
                            _sr("x", {"marketplace": "smithery"})])
    got = mkt.search("任意")
    assert got and got[0].raw["marketplace"] == "smithery"
    assert "channel_note" in got[0].raw, got[0].raw


# ============================================================ 可用性语义


def test_market_available_when_any_host_up(monkeypatch):
    def fake(host, timeout=3.0, **kw):
        return host == _mod.HOST_SMITHERY
    monkeypatch.setattr(_mod, "_host_reachable", fake)
    assert _mod.SkillMarketEngine().is_available() is True
    monkeypatch.setattr(_mod, "_host_reachable", lambda host, **kw: False)
    assert _mod.SkillMarketEngine().is_available() is False


def test_oss_registry_available_when_any_host_up(monkeypatch):
    """第一版只探 npm：npm 被墙而 crates/GitLab 活着会误报不可用 —— 必须任一即可。"""
    def fake(host, timeout=3.0, **kw):
        return host == _mod.HOST_CRATES
    monkeypatch.setattr(_mod, "_host_reachable", fake)
    assert _mod.OssRegistryEngine().is_available() is True
    monkeypatch.setattr(_mod, "_host_reachable", lambda host, **kw: False)
    assert _mod.OssRegistryEngine().is_available() is False


# ============================================================ 路由接线（离线）


def test_opensource_chain_contains_market_engines_in_order():
    from router import ENGINE_CHAIN_MAP
    chain = ENGINE_CHAIN_MAP["opensource"]
    for name in ("skill-market", "oss-registry"):
        assert name in chain, "链里必须有 %s（这次优化就是为它）" % name
    # 深度 GitHub 仍在市场引擎之前：市场不是替代 GitHub 深挖，是补生态位
    assert chain.index("github-deep-search") < chain.index("skill-market")
    assert chain.index("skill-market") < chain.index("oss-registry")


def test_skill_query_routes_to_opensource_chain():
    from router import QueryRouter
    d = QueryRouter().route("帮我找一个能做 PDF 解析的 Claude skill")
    assert d.query_type == "opensource", "skill 类查询掉进 general 就是这次的事故"
    assert "skill-market" in d.engine_chain, d.engine_chain
    d2 = QueryRouter().route("有没有类似 notion 的开源 mcp server")
    assert d2.query_type == "opensource", d2.query_type
    assert "oss-registry" in d2.engine_chain


def test_mcp_definition_query_not_hijacked():
    """'mcp' 只放 WEAK：定义类查询（MCP 协议含义）必须仍走 definition。
    若 opensource 用强词 'mcp'，这条就红 —— 路由关键词的波及面要被钉住。"""
    from router import QueryRouter
    d = QueryRouter().route("MCP 协议含义")
    assert d.query_type == "definition", d.query_type


# ============================================================ 出口白名单（守卫不松）


def test_egress_allowlist_extended_but_guard_intact():
    """新主机入白名单**且**守卫仍拦陌生主机 —— 这两句必须同时成立。"""
    from engines.fallback import _EGRESS_ALLOW, egress_denied_reason
    for host in ("skills.sh", "smithery.ai", "npmjs.org", "crates.io",
                 "gitlab.com"):
        assert host in _EGRESS_ALLOW, host
    # 后缀匹配：API 子域ageraality主机直接过
    for url in ("https://registry.smithery.ai/servers?q=x",
                "https://skills.sh/api/search?q=x",
                "https://registry.npmjs.org/-/v1/search",
                "https://crates.io/api/v1/crates",
                "https://gitlab.com/api/v4/projects"):
        assert egress_denied_reason(url) == "", (url, egress_denied_reason(url))
    # 陌生主机仍被拒；拒绝理由要提到白名单（不是变成无条件放行）
    reason = egress_denied_reason("https://evil.example.org/steal")
    assert reason and "白名单" in reason, reason


# ============================================================ 注册面（真注册表）


def test_registry_registers_new_engines_as_layer2():
    import research
    reg = research.build_registry()
    for name in ("skill-market", "oss-registry"):
        e = reg.get(name)
        assert e is not None, "build_registry 必须注册 %s" % name
        assert e.get_layer() == 2, (name, e.get_layer())
        assert e.metadata.requires_config is False, "市场源必须免 key"
