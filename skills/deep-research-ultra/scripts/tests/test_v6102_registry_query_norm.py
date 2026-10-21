# -*- coding: utf-8 -*-
"""v6.102：注册表类子源的**查询词语言**——中文词进 ASCII 索引就是查不到。

## 起因（v6.101 上线后的实网复验，2026-10-21）

v6.101 补了 npm / crates.io / GitLab / smithery 四个子源，端点全通、解析全对，
但**端到端跑一次就露馅**：查询词「找一个现成的 deep research skill」原样传下去，
npm 回的是 `dsh-mcp-connector` / `@antv/g-plugin-canvas-picker` / `openxiangda-cli`
——**5 条全不相干**；相关性判定器把 10 条全判成 unrated，Lead 拿到的是一堆噪声。

根因不是解析，是**语言**：这四个源都按 ASCII 名索引（包名、项目路径、MCP
server 名），中文词进去只能召回泛匹配。GitLab 更直接：中文 search 词回
**HTTP 500**。

## 先量后写（同一天，两组对照查询）

| 源 | 原样传中文 | 只留 ASCII 词 |
|---|---|---|
| npm | dsh-mcp-connector / @antv/g-plugin-canvas-picker / openxiangda-cli / html-to-md / minigame-api-typings | pi-deep-research / deep-research-skill / @mimo-ai/plugin / @mimo-ai/sdk / verified-deep-research |
| smithery | silly-geese/estonian-mcp / liqi-cuhk/cuqu-mcp / 7388603/cn-hotrank | tofan96you/deep-research-mcp / dev-chad/skilldb-catalog / hyperresearch/hyperresearch |
| GitLab | **HTTP 500** | z3kigz/Skywork-Skills / kelseyrecinas/deep-learning-intensive |

skills.sh 是**语义**搜索：纯中文「深度调研工具」能召回 deep-research-skill、
auto-deep-research、deep-research-zh —— 所以它**不改写查询词**（实测形状不同，
处理方式就该不同）。

## 这批测试的判据边界

本文件**不打网络**：monkeypatch 把 `_http_get_json` 换成"记录 URL 的假端点"，
断言**发出去的查询词**是什么形状。被测行为是「查询词怎么改写」，
不是「上游今天返回什么」——后者归 v6.101 的 fixture 判据管。
"""
from __future__ import annotations

import importlib
import sys
import urllib.parse
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

import pytest                                    # noqa: E402

_mod = importlib.import_module("engines.marketplaces")

CJK_QUERY = "找一个现成的 deep research skill"
PURE_CJK = "深度调研工具"


@pytest.fixture()
def mkt():
    return _mod.SkillMarketEngine()


@pytest.fixture()
def oss():
    return _mod.OssRegistryEngine()


def _capture(monkeypatch, payload):
    """把 _http_get_json 换成记录 URL 的假端点（不发网络）。"""
    seen = []

    def _fake(url, **kw):
        seen.append(url)
        return payload

    monkeypatch.setattr(_mod, "_http_get_json", _fake)
    return seen


# ============================================================ 词元抽取本身


def test_ascii_query_drops_cjk_and_keeps_ascii_tokens():
    """中文词要被剔除，ASCII 词按原顺序保留。"""
    assert _mod._ascii_query(CJK_QUERY) == "deep research skill"
    assert _mod._ascii_query("用 rust 写的 pdf 解析器") == "rust pdf"


def test_ascii_query_keeps_package_and_path_shapes():
    """包名/项目路径里的 . _ @ / + - 不能被切碎。"""
    assert _mod._ascii_query("@mimo-ai/plugin") == "mimo-ai/plugin"
    assert _mod._ascii_query("crates.io/api/v1") == "crates.io/api/v1"


def test_pure_chinese_query_yields_no_ascii_tokens():
    """纯中文提不出 ASCII 词 —— 这正是「不能瞎编译名」的边界。"""
    assert _mod._ascii_query(PURE_CJK) == ""


