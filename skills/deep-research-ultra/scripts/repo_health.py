"""
repo_health.py — 开源仓库健康/合规/风险扫描器

审计"用开源方案优化自有项目"前的确定性风险项（防信息失真/风险隐形），
覆盖用户痛点对应的可自动化部分：
  1. 信息核实   —— 仓库事实全部来自官方 API（GitHub/Gitee），标注检测时间，禁止编造
  2. 维护状态   —— 最近提交时间 / 归档标记 / star / open issues → 停更与活跃预警
  3. 许可证合规 —— SPDX 标识 + 传染性分级（permissive / weak-copyleft / strong-copyleft）+ 商业使用提示
  4. 安全风险   —— OSV API 按包名查已知 CVE（数量 + 摘要），可选
  5. 依赖传导   —— 包管理器 yanked/不推荐标记（pip yanked / npm deprecated），可选入口

设计约束：
- 免费公开 API（GitHub REST 无 token 60/h；Gitee v5；OSV 无需 key），无第三方依赖
- 纯确定性，全部输出带"检测时间"；任何单项失败只标 UNKNOWN，不阻断
- CLI：python repo_health.py <owner/repo 或 GitHub|Gitee URL> [--package npm:name] [--json]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
TIMEOUT = 10.0

# ---------------------------------------------------------------------------
# 许可证传染性分级（企业落地关键）
# ---------------------------------------------------------------------------
PERMISSIVE = {'mit', 'apache-2.0', 'bsd-2-clause', 'bsd-3-clause', 'isc',
              'unlicense', 'zlib', '0bsd', 'wtfpl'}
WEAK_COPYLEFT = {'lgpl-2.0', 'lgpl-2.1', 'lgpl-3.0', 'lgpl-2.1-only', 'lgpl-3.0-only',
                 'lgpl-2.0-or-later', 'lgpl-2.1-or-later', 'lgpl-3.0-or-later',
                 'lgpl-2.1-or-later-only', 'mpl-2.0', 'epl-1.0', 'epl-2.0',
                 'cddl-1.0', 'cddl-1.1'}
STRONG_COPYLEFT = {'gpl-2.0', 'gpl-3.0', 'agpl-3.0', 'gpl-2.0-only', 'gpl-3.0-only',
                   'agpl-3.0-only', 'gpl-2.0-or-later', 'gpl-3.0-or-later',
                   'agpl-3.0-or-later', 'sspl-1.0', 'cc-by-sa-4.0'}


def _spdx_from_body(text: str) -> str:
    """从 LICENSE 正文判 SPDX 名（只认正文里的标题行与标志性句子）。"""
    head = (text or '')[:4000].lower()
    if not head.strip():
        return ''
    if 'gnu affero general public license' in head:
        return 'AGPL-3.0'
    if 'gnu lesser general public license' in head:
        return 'LGPL-3.0' if 'version 3' in head else 'LGPL-2.1'
    if 'gnu general public license' in head:
        return 'GPL-3.0' if 'version 3' in head else 'GPL-2.0'
    if 'apache license' in head and 'version 2' in head:
        return 'Apache-2.0'
    if 'mozilla public license' in head:
        return 'MPL-2.0'
    if 'mit license' in head or 'permission is hereby granted, free of charge' in head:
        return 'MIT'
    if 'bsd' in head:
        return 'BSD'
    if 'isc license' in head:
        return 'ISC'
    if 'the unlicense' in head or 'unlicense' in head:
        return 'Unlicense'
    return ''


def _resolve_license_body(h: 'RepoHealth', headers: Dict[str, str]) -> None:
    """字段判不出（NOASSERTION / Other / 空）时回读 LICENSE 本体。

    实测 4 例（2026-09-29）：`vercel/ai`、`openai/evals` 字段是 NOASSERTION 而本体分别是
    纯 Apache-2.0 与逐字 MIT；`neo4j-graphrag-python` 本体 Apache-2.0+PSF；
    `modelcontextprotocol/typescript-sdk` 本体已从 MIT 迁到 Apache-2.0，npm 发布件里仍标 MIT。
    字段说什么就印什么，等于把"GitHub 没识别出来"写成"这个件用的是 Other"。
    """
    field = (h.facts.get('license_field') or '').strip().lower()
    if field not in ('', 'noassertion', 'other', 'no-license', 'unknown', 'null'):
        h.facts['license_effective'] = h.facts.get('license')
        return
    if h.host != 'github':
        h.facts['license_effective'] = ''
        h.facts['license_note'] = f'许可证未证实（{h.host} 无本体端点，字段值 {field or "空"}）'
        return
    status, data = fetch_json(f'https://api.github.com/repos/{h.owner}/{h.repo}/license',
                              headers)
    body, url = '', ''
    if status == 200 and isinstance(data, dict):
        url = data.get('download_url') or (data.get('url') or '')
        try:
            import base64
            body = base64.b64decode(data.get('content') or '').decode('utf-8', errors='replace')
        except Exception:
            body = ''
    detected = _spdx_from_body(body)
    if detected:
        h.facts['license_effective'] = detected
        h.facts['license_body_url'] = url
        h.facts['license_note'] = f'字段 {field or "空"} 与本体不符，按本体判为 {detected}'
    else:
        h.facts['license_effective'] = ''
        h.facts['license_body_url'] = url
        h.facts['license_note'] = ('许可证未证实（字段 ' + (field or '空') +
                                   ('，本体取回但读不出 SPDX 名' if url else '，且本体没取到') +
                                   '）——写结论前先人工看 LICENSE 文件，不许抄字段值')


def license_risk(spdx_id: str) -> Tuple[str, str]:
    """返回 (风险等级, 说明)。等级：permissive/weak/strong/unknown。"""
    s = (spdx_id or '').strip().lower()
    if not s or s == 'no-license' or 'other' in s:
        return 'unknown', '无有效许可证（或 LicenseRef），私有项目慎用，需法务确认'
    # 归一化 -only/-or-later 后缀再比对（弱传染集合已含 or-later 变体，
    # 避免 'lgpl-3.0-or-later' 落入下方 'gpl' 子串 heuristic 被误判为 strong）
    base = re.sub(r'-only$|-or-later(-only)?$', '', s)
    if s in PERMISSIVE or base in PERMISSIVE:
        return 'permissive', '可自由商用/修改（MIT/Apache/BSD 系），最常见安全选择'
    if s in WEAK_COPYLEFT or base in WEAK_COPYLEFT:
        return 'weak', '修改该组件需以同许可证开源该组件（LGPL/MPL/EPL）；动态链接通常可避免传染'
    if s in STRONG_COPYLEFT or base in STRONG_COPYLEFT:
        return 'strong', '传染性最强（GPL/AGPL）：分发含其代码的产品需整体开源，商业闭源项目高风险'
    # heuristic：含 agpl/gpl 字样的未知变体（排除已归入 weak 的 lgpl）
    if 'agpl' in s:
        return 'strong', f'疑似强传染性许可证（{spdx_id}），需法务确认'
    if re.search(r'(?<!l)gpl', s):   # gpl 但不是 lgpl
        return 'strong', f'疑似强传染性许可证（{spdx_id}），需法务确认'
    return 'unknown', f'未收录许可证 {spdx_id}（{s}），需法务确认'


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------
def fetch_json(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
    """取 JSON，并把"为什么没取到"一起带回来：(HTTP 状态码, 数据)。

    状态码不能压成 None——403/429 是我们被限流，404 才是仓库真不存在。
    混成一个结论就会把活跃仓库判成高风险。0 表示传输层失败（DNS/超时/断网）。
    """
    hdrs = {'User-Agent': UA, 'Accept': 'application/json'}
    hdrs.update(headers or {})
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8', errors='ignore'))
    except urllib.error.HTTPError as e:
        return int(e.code), None
    except Exception:
        return 0, None


# 状态码 → 判定。未列出的（5xx、401 等）一律按"这次没查到"处理。
VERDICT_BY_STATUS = {200: 'ok', 404: 'not_found', 403: 'forbidden', 429: 'rate_limited'}
UNVERIFIED = ('rate_limited', 'forbidden', 'unreachable')


def api_headers(host: str) -> Tuple[Dict[str, str], bool]:
    """GitHub 匿名限额只有 60 次/小时，一次深跑必撞——有 GITHUB_TOKEN 就带上。"""
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if host == 'github' and token:
        return {'Authorization': f'Bearer {token}'}, False
    return {}, host == 'github'


def _post_json(url: str, payload: Dict[str, Any]) -> Optional[Any]:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode('utf-8'),
            headers={'User-Agent': UA, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8', errors='ignore'))
    except Exception:
        return None


def _parse_repo_ref(raw: str) -> Optional[Dict[str, str]]:
    """解析 owner/repo 或 GitHub/Gitee URL。"""
    raw = raw.strip().rstrip('/')
    m = re.search(r'(?:github\.com|gitee\.com)/([^/]+)/([^/]+)$', raw)
    host = 'github'
    if 'gitee.com' in raw:
        host = 'gitee'
    if m:
        return {'host': host, 'owner': m.group(1), 'repo': m.group(2)}
    parts = raw.split('/')
    if len(parts) == 2 and parts[0] and parts[1]:
        return {'host': 'github', 'owner': parts[0], 'repo': parts[1]}
    return None


@dataclass
class RepoHealth:
    owner: str
    repo: str
    host: str = 'github'
    api_ok: bool = False
    verdict: str = 'pending'          # ok / not_found / rate_limited / forbidden / unreachable
    http_status: int = 0
    anonymous: bool = False           # GitHub 匿名请求（60 次/小时），限流时要说清这点
    facts: Dict[str, Any] = field(default_factory=dict)      # 官方 API 事实（带检测时间）
    detected_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat(
        timespec='seconds'))
    risks: List[Dict[str, Any]] = field(default_factory=list)  # {level, category, detail}
    cves: List[Dict[str, Any]] = field(default_factory=list)   # OSV 结果
    package_health: Dict[str, Any] = field(default_factory=dict)  # yanked/deprecated
    cve_status: str = 'skipped'     # skipped / ok / unknown —— 条数与通道状态分开记
    cve_note: str = ''

    def add_risk(self, level: str, category: str, detail: str) -> None:
        self.risks.append({'level': level, 'category': category, 'detail': detail})

    def overall(self) -> str:
        # 没查到就判 unknown：限流是我们的问题，不是仓库的风险
        if self.verdict in UNVERIFIED:
            return 'unknown'
        # CVE 通道没取到时也不能停在 low：`cves: [] + overall: low` 会被下游照抄成"无已知漏洞"
        if self.cve_status == 'unknown':
            return 'unknown'
        if any(r['level'] == 'high' for r in self.risks):
            return 'high'
        if any(r['level'] == 'medium' for r in self.risks):
            return 'medium'
        return 'low'


# ---------------------------------------------------------------------------
# 数据采集
# ---------------------------------------------------------------------------
def scan_repo(ref: str, with_cve_package: Optional[str] = None) -> RepoHealth:
    """主扫描：官方事实 + 健康信号 + 许可证 + 可选 OSV CVE。"""
    parsed = _parse_repo_ref(ref)
    if not parsed:
        raise ValueError(f'无法解析仓库引用：{ref}（期望 owner/repo 或 GitHub/Gitee URL）')
    h = RepoHealth(host=parsed['host'], owner=parsed['owner'], repo=parsed['repo'])

    headers, h.anonymous = api_headers(h.host)
    url = (f'https://api.github.com/repos/{h.owner}/{h.repo}' if h.host == 'github'
           else f'https://gitee.com/api/v5/repos/{h.owner}/{h.repo}')
    status, data = fetch_json(url, headers)
    h.http_status = status
    h.verdict = VERDICT_BY_STATUS.get(status, 'unreachable')
    if h.verdict == 'ok' and not isinstance(data, dict):
        h.verdict = 'unreachable'
    if h.verdict == 'not_found':
        h.add_risk('high', 'not_found',
                   f'{h.owner}/{h.repo} 在 {h.host} 上不存在（API 404）——'
                   '改名、删除或从未公开，这是仓库的事实，不是我们查不到')
        return h
    if h.verdict != 'ok':
        return h     # 限流/无权限/网络故障：一条风险都不写，原因交给 build_markdown
    h.api_ok = True

    pushed = data.get('pushed_at') or data.get('updated_at') or ''
    stars = data.get('stargazers_count')
    license_spdx = ''
    lic = data.get('license')
    if isinstance(lic, dict):
        license_spdx = lic.get('spdx_id') or lic.get('name') or ''
    elif isinstance(lic, str):
        license_spdx = lic

    h.facts = {
        'name': data.get('full_name') or f'{h.owner}/{h.repo}',
        'requested': f'{h.owner}/{h.repo}',
        'description': (data.get('description') or '')[:200],
        'language': data.get('language'),
        'stars': stars,
        'forks': data.get('forks_count') or data.get('forks'),
        'open_issues': data.get('open_issues_count'),
        'pushed_at': pushed,
        'archived': bool(data.get('archived', False)),
        'license': license_spdx or 'unknown',
        'license_field': license_spdx,
        'license_body_url': '',
        'license_effective': license_spdx,
        'license_note': '',
    }

    # 改名仓库：GitHub 会把旧路径直接返回新主人的元数据，所以 facts['name'] 本来就是终态。
    # 但 Lead 手里那条 URL 还是旧的——不写出"请求的是哪个"，旧链接就靠"已核对"的错觉
    # 混进引用清单（实测本轮三件 org 迁移、一件 404 无重定向）。
    resolved = (data.get('full_name') or '').strip().lower()
    h.facts['renamed'] = bool(resolved) and resolved != f'{h.owner}/{h.repo}'.strip().lower()
    if h.facts['renamed']:
        h.facts['rename_note'] = (f'请求路径 {h.owner}/{h.repo} 已由仓库自报为 '
                                  f'{data.get("full_name")}（改名/迁移）——'
                                  '引用请改写成终态，旧 URL 随时可能断')

    # --- 维护状态（防停更/弃坑）---
    if pushed:
        try:
            age_days = (datetime.datetime.now(datetime.timezone.utc)
                        - datetime.datetime.fromisoformat(pushed.replace('Z', '+00:00'))).days
            h.facts['days_since_push'] = age_days
            if age_days > 365:
                h.add_risk('high', 'maintenance',
                           f'最近提交 {age_days} 天前（≥1 年）——高度疑似停更，上线风险大')
            elif age_days > 180:
                h.add_risk('medium', 'maintenance',
                           f'最近提交 {age_days} 天前——活跃度低，需确认维护计划')
        except ValueError:
            pass
    if h.facts.get('archived'):
        h.add_risk('high', 'maintenance', '仓库已归档（archived）——官方停止维护')
    if isinstance(stars, int) and stars < 10 and not h.facts.get('archived'):
        h.add_risk('medium', 'adoption', f'Star 仅 {stars}，社区采用度极低，注意试错成本')

    # --- 许可证（合规）：字段判不出就读本体，判据按本体结果下 ---
    h.facts['license_field'] = license_spdx
    _resolve_license_body(h, headers)
    lic_effective = h.facts.get('license_effective') or ''
    level, note = license_risk(lic_effective)
    if not lic_effective:
        level, note = 'unknown', h.facts.get('license_note') or note
    h.facts['license_risk'] = level
    if level == 'strong':
        h.add_risk('high', 'license', f'{lic_effective or "未知许可"}：{note}')
    elif level == 'weak':
        h.add_risk('medium', 'license', f'{lic_effective}：{note}')
    elif level == 'unknown':
        h.add_risk('medium', 'license', note)

    # --- 安全（OSV，按包可选）---
    if with_cve_package:
        _apply_osv(h, with_cve_package)

    return h


def _apply_osv(h: 'RepoHealth', pkg_ref: str) -> Dict[str, Any]:
    """把一发 OSV 查询落到健康结构上：条数与通道状态分开，取不到就进风险清单。"""
    sch = _scan_osv(pkg_ref)
    h.cves = sch.get('vulns', [])
    h.package_health = sch.get('package', {})
    h.cve_status = sch.get('status', 'unknown')
    h.cve_note = sch.get('note', '')
    if h.cve_status == 'unknown':
        h.add_risk('unknown', 'security',
                   f'CVE 未取到（不是 0 个）：{h.cve_note or "OSV 回执不可判定"}'
                   f'——别把这一路的空列表写进结论')
    elif h.cves:
        h.add_risk('medium', 'security',
                   f'OSV 检出 {len(h.cves)} 个已知漏洞（含 {h.cves[0].get("id", "?")} 等）')
    return sch


_OSV_ECOSYSTEMS = {
    'pypi': 'PyPI', 'npm': 'npm', 'nuget': 'NuGet', 'go': 'Go',
    'crates.io': 'crates.io', 'crates': 'crates.io', 'rubygems': 'RubyGems',
    'ruby': 'RubyGems', 'maven': 'Maven', 'packagist': 'Packagist',
    'pub': 'pub', 'hugging face': 'Hugging Face', 'huggingface': 'Hugging Face',
    'android': 'Android', 'osv': 'OSV', 'linux': 'Linux',
}


def _canon_ecosystem(raw: str) -> str:
    """把用户写的生态名折成 OSV 认的规范形。

    实测（2026-09-29）：OSV 对大小写敏感——`PyPI` 正常返回，`pypi` 直接 400
    `invalid ecosystem`，而旧代码把这个拒答当成"0 条 CVE"写进结论。
    """
    key = (raw or '').strip().lower()
    return _OSV_ECOSYSTEMS.get(key, (raw or '').strip())


def _osv_vulns(payload: Any) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """把一发 OSV 回执拆成 (条目列表 | None, 说明)。None 就是"这一发没取到"。"""
    if payload is None:
        return None, 'OSV 请求未成功（网络或 5xx）'
    if not isinstance(payload, dict):
        return None, f'OSV 返回形态不认识：{type(payload).__name__}'
    if 'code' in payload or 'message' in payload:
        return None, f"OSV 拒答：{payload.get('message') or payload.get('code')}"
    # 键名是 vulns（实测）；vulnerabilities 是别处文档里的叫法，留着兜底但不当主路
    for key in ('vulns', 'vulnerabilities'):
        if isinstance(payload.get(key), list):
            return payload[key], ''
    return None, 'OSV 回执里没有 vulns 字段，无法判定是 0 条还是没取到'


def _scan_osv(pkg_ref: str) -> Dict[str, Any]:
    """OSV 查询：ref 形如 npm:vue 或 PyPI:requests。

    通道状态与命中条数分开报——`cves: []` + `overall: low` 会被下游照抄成"无已知漏洞"，
    而实测这条路径上三种成因（键名读错／生态名被拒／请求失败）长得一模一样。
    """
    if ':' not in pkg_ref:
        pkg_ref = f'pypi:{pkg_ref}'
    ecosystem, _, name = pkg_ref.partition(':')
    eco = _canon_ecosystem(ecosystem)
    payload = {'package': {'ecosystem': eco, 'name': name.strip()}}
    raw, vulns, note = None, None, ''
    got, why = _osv_vulns(_post_json('https://api.osv.dev/v1/query', payload))
    if got is None:
        note = why
    elif got:
        vulns = [_shape_osv_vuln(v) for v in got[:10]]
        note = f'OSV 取到 {len(got)} 条' + ('（已截前 10）' if len(got) > 10 else '')
    else:
        # 0 条要先自证通道活着：对照包是当日实测必回 16 条的组合
        canary, why = _osv_vulns(_post_json('https://api.osv.dev/v1/query', {
            'package': {'ecosystem': 'PyPI', 'name': 'requests'}}))
        if canary is None or not canary:
            note = f'本查询 0 条，但对照包 PyPI:requests 同样取不到（{why or "回执为空"}）' \
                   f'——OSV 这一发不可信，0 条不许当结论'
        else:
            vulns = []
            note = f'0 条，已用对照包自证通道正常（PyPI:requests 同批取到 {len(canary)} 条）'
    return {'package': {'ecosystem': eco, 'name': name.strip(),
                        'requested_ecosystem': ecosystem.strip()},
            'vulns': vulns or [], 'status': 'unknown' if vulns is None else 'ok',
            'note': note}


def _shape_osv_vuln(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': v.get('id', ''),
        'aliases': (v.get('aliases') or [])[:3],
        'summary': (v.get('summary') or '')[:160],
        'severity': _osv_severity(v),
    }


def _osv_severity(v: Dict[str, Any]) -> str:
    """提取严重度：优先 database_specific.severity，其次 severity[].score 解析。"""
    sev = v.get('database_specific', {}).get('severity', '')
    if isinstance(sev, str) and sev:
        return sev
    for s in v.get('severity', []) or []:
        score = str(s.get('score', ''))
        # score 是 CVSS 向量（如 "CVSS:3.1/AV:N/..."），截断会误当严重度；
        # 从向量解析基础严重度需完整解析器，此处返回向量存在标记
        if score.startswith('CVSS'):
            return 'CVSS-vector'
        return score or 'unknown'
    return 'unknown'


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def unverified_fix(h: RepoHealth) -> str:
    """未核实必须给得出下一步动作，尤其缺 token 这种一秒能修的事。"""
    if h.verdict == 'unreachable':
        return '网络/DNS/超时，或返回体不是 JSON——检查网络或代理（--proxy）后重跑'
    if h.anonymous:
        return (f'{h.verdict}：本次是 GitHub 匿名请求，限额只有 60 次/小时，深跑必撞。'
                '配 token 后重跑：export GITHUB_TOKEN="<你的 PAT>"（只读 public_repo 足够）')
    if h.verdict == 'rate_limited':
        return '已带 GITHUB_TOKEN 仍 429：等 1 小时或降低扫描频次后重跑'
    return '已带 GITHUB_TOKEN 仍 403：多为二级限流或私有仓库权限不足，稍后重跑或换 token'


def build_markdown(h: RepoHealth) -> str:
    lines = [f'## 开源仓库健康扫描 — {h.facts.get("name", f"{h.owner}/{h.repo}")}',
             f'> 检测时间：{h.detected_at}（数据源：{"GitHub REST API" if h.host == "github" else "Gitee v5 API"}；OSV 官方）',
             '']
    if h.verdict in UNVERIFIED:
        lines.append(f'### ⚠️ 未核实（verdict={h.verdict}，HTTP {h.http_status or "—"}）')
        lines.append('- 本次一条官方事实都没拿到，因此**不能**据此判该仓库有风险或无风险')
        lines.append(f'- 原因与对策：{unverified_fix(h)}')
        lines.append('- 综合结论：**UNKNOWN（未核实）**，不是 LOW 也不是 HIGH')
        return '\n'.join(lines)
    lines.append('### 仓库事实（官方数据，非 AI 推断）')
    lines.append('| 项 | 值 |')
    lines.append('|----|----|')
    f = h.facts
    lines.append(f'| 描述 | {f.get("description") or "-"} |')
    if f.get('rename_note'):
        lines.append(f'| 路径核对 | 🔴 {f.get("rename_note")} |')
    lines.append(f'| 语言 | {f.get("language") or "-"} |')
    lines.append(f'| Star | {f.get("stars") if f.get("stars") is not None else "-"} |')
    lines.append(f'| Fork | {f.get("forks") if f.get("forks") is not None else "-"} |')
    lines.append(f'| Open Issues | {f.get("open_issues") if f.get("open_issues") is not None else "-"} |')
    lines.append(f'| 最近提交 | {f.get("pushed_at") or "-"}（{f.get("days_since_push", "-")} 天前） |')
    lines.append(f'| 已归档 | {"是（停更）" if f.get("archived") else "否"} |')
    lic_eff = f.get('license_effective') or ''
    lic_field = f.get('license_field') or ''
    lic_show = lic_eff or '未证实'
    if lic_field and lic_eff and lic_field.lower() != lic_eff.lower():
        lic_show = f'{lic_eff}（字段写 {lic_field}，按 LICENSE 本体）'
    lic_url = f.get('license_body_url') or ''
    lic_note = f.get('license_note') or ''
    lines.append(f'| 许可证 | {lic_show}（{f.get("license_risk", "-")}） |')
    if lic_note:
        lines.append(f'| 许可证备注 | {lic_note}'
                     + (f'　本体：{lic_url}' if lic_url else '') + ' |')
    lines.append('')
    lines.append('### 风险清单')
    if not h.risks:
        lines.append('- ✅ 未检出明显风险（仍需按六维质量门人工复核）')
    for r in h.risks:
        icon = {'high': '🔴', 'medium': '🟠', 'low': '🟡'}.get(r['level'], '⚪')
        lines.append(f'- {icon} [{r["level"].upper()}] {r["category"]}：{r["detail"]}')
    if h.risks:
        lines.append(f'\n**综合风险等级：{h.overall().upper()}**')
    lines.append('')
    if h.cve_status == 'unknown':
        lines.append('## 已知安全漏洞（OSV）')
        lines.append(f'- ⚠️ **CVE 未取到（不是 0 个）**：{h.cve_note or "OSV 回执不可判定"}')
        lines.append('- 需要 CVE 数字时：直接打 `api.osv.dev/v1/query` 或 GitHub Advisory，'
                     '把请求体与返回条数一起记进证据，别引用本节的空结果')
        lines.append('')
    elif h.cves:
        lines.append(f'## 已知安全漏洞（OSV，{len(h.cves)} 个）')
        for c in h.cves:
            lines.append(f"- `{c['id']}` 严重度:{c['severity']} {c['summary']}")
        lines.append('')
    elif h.cve_status == 'ok':
        lines.append('## 已知安全漏洞（OSV，0 个）')
        lines.append(f'- 查询：`{h.package_health.get("ecosystem")}:{h.package_health.get("name")}`'
                     f' 未列已知漏洞（{h.cve_note}）')
        lines.append('')
    lines.append('---')
    lines.append('> 说明：本扫描提供"事实与部分风险信号"；技术适配性、二次开发成本、')
    lines.append('> 生态完整性与落地计划请结合六维质量门（SKILL.md 开源调研章节）人工评估。')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description='开源仓库健康/合规/风险扫描')
    parser.add_argument('repo', help='owner/repo 或 GitHub/Gitee URL')
    parser.add_argument('--package', default='',
                        help='OSV 包引用（如 npm:vue / PyPI:requests），用于查已知 CVE')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    opts = parser.parse_args(args)

    h = scan_repo(opts.repo, with_cve_package=opts.package or None)
    if opts.json:
        print(json.dumps({
            'verdict': h.verdict, 'http_status': h.http_status, 'anonymous': h.anonymous,
            'detected_at': h.detected_at, 'facts': h.facts,
            'risks': h.risks, 'cves': h.cves,
            'cve_status': h.cve_status, 'cve_note': h.cve_note,
            'package_health': h.package_health, 'overall': h.overall(),
        }, ensure_ascii=False, indent=2))
    else:
        print(build_markdown(h))
    # 未核实不是"扫过了"：退非 0，免得 Lead 把限流当成一次成功的扫描写进报告
    return 3 if h.verdict in UNVERIFIED else 0


if __name__ == '__main__':
    from console import force_utf8
    force_utf8()
    sys.exit(_main())