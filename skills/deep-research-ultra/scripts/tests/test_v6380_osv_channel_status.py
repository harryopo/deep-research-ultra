"""v6.38.0 回归：CVE 取不到不能写成 0 条。

报告（2026-09-29 一轮实跑，D6 先误归因"OSV 通道坏了"，Lead 复核后改成"通道正常、我们的
实现读错了键"）。我当场三连实测把根因钉死：

- `curl POST api.osv.dev/v1/query {"package":{"ecosystem":"PyPI","name":"requests"}}`
  → 返回键是 **vulns**，16 条（GHSA-652x-xj99-gmcc 等）；而 `_scan_osv` 读的是
  `data.get('vulnerabilities')` → **恒空**。
- 生态名大小写敏感：`pypi` 直接回 `{"code":…,"message":"invalid ecosystem"}`，
  `npm` 回 `{}`（该生态里没有 requests 这个包）。代码把这两种都当成"0 条"。
- `_post_json` 把异常吞成 `None`，"通道坏了"与"确实没有 CVE"在回执里长得一模一样。

三者叠加的产物就是本包最忌的假成功形态：`cves: []` + `overall: low`，下游照抄成"无已知漏洞"。
判据据此补齐：通道状态与命中条数分开报，取到 0 条时必须用对照包自证通道是活的。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import repo_health as rh  # noqa: E402

VULN_OK = {'vulns': [{'id': 'GHSA-652x-xj99-gmcc', 'summary': 's', 'aliases': []}]}
CANARY_OK = {'vulns': [{'id': 'GHSA-x', 'summary': 's', 'aliases': []} for _ in range(3)]}
ZERO = {'vulns': []}


def _fake_post(responses):
    """按调用顺序回放 OSV 回执，并记下每次发出的请求体。"""
    calls = []

    def post(url, payload):
        calls.append(payload)
        return responses[min(len(calls) - 1, len(responses) - 1)]
    post.calls = calls
    return post


def test_osv_vulns_key_is_parsed(monkeypatch):
    """OSV 的返回键是 vulns；读成 vulnerabilities 就把 16 条读成 0 条。"""
    monkeypatch.setattr(rh, '_post_json', _fake_post([VULN_OK]))

    out = rh._scan_osv('PyPI:requests')

    assert out['status'] == 'ok', out
    assert len(out['vulns']) == 1, out


def test_osv_ecosystem_is_canonical(monkeypatch):
    """`pypi:requests` 要发成 PyPI——小写会被 OSV 判 invalid ecosystem。"""
    post = _fake_post([VULN_OK])
    monkeypatch.setattr(rh, '_post_json', post)

    rh._scan_osv('pypi:requests')

    sent = post.calls[0]['package']
    assert sent['ecosystem'] == 'PyPI', f"发出去的生态名不是规范形: {sent}"
    assert sent['name'] == 'requests', sent


def test_invalid_ecosystem_is_reported_as_unknown_channel(monkeypatch):
    """被 API 拒答（code/message）不等于 0 条。"""
    monkeypatch.setattr(rh, '_post_json',
                        _fake_post([{'code': 400, 'message': 'invalid ecosystem'}]))

    out = rh._scan_osv('badeco:foo')

    assert out['status'] == 'unknown', out
    assert 'invalid ecosystem' in out['note'], out


def test_channel_exception_is_unknown_not_zero(monkeypatch):
    """_post_json 吞异常返回 None 时，回执必须说"没取到"，不许留空列表装成查过了。"""
    monkeypatch.setattr(rh, '_post_json', _fake_post([None]))

    out = rh._scan_osv('PyPI:requests')

    assert out['status'] == 'unknown', out


def test_zero_result_is_only_trusted_after_canary(monkeypatch):
    """0 条要自证通道活着：对照包同批发得出 vulns，才许写 0。"""
    monkeypatch.setattr(rh, '_post_json', _fake_post([ZERO, CANARY_OK]))

    out = rh._scan_osv('PyPI:some-new-package')

    assert out['status'] == 'ok', out
    assert len(out['vulns']) == 0
    assert '对照' in out['note'], f"0 条没说明凭什么可信: {out}"


def test_zero_result_with_dead_canary_is_unknown(monkeypatch):
    """对照包也取不到 → 通道存疑，这批发回的 0 条一条都不许当结论。"""
    monkeypatch.setattr(rh, '_post_json', _fake_post([ZERO, ZERO]))

    out = rh._scan_osv('PyPI:some-new-package')

    assert out['status'] == 'unknown', out


def _health_with_osv(monkeypatch, responses):
    monkeypatch.setattr(rh, '_post_json', _fake_post(responses))
    h = rh.RepoHealth(owner='a', repo='b')
    h.verdict = 'ok'
    h.api_ok = True
    return h, rh._apply_osv(h, 'PyPI:requests')


def test_unknown_channel_lands_in_risks_and_not_low(monkeypatch):
    """OSV 没取到时，综合等级不许停在 low，风险清单里要点名。"""
    h, _ = _health_with_osv(monkeypatch, [None])

    assert h.overall() == 'unknown', f"CVE 没取到却判 {h.overall()}: {h.risks}"
    assert any(r['category'] == 'security' for r in h.risks), h.risks


def test_markdown_never_prints_zero_for_a_dead_channel(monkeypatch):
    """通道没取到时，不许印出"OSV，0 个"这一节标题——那是把没查过伪装成查过。

    （断言基准取标题行而不是"0 个"三个字：诚实措辞"CVE 未取到（不是 0 个）"里也含"0 个"，
    拿子串"0 个"当禁令会把自己那句真话判成违规。）
    """
    h, _ = _health_with_osv(monkeypatch, [None])

    md = rh.build_markdown(h)

    assert '不是 0' in md, md[-600:]
    assert '已知安全漏洞（OSV，0 个）' not in md, md[-600:]


def test_markdown_prints_count_when_channel_is_ok(monkeypatch):
    """正向对照：通道确认活着时，条数照实印。"""
    h, _ = _health_with_osv(monkeypatch, [VULN_OK])

    md = rh.build_markdown(h)

    assert '1 个' in md, md[-600:]
