"""v6.34.0 回归：学术论文推荐度表不许列 GitHub 仓库。

`PaperRecommender.rank_results` 以前只问"raw 是不是非空 dict"，不问它是不是论文，
而 `_html_recommendations` 把**全部**结果同时喂给两个推荐器。实测（本机直接调）：

    论文表里的条目: ['某论文', 'ggml-org/llama.cpp']
    GitHub 表里的条目: ['ggml-org/llama.cpp']

于是只要一次调研同时抓到仓库与论文（这是常态），报告里那张「学术论文推荐度」
就会把仓库当论文排进去，还给它打"引用影响/时效/权威/h-index"四维分——
一个 GitHub 仓库的 h-index 是无意义的数。反方向（GitHub 表混进论文）不会发生，
因为那边按 `repo_type == 'github'` 正着筛；这一侧没有对应的门。

判据取"是什么"而不是"像不像"：带 `repo_type=github` 或带 `full_name` 的一律不是论文。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.base import SearchResult  # noqa: E402
from recommend import GitHubRecommender, PaperRecommender  # noqa: E402
from report import ReportGenerator  # noqa: E402

REPO = SearchResult(
    title='ggml-org/llama.cpp', url='https://github.com/ggml-org/llama.cpp',
    content='LLM inference in C/C++', source='github-deep-search',
    raw={'full_name': 'ggml-org/llama.cpp', 'repo_type': 'github',
         'stars': 129502, 'description': 'LLM inference in C/C++'})
REPO_CODE = SearchResult(
    title='corp/app-builder: rag.py', url='https://github.com/corp/app-builder/blob/main/rag.py',
    content='在仓库源码里找到', source='github-code-search',
    raw={'full_name': 'corp/app-builder', 'repo_type': 'github', 'metadata_missing': True})
PAPER = SearchResult(
    title='某篇真论文', url='https://arxiv.org/abs/2405.04532v3', content='摘要正文',
    source='arxiv-fulltext',
    raw={'title': '某篇真论文', 'abstract': 'W4A8KV4 协同设计' * 12,
         'venue': 'arXiv', 'citation_count': 7})


def _paper_html(rows):
    ranked = PaperRecommender().rank_results(rows, '')
    return ReportGenerator()._render_paper_recommendations(ranked)


def _github_html(rows):
    ranked = GitHubRecommender().rank_results(rows, '', 'default')
    return ReportGenerator()._render_github_recommendations(ranked, 'default')


def test_论文表不收仓库():
    titles = [i['result'].title for i in PaperRecommender().rank_results([PAPER, REPO, REPO_CODE], '')]
    assert titles == ['某篇真论文'], f'仓库混进了论文表：{titles}'


def test_论文表照收论文():
    """对照面：不许把筛选做成"论文表永远空"。"""
    out = _paper_html([REPO, PAPER])
    assert '某篇真论文' in out
    assert '<td>7</td>' in out, '真实引用数仍要印出来'


def test_论文表里没有仓库链接():
    out = _paper_html([REPO, REPO_CODE, PAPER])
    assert 'github.com' not in out, '论文表里出现了仓库链接'


def test_github_表照收仓库且不收论文():
    out = _github_html([PAPER, REPO])
    assert 'ggml-org/llama.cpp' in out
    assert '某篇真论文' not in out


def test_两张表各自只出该出的行():
    """合起来看：同一次调研里仓库与论文各归一张表，不重复、不串味。"""
    rows = [PAPER, REPO, REPO_CODE]
    p = _paper_html(rows)
    g = _github_html(rows)
    assert 'llama.cpp' not in p and '某篇真论文' not in g
    assert '某篇真论文' in p
    assert 'llama.cpp' in g and 'app-builder' in g
