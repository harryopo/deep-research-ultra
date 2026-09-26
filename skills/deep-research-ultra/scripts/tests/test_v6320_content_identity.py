"""v6.32.0 回归：跨主机的同一份内容，凭"逐字片段两处都命中"绑成同一制品。

实跑（2026-09-26，主题「本地小模型推理引擎选型」）有 3 条 vLLM 文档结论卡在档 B：
来源登记的是文档站页面 `docs.vllm.ai/en/latest/getting_started/installation/gpu/index.html`，
仓库源文件在 `raw.githubusercontent.com/vllm-project/vllm/main/docs/.../gpu.md`——
两个主机、两条路径互推不出来，`_artifact_key` 判不同，`link-identity` 又只认书目标识符
（文档页没有 DOI/arXiv 号），于是"官方文档页 ↔ 官方仓库源文件"这对本该最硬的组合打不通。

本机实测（两侧都真取回正文）：
- `vLLM does not support Windows natively`、`OS: Linux`、`Python: 3.10 -- 3.13`
  两句在**文档页与仓库源文件里逐字都在** → 该判同一制品；
- `compute capability 7.5 or higher`、AMD/Intel 那些行只在文档页（写在别的文件里）
  → 拿 gpu.md 反查它必须被拒，**指错文件不能算凭据**。

所以凭据取"这条 claim 自己的逐字片段在两处正文里都命中"，不做任何路径猜测，
也不看整体相似度（导航、页脚、版权行会让两个无关页面"很像"）。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import ResearchLedger, _main  # noqa: E402

DOCS = 'https://docs.vllm.ai/en/latest/getting_started/installation/gpu/index.html'
REPO = 'https://raw.githubusercontent.com/vllm-project/vllm/main/docs/getting_started/installation/gpu.md'
OTHER = 'https://docs.vllm.ai/en/latest/getting_started/installation/cpu.html'

# 文档页正文（含导航噪声）与仓库源文件正文，只保留判据用到的片段
DOC_BODY = ('vLLM installation guide. nav menu. ' * 12 +
            'Supported backends OS: Linux Python: 3.10 -- 3.13 '
            'vLLM does not support Windows natively. Use WSL instead. '
            'footer copyright ' * 12)
REPO_BODY = ('# GPU\n\nvLLM does not support Windows natively. Use WSL instead.\n'
             'Prerequisites: OS: Linux, Python: 3.10 -- 3.13\n' + 'filler ' * 90)
# 只有文档页有那句话（AMD/Intel 段落写在别的文件里）
REPO_NO_HIT = '# GPU\n\nPrerequisites: OS: Linux\n' + 'filler ' * 90
SHELL_BODY = '404: Not Found'


@pytest.fixture()
def ledger(tmp_path, capsys):
    d = tmp_path / 'ledger'
    d.mkdir()
    led = ResearchLedger(str(d)).init()
    led.add_claim('文档原文说「vLLM does not support Windows natively.」', topic='t')
    cid = led.claims()[0]['id']
    led.add_source(cid, DOCS, title='vLLM GPU 安装文档', tier=1)
    capsys.readouterr()
    return led, cid


def _bodies(mapping):
    return lambda url: mapping.get(url, '')


def test_逐字片段两处都在就绑成同一制品(ledger, capsys):
    led, cid = ledger
    n = led.content_identity([cid], DOCS, REPO, body_of=_bodies(
        {DOCS: DOC_BODY, REPO: REPO_BODY}))
    capsys.readouterr()
    assert n == 1
    recs = [e for e in map(json.loads, open(led.entries_path, encoding='utf-8'))
            if e.get('type') == 'identity']
    assert recs and recs[0]['matched'].startswith('content:')
    assert 'windows natively' in recs[0]['matched'].lower()


def test_绑完档b反查能走通(ledger, capsys):
    """这条测的是闭环：identity 记录写进去后，verify_primary 必须认这条反查通道。"""
    led, cid = ledger
    led.content_identity([cid], DOCS, REPO, body_of=_bodies(
        {DOCS: DOC_BODY, REPO: REPO_BODY}))
    capsys.readouterr()
    assert led.verify_primary([cid], REPO, 'vLLM gpu.md', 'doc_source') == 1
    assert led.claims()[0]['status'] == 'verified'


def test_指错文件不许绑(ledger, capsys):
    """那句话不在这个文件里＝没有凭据，不能因为"都是 vLLM 官方"就放行。"""
    led, cid = ledger
    n = led.content_identity([cid], DOCS, REPO, body_of=_bodies(
        {DOCS: DOC_BODY, REPO: REPO_NO_HIT}))
    err = capsys.readouterr().err
    assert n == 0, err
    assert '拒绝 content-identity' in err and '两侧都命中' in err, err


def test_空壳页不许当凭据(ledger, capsys):
    led, cid = ledger
    n = led.content_identity([cid], DOCS, OTHER, body_of=_bodies(
        {DOCS: DOC_BODY, OTHER: SHELL_BODY}))
    capsys.readouterr()
    assert n == 0


def test_相邻两个引号不许拼成一段():
    """实跑撞出来的提取缺陷：`"OS: Linux" 与 "Python: 3.10 -- 3.13"` 这种写法，

    旧正则 `"(.{20,}?)"` 会把第一个引号的右半边和第二个的左半边一起吃进来，取出
    `os: linux" 与 "python: 3.10 -- 3.13` —— 这个拼接串在任何页面都不存在，
    于是**真有凭据的 claim 被判成"没命中"**（假阴性）。片段必须止于引号本身。
    """
    from ledger import _quote_spans
    spans = _quote_spans('前置条件逐字为 "OS: Linux" 与 "Python: 3.10 -- 3.13"，另见 `compute capability 7.5 or higher`')
    assert 'os: linux" 与 "python: 3.10 -- 3.13' not in spans
    assert 'python: 3.10 -- 3.13' in spans
    assert 'compute capability 7.5 or higher' in spans
    assert all('"' not in s and '“' not in s and '`' not in s for s in spans), spans


def test_跨主机同一句就能绑上(ledger, capsys):
    """上一条的闭环：片段提取修好后，这条 claim 能用源文件反查升档 B。"""
    led, cid = ledger
    led.set_status([cid], 'pending',
                   text='文档逐字写「vLLM does not support Windows natively.」，'
                        '前置条件为 "Python: 3.10 -- 3.13"')
    n = led.content_identity([cid], DOCS, REPO, body_of=_bodies(
        {DOCS: DOC_BODY, REPO: REPO_BODY}))
    capsys.readouterr()
    assert n == 1


def test_claim没有逐字片段不许绑(ledger, capsys):
    """全是转述就没有可核证据，宁可不升。"""
    led, cid = ledger
    led.set_status([cid], 'pending', text='vLLM 的 GPU 文档大概只支持 Linux 吧')
    n = led.content_identity([cid], DOCS, REPO, body_of=_bodies(
        {DOCS: DOC_BODY, REPO: REPO_BODY}))
    capsys.readouterr()
    assert n == 0


def test_锚点必须是这条claim自己的来源(ledger, capsys):
    """不许拿别的 claim 的判同记录给自己背书。"""
    led, cid = ledger
    led.add_claim('另一条说「别的句子」', topic='t')
    other = [c['id'] for c in led.claims() if c['id'] != cid][0]
    n = led.content_identity([other], DOCS, REPO, body_of=_bodies(
        {DOCS: DOC_BODY, REPO: REPO_BODY}))
    capsys.readouterr()
    assert n == 0
