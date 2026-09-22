"""第 5 条（arXiv 全程 406）的根因是传输层没有 TLS 指纹，当时只修了公共通道那一条路。

本文件横扫同类：凡是自己在发 HTTP 的模块，都得走那条带指纹、会把状态码留下来的公共通道。
判据取实跑里那句无归因的话——「引擎返回 None（依赖/服务未就绪）」，用户看到它不知道该做什么。
"""
import ast
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines import fallback  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]

# 允许自己发裸请求的两处，各自都有理由，不是漏网：
# - engines/fallback.py：它就是那条公共通道本身；
# - repo_health.py：fetch_json 必须把 403/429/404 分开（X-D11 的修复），公共通道非 200
#   只回 None，改过去会把状态码契约打回"一律算无法核实"，反而误杀活跃仓库。
ALLOWED_BARE = {'engines/fallback.py', 'repo_health.py'}


def _bare_http_calls():
    """扫出所有 urlopen / opener.open / build_opener 调用点，返回 '相对路径:行号'。"""
    hits = []
    for path in sorted(SCRIPTS.rglob('*.py')):
        rel = path.relative_to(SCRIPTS).as_posix()
        if rel.startswith('tests/'):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in ('urlopen', 'open', 'build_opener'):
                continue
            callee = ast.unparse(node.func.value)
            if callee.endswith('urllib.request') or callee == 'opener':
                hits.append(f'{rel}:{node.lineno}')
    return hits


def test_no_module_bypasses_the_shared_transport():
    bad = [h for h in _bare_http_calls() if h.split(':')[0] not in ALLOWED_BARE]
    assert not bad, (
        '这些调用点在发不带 TLS 指纹的请求，失败时也不留状态码：'
        + ', '.join(bad))


def test_the_bare_http_scanner_sees_the_legit_uses():
    """正向对照：扫描器一旦失效，上一条就会永远绿灯，等于没有门。"""
    files = {h.split(':')[0] for h in _bare_http_calls()}
    assert ALLOWED_BARE <= files, f'扫描器没抓到本该存在的公共通道调用点：{sorted(files)}'


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/denied':
            self.send_response(403)
            self.end_headers()
            return
        body = json.dumps([{'full_name': 'openml-org/mlflow'}]).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def base_url():
    srv = HTTPServer(('127.0.0.1', 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_port}'
    srv.shutdown()
    srv.server_close()


def test_platform_json_failure_keeps_the_status_code(base_url):
    """gitee/modelscope 是境内平台，正是被指纹拦的那一类；吞成 None 就没法归因。"""
    from engines import platform_engines

    assert platform_engines._http_get_json(f'{base_url}/denied') is None
    assert '403' in fallback.LAST_HTTP_ERROR, (
        f"失败原因没留下，Lead 只能看到『依赖/服务未就绪』：{fallback.LAST_HTTP_ERROR!r}")


def test_platform_json_success_still_parses(base_url):
    """给负向断言配正向对照：换了通道不能把本来拿得到的数据换没了。"""
    from engines import platform_engines

    data = platform_engines._http_get_json(f'{base_url}/ok')
    assert data == [{'full_name': 'openml-org/mlflow'}]


def test_search_http_get_failure_keeps_the_status_code(base_url):
    import search

    with pytest.raises(Exception):
        search._http_get(f'{base_url}/denied', max_retries=1)
    assert '403' in fallback.LAST_HTTP_ERROR, (
        f'搜索层报错要带上状态码，否则与"服务没起来"无法区分：{fallback.LAST_HTTP_ERROR!r}')


def test_search_http_get_success_returns_bytes(base_url):
    import search

    raw = search._http_get(f'{base_url}/ok', max_retries=1)
    assert json.loads(raw.decode('utf-8')) == [{'full_name': 'openml-org/mlflow'}]


def test_search_call_sites_pass_only_supported_kwargs():
    """机械改写的漏网之处：原来 `Request(url, method='HEAD')` 的参数会被原样搬进新助手。

    允许的入参从函数自己的签名取，签名变了这条会跟着变，不写死名单。
    """
    import inspect

    import search

    allowed = {'_reachable': set(inspect.signature(search._reachable).parameters),
               '_http_get': set(inspect.signature(search._http_get).parameters)}
    tree = ast.parse((SCRIPTS / 'search.py').read_text(encoding='utf-8'))
    bad = [f'{node.func.id}(kwarg={kw.arg}) 第 {node.lineno} 行'
           for node in ast.walk(tree)
           if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id in allowed
           for kw in node.keywords if kw.arg not in allowed[node.func.id]]
    assert not bad, 'search.py 传了公共通道不支持的参数：' + '；'.join(bad)
