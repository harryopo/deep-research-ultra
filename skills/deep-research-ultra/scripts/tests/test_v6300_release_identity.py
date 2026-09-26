"""v6.30.0 回归：GitHub Release 页与它的 REST 入口必须判成同一个制品。

实跑（2026-09-26，主题「本地小模型推理引擎选型」）：D5 维度 5 条 claim 的来源是
`github.com/vllm-project/vllm/releases/tag/v0.28.0` 这类**官方发布页**，按档 B 的
文档指引去反查官方 API `api.github.com/repos/vllm-project/vllm/releases/tags/v0.28.0`
——REST 路径多一个 `s`，`_github_key` 把它当普通 blob 之外的路径处理，于是同一个 release
长出两个指纹，5 条真反查**全部被拒**（拒词是"反查必须打在同一个制品上"）。

Release 说明是"版本 churn"这类结论唯一的一手载体，这条通道打不通就只能整批停在 pending。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import _artifact_key  # noqa: E402

WEB = 'https://github.com/vllm-project/vllm/releases/tag/v0.28.0'
API = 'https://api.github.com/repos/vllm-project/vllm/releases/tags/v0.28.0'
OTHER_TAG = 'https://github.com/vllm-project/vllm/releases/tag/v0.29.0'
REPO_ROOT = 'https://github.com/vllm-project/vllm'
README_BLOB = 'https://github.com/vllm-project/vllm/blob/main/README.md'
ASSET = 'https://github.com/vllm-project/vllm/releases/download/v0.28.0/wheel.whl'


def test_release_网页与_rest_入口同一制品():
    assert _artifact_key(WEB) == _artifact_key(API)


def test_不同_release_仍是不同制品():
    """归一不许把两个版本的发布说明并成一份——版本差异本身就是结论。"""
    assert _artifact_key(WEB) != _artifact_key(OTHER_TAG)


def test_release_不等于仓库根或_readme():
    """不许拿 README 去"反查"一条发布说明 claim。"""
    root, readme, release = (_artifact_key(x) for x in (REPO_ROOT, README_BLOB, WEB))
    assert root == readme, '仓库根与 README 本就同指一份内容（v6.20 归一）'
    assert release not in (root, readme)


def test_release_资源文件另算制品():
    """releases/download/<tag>/<file> 指向具体文件，不与发布页混同。"""
    assert _artifact_key(ASSET) != _artifact_key(WEB)


@pytest.mark.parametrize('url', [WEB, API])
def test_release_键里带_tag(url):
    assert 'v0.28.0' in _artifact_key(url).lower()
