"""MCP 工具返回的两种真实形态，此前都被读成「可调通但 0 结果」。

实测起因（2026-09-24 端到端实跑后排查 arxiv / paper-search 两个 MCP 源）：

1. paper-search 的 `search_papers` 返回的是**散文抬头 + JSON 数组**：
   `"Found 10 papers.\n\n[ {...}, {...} ]"`。旧 `_parse_mcp_result` 只会整段
   `json.loads`，失败就退化成 `{"text": 整段}`，再被引擎的 title/url 过滤全丢光——
   一个当天正常出数据的好源，被判成"查询词无命中"。
2. arxiv 的 `search_papers` 上游被 arXiv 限流时返回
   `{"content":[{"text":"{\"status\":\"error\",\"message\":\"arXiv API HTTP error (HTTP 406)\"}"}],
    "isError":true}`。旧实现不看 `isError`，把这条错误文本也塞成一条无 title/url 的条目，
   同样落到"0 结果"。**端点报错被当成"这个主题没资料"**——正是自检最不该犯的错。

所以修复方向是：能解析的解析出来，解析不了的错误要作为"未取到数据 + 原因"上报。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.mcp_client import McpClient  # noqa: E402
from engines.mcp_engines import _parse_mcp_result  # noqa: E402

PAPERS = [{'paper_id': '10.1002/x', 'title': 'Graph Neural Network',
           'url': 'https://doi.org/10.1002/x'},
          {'paper_id': '10.2172/y', 'title': 'NuGraph2',
           'url': 'https://doi.org/10.2172/y'}]

STUB = r'''
import json, sys

mode = sys.argv[1] if len(sys.argv) > 1 else 'good'
sys.stdout.reconfigure(encoding='utf-8')
ready = False
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue
    method, rid = req.get('method'), req.get('id')
    if method == 'initialize':
        ready = True
        out = {'jsonrpc': '2.0', 'id': rid,
               'result': {'protocolVersion': '2024-11-05', 'capabilities': {},
                          'serverInfo': {'name': 'stub', 'version': '1'}}}
    elif method == 'tools/list':
        out = {'jsonrpc': '2.0', 'id': rid,
               'result': {'tools': [{'name': 'search_papers', 'description': 'd',
                                     'inputSchema': {}}]}}
    elif method == 'tools/call':
        if not ready:
            out = {'jsonrpc': '2.0', 'id': rid,
                   'error': {'code': -32002, 'message': 'Server not initialized'}}
        elif mode == 'prose':
            text = 'Found 10 papers.\n\n' + json.dumps(PAPERS_PLACEHOLDER)
            out = {'jsonrpc': '2.0', 'id': rid,
                   'result': {'content': [{'type': 'text', 'text': text}],
                              'isError': False}}
        elif mode == 'toolerr':
            text = json.dumps({'status': 'error',
                               'message': 'arXiv API HTTP error (HTTP 406)'})
            out = {'jsonrpc': '2.0', 'id': rid,
                   'result': {'content': [{'type': 'text', 'text': text}],
                              'isError': True}}
        elif mode == 'rpcerr':
            out = {'jsonrpc': '2.0', 'id': rid,
                   'error': {'code': -32603, 'message': 'internal error: boom'}}
        else:
            out = {'jsonrpc': '2.0', 'id': rid,
                   'result': {'content': [{'type': 'text',
                                           'text': json.dumps(PAPERS_PLACEHOLDER)}],
                              'isError': False}}
    else:
        continue
    sys.stdout.write(json.dumps(out) + '\n')
    sys.stdout.flush()
'''.replace('PAPERS_PLACEHOLDER', json.dumps(PAPERS))


@pytest.fixture()
def stub_path(tmp_path):
    p = tmp_path / 'mcp_stub.py'
    p.write_text(STUB, encoding='utf-8')
    return p


def make_client(stub_path, mode):
    return McpClient('stub', config={
        'command': sys.executable, 'args': [str(stub_path), mode]})


# ---------------------------------------------------------- ① 散文抬头的 JSON 数组
def test_parse_mcp_result_handles_prose_prefixed_json_array():
    """'Found 10 papers.' + JSON 数组必须解析出条目，不能整段当纯文本丢掉。"""
    text = 'Found 10 papers.\n\n' + json.dumps(PAPERS)
    items = _parse_mcp_result({'content': [{'type': 'text', 'text': text}]})
    assert [i.get('title') for i in items] == ['Graph Neural Network', 'NuGraph2'], \
        f'散文抬头的 JSON 没被解析出来：{items}'


def test_parse_mcp_result_prose_prefixed_json_object_with_results():
    text = 'Query done.\n' + json.dumps({'count': 2, 'results': PAPERS})
    items = _parse_mcp_result({'content': [{'type': 'text', 'text': text}]})
    assert [i.get('url') for i in items] == [p['url'] for p in PAPERS]


def test_paper_search_engine_returns_results_from_prose_stub(stub_path):
    """真引擎 + 真会话：paper-search 这种形态必须出得来 SearchResult。"""
    from engines.mcp_engines import PaperSearchMcpEngine
    eng = PaperSearchMcpEngine()
    eng._client = make_client(stub_path, 'prose')
    results = eng.search('graph neural network', max_results=5)
    assert results and len(results) == 2, f'出得来数据却被判成空：{results}'
    assert results[0].url.startswith('https://doi.org/')


# ---------------------------------------------------------- ② 工具报错≠零命中
def test_tool_reported_error_becomes_failure_not_empty_list(stub_path):
    client = make_client(stub_path, 'toolerr')
    assert client.call_tool('search_papers', {'query': 'x'}) is None, \
        'isError=true 的工具响应不能再被当成"调通但没结果"'
    assert '406' in client.last_error, \
        f'失败原因要带上 server 给的消息：{client.last_error!r}'


def test_rpc_error_becomes_failure_with_reason(stub_path):
    client = make_client(stub_path, 'rpcerr')
    assert client.call_tool('search_papers', {'query': 'x'}) is None
    assert 'boom' in client.last_error, f'JSON-RPC 错误没留原因：{client.last_error!r}'


def test_probe_reports_arxiv_style_error_as_failed_not_zero_hits(stub_path):
    """自检结论决定 Lead 怎么行动：'0 结果'会让人换查询词，'未取到数据'才会去修通道。"""
    import probe
    from engines.mcp_engines import ArxivMcpEngine
    eng = ArxivMcpEngine()
    eng._client = make_client(stub_path, 'toolerr')

    rep = probe.probe_engine(eng, max_results=3)
    assert rep['status'] == probe.STATUS_FAILED, \
        f"端点报错被判成 {rep['status']}：{rep['note']}"
    assert '406' in rep['note'], f"探针报告没带上游原因：{rep['note']}"


def test_plain_json_still_parses(stub_path):
    """回归护栏：本来就正常的纯 JSON 响应不许被新解析路径弄坏。"""
    from engines.mcp_engines import PaperSearchMcpEngine
    eng = PaperSearchMcpEngine()
    eng._client = make_client(stub_path, 'good')
    assert len(eng.search('graph neural network', max_results=5)) == 2