def test_registry_query_falls_back_to_original_for_pure_chinese():
    """提不出 ASCII 词时**原样传回**并标 non-ascii，不编造译名。"""
    used, lang = _mod._registry_query(PURE_CJK)
    assert used == PURE_CJK
    assert lang == "non-ascii"


def test_registry_query_uses_ascii_form_when_available():
    used, lang = _mod._registry_query(CJK_QUERY)
    assert used == "deep research skill"
    assert lang == "ascii"


# ============================================================ 发出去的查询词形状


def test_npm_query_is_normalized_to_ascii(oss, monkeypatch):
    seen = _capture(monkeypatch, {"objects": []})
    oss._npm(CJK_QUERY, 5)
    assert seen, "npm 子源没有发出请求"
    q = urllib.parse.parse_qs(urllib.parse.urlparse(seen[0]).query)["text"][0]
    assert q == "deep research skill"
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in q), \
        "npm 查询词里还留着中文 —— 那是泛匹配的路"


def test_smithery_query_is_normalized_to_ascii(mkt, monkeypatch):
    seen = _capture(monkeypatch, {"servers": []})
    mkt._smithery(CJK_QUERY, 5)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(seen[0]).query)["q"][0]
    assert q == "deep research skill"


def test_gitlab_query_is_normalized_to_ascii(oss, monkeypatch):
    seen = _capture(monkeypatch, [])
    oss._gitlab(CJK_QUERY, 5)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(seen[0]).query)["search"][0]
    assert q == "deep research skill"


def test_crates_query_is_normalized_to_ascii(oss, monkeypatch):
    seen = _capture(monkeypatch, {"crates": []})
    oss._crates(CJK_QUERY, 5)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(seen[0]).query)["q"][0]
    assert q == "deep research skill"


def test_skills_sh_keeps_the_original_query(mkt, monkeypatch):
    """skills.sh 是语义搜索、中文能听懂（实测）——**不许**拿掉中文。"""
    seen = _capture(monkeypatch, {"skills": []})
    mkt._skills_sh(CJK_QUERY, 5)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(seen[0]).query)["q"][0]
    assert q == CJK_QUERY


def test_pure_chinese_still_queries_the_source(oss, monkeypatch):
    """纯中文查询**照发**（不静默跳过、不伪造译名），只是标出低置信。"""
    seen = _capture(monkeypatch, {"objects": [{"package": {"name": "pkg-x"}}]})
    got = oss._npm(PURE_CJK, 5)
    assert seen, "纯中文查询被静默丢掉了 —— 那是丢数据，不是降级"
    q = urllib.parse.parse_qs(urllib.parse.urlparse(seen[0]).query)["text"][0]
    assert q == PURE_CJK
    assert got and got[0].raw["query_language"] == "non-ascii"
    assert "纯中文" in got[0].content, "低置信必须写在正文里，不能只存在 raw 里"


def test_normalized_results_carry_the_query_actually_used(oss, monkeypatch):
    """结果里要能查回「到底发了什么查询词」——溯源链不能断在这儿。"""
    _capture(monkeypatch, {"objects": [{"package": {"name": "pi-deep-research"}}]})
    got = oss._npm(CJK_QUERY, 5)
    assert got
    assert got[0].raw["query_used"] == "deep research skill"
    assert got[0].raw["query_language"] == "ascii"
    assert "规范化" in got[0].content, "改写了查询词就要在正文里说明"


def test_semantic_source_marks_its_query_language(mkt, monkeypatch):
    """skills.sh 的 raw 也要标 language='semantic'，与注册表区分开。"""
    _capture(monkeypatch, {"skills": [{"source": "o/r", "skillId": "s1",
                                        "installs": 3}]})
    got = mkt._skills_sh(CJK_QUERY, 5)
    assert got
    assert got[0].raw["query_language"] == "semantic"
    assert got[0].raw["query_used"] == CJK_QUERY
