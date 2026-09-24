"""
ledger.py — 证据账本（Research Ledger）  [v6.0 新增]

所有搜索证据（claim）与来源（source）的统一持久化层，支持：
- 多子 Agent 并行追加（JSONL 追加式，O_APPEND，Windows/Linux 均安全）
- claim → source 多源关联，可审计、可溯源
- merge：合并子 Agent 产物（递归收 *.json / *.jsonl；两种形状都认——逐条
  {"type": "claim"|"source", ...} 与容器 {"claims": [...], "sources": [...]}）
- status：按 topic 统计覆盖率、独立来源数、冲突数（证据充分性判据来源）
- 导出 JSON / Markdown（供报告引用编号锚定：primary_index = [topic_id-source_seq]）

设计约束：
- 只做文件 IO、去重与统计，不做语义判断（判断交给子 Agent / 主 Agent）
- 所有写操作追加式，读操作按行解析并容错（并发写时可能出现的半行直接跳过）
- 与 tier.py 低耦合：add-source 若不传 tier，则用 domain_tier 自动判定
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from tier import domain_tier, tier_label
except ImportError:  # 独立运行/测试无 tier 时降级
    domain_tier = None  # type: ignore
    tier_label = lambda t: str(t)  # type: ignore

try:
    from similarity import effective_independent_count  # v6.4 转载指纹去重
except ImportError:
    effective_independent_count = lambda srcs, **kw: len(srcs)  # type: ignore

VALID_STATUS = {'pending', 'searching', 'verified', 'conflict', 'supplementing', 'completed'}


def _registered_domain(url: str) -> str:
    """取注册域（近似）：github.com 与 api.github.com 同属 github.com。

    档 B 判据依赖它——同一制品的不同检索通道（仓库页 / REST API）算一个域。
    GitHub 的同一份内容有三个合法入口（blob 页 / REST API / raw 字节流），
    它们的注册域并不相同（github.com vs githubusercontent.com），按纯注册域
    判同会把「拿 raw 链接复核 blob 链接」这种真实反查误拒，故整个家族归一。
    """
    m = re.match(r'https?://([^/]+)', str(url or ''))
    if not m:
        return ''
    host = m.group(1).lower().split(':')[0]
    if host.endswith('githubusercontent.com') or host.endswith('github.com'):
        return 'github.com'
    parts = host.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 else parts[0]


_ARXIV_ID_RE = re.compile(r'(\d{4}\.\d{4,5})')

# 仓库根页渲染的就是 README，REST /readme 返回的也是它——同一份内容的三个官方入口。
# 只放行这一族文件名，其他文件仍算独立制品（见 _github_key）。
_README_ALIASES = {'', 'readme', 'readme.md', 'readme.markdown', 'readme.txt', 'readme.rst'}


def _doi_of(url: str) -> str:
    """取 URL 里明确用来定位作品的那个 DOI，取不到回空串。

    档 B 需要认得"同一篇作品的三个官方入口"：doi.org/<DOI>、OpenAlex 的
    `works/https://doi.org/<DOI>`、Semantic Scholar 的 `paper/DOI:<DOI>`。
    判据只认"URL 里出现 doi.org/ 或 /doi:"，所以 OpenAlex 自己的 work id
    （`/works/W4386510404`，不含 DOI 串）不会被误归一。
    """
    u = str(url or '').strip()
    lu = u.lower()
    if 'doi.org/' not in lu and '/doi:' not in lu:
        return ''
    m = re.search(r'doi\.org/(10\.\d{4,9}/[^\s"\'<>]+)|/doi:(10\.\d{4,9}/[^\s"\'<>]+)',
                  u, re.I)
    if not m:
        return ''
    return (m.group(1) or m.group(2)).rstrip('/.')


def _clean_url(url: str) -> str:
    """判等之前先切净：回车/换行/制表符可能落在任意位置，首尾空白按 strip 处理。

    实跑 2026-09-24 撞上的形态：从 CRLF 文本或剪贴板带出的 URL 尾部常藏一个回车符，
    于是同一个 README 长出两个制品键；而回车在报错信息里渲染成一个看不见的空位，
    Lead 从消息本身推不出原因，只能逐字猜。

    两条判等通道（_artifact_key 的制品判等、_same_url 的"是不是同一条 URL"）共用这一
    个口径：各自清洗一遍迟早长出差异，届时会出现"键说同一制品、字面说两条 URL"的
    互相打架，拒收理由无法解释。协议与前缀大小写不在这里动——那是各判据自己的事。
    """
    u = str(url or "")
    for ch in (chr(13), chr(10), chr(9)):
        u = u.replace(ch, "")
    return u.strip()


def _artifact_key(url: str) -> str:
    """制品指纹 = 注册域族 + 去掉浏览态路径段的路径。

    档 B 只比注册域会被批量误用：一次传 7 篇论文的 claim + 1 个 check-url，
    域全是 arxiv.org，但 6 条会把"另一篇论文存在"记成自己的反查凭据。
    指纹要求反查打在**同一个制品**上：同一文件的不同检索通道（blob 页 / raw 字节流）
    指纹相同；同仓库不同分支或不同文件视为不同制品。

    三族入口在此归一（2026-09-24 实跑：33 条真反查里 17 条因未归一被误拒）：
    - arXiv 归一到论文 ID：/abs、/pdf、/html、OAI 接口是同一篇论文的四个入口；
      版本后缀不参与判同，/abs 本就重定向到最新版。
    - DOI 归一到 doi 串：doi.org/<DOI> 与 OpenAlex、Semantic Scholar 的书目记录
      是同一篇作品（见 _doi_of）。
    - GitHub 的仓库根与它的 README 算同一制品（见 _github_key）。

    入参先过 _clean_url，控制字符不参与判等。
    """
    u = _clean_url(url)
    doi = _doi_of(u)
    if doi:
        return 'doi:' + doi.lower()
    host = _registered_domain(u)
    if host == 'arxiv.org':
        m = _ARXIV_ID_RE.search(u)
        if m:
            return 'arxiv:' + m.group(1)
    if host == 'github.com':
        return _github_key(u)
    path = re.sub(r'^https?://[^/]+', '', u).lower()
    return host + ':' + path.rstrip('/')
def _github_key(u: str) -> str:
    """GitHub 同一份内容的几个入口归一到 owner/repo@ref:path。

    网页 blob/tree、REST contents、raw 字节流是同一制品（反馈 #4：官方 API 与
    官方网页这对最硬的自证组合，原先两条通道都不认）。ref 缺省（REST 不带
    ?ref=）取的是默认分支，与 main/master 记同一个值；3.14 这类具名分支仍是
    不同制品——版本差异正是结论本身。
    """
    m = re.match(r'https?://([^/]+)/?(?:repos/)?([^/]+)/([^/]+)/?(.*)',
                 str(u or ''))
    if not m:
        return f'github:{str(u or "").lower()}'
    host, owner, repo, rest = m.group(1).lower(), m.group(2), m.group(3), m.group(4)
    seg = rest.split('/')
    ref, path = '', rest
    if seg[0] in ('blob', 'tree', 'raw', 'resolve') and len(seg) > 1:
        ref, path = seg[1], '/'.join(seg[2:])
    elif seg[0] == 'contents':
        ref = re.search(r'[?&](?:ref|sha)=([^&/]+)', u)
        ref, path = (ref.group(1) if ref else ''), '/'.join(seg[1:])
    elif host == 'raw.githubusercontent.com':
        ref, path = seg[0], '/'.join(seg[1:])
    # 'HEAD' 是 GitHub 认的"默认分支"写法（/blob/HEAD/README.md、raw/.../HEAD/...），
    # 与 main/master 同指一个分支；不归一会让同一个 README 长出 @HEAD 与 @head 两个键。
    key_ref = ref.lower() if ref.lower() not in ('', 'main', 'master', 'head') else 'HEAD'
    # 仓库根页 / REST /readme / blob README.md / raw README.md 是同一份内容：
    # GitHub 打开仓库根渲染的就是 README。不归一的话，"来源登记成仓库根、
    # 反查打在 README"这条文档推荐的通道就永远判成不同制品（实跑误拒 17 条）。
    # 只折叠默认分支的 README 一族；具名分支与其余文件保持制品区分。
    path_norm = path.lower().rstrip('/')
    if key_ref == 'HEAD' and path_norm in _README_ALIASES:
        path_norm = ''
    return f'github.com:{owner.lower()}/{repo.lower()}@{key_ref}:{path_norm}'


def _same_url(a: str, b: str) -> bool:
    """两条 URL 是不是字面同一条（清洗控制字符后，抹掉协议、大小写与尾斜杠）。

    这道判等是档 B 的反自批门：把账本里已有的来源再填一遍不算任何验证动作。
    它必须与 _artifact_key 共用 _clean_url 口径——只有一边切控制字符时，
    「同一条 URL」与「同一制品」会各说一套，拒收理由互相打架。
    """
    f = lambda s: re.sub(r'^https?://', '', _clean_url(s).lower()).rstrip('/')
    return bool(f(a)) and f(a) == f(b)


def _is_traceable(url: str) -> bool:
    """能不能点回原文：站内相对链接（/link?url=…）与 javascript: 之类一律不算来源。"""
    return bool(re.match(r'^https?://[^\s/]+', str(url or '').strip()))


def _one_line(text) -> str:
    """压成单行：把所有空白（含换行）折叠成单个空格，并去掉首尾空白。

    claim 文本与来源标题都必须单行：账本 JSONL 一行一条记录，骨架又按
    「每条 claim 一行、行尾带编号与状态标注」渲染。文本里夹一个换行就会被切成两行，
    标注与编号落在不同行上，发布门的行级归因认不出后半行，会把一条已标警告的
    pending claim 误判成正文引用了却没降级（实跑撞上：分片里的转义换行原样进账）。
    """
    return re.sub(r'\s+', ' ', str(text or '')).strip()

def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _slug(text: str) -> str:
    """文本 → 文件安全短名。"""
    s = re.sub(r'[^\w\u4e00-\u9fff-]', '_', text.strip()).strip('_')[:40]
    return s or 'untitled'


def _atomic_append(path: Path, line: str) -> None:
    """追加一行（Windows O_APPEND 原子性；单行小写安全）。"""
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
        f.flush()


def _iter_entries(path: Path):
    """按行读取 jsonl，容错跳过坏行。"""
    if not path.exists():
        return
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue


def _flat_records(data) -> List[Any]:
    """把一份 JSON 值摊平成带 type 的扁平记录。

    容器形状 {"claims": [...], "sources": [...]} 是 SKILL.md 教子 Agent 写的形状，
    展开时补上 type；逐条扁平记录原样通过。
    """
    if isinstance(data, list):
        return [r for d in data for r in _flat_records(d)]
    if not isinstance(data, dict):
        return [data]
    if data.get('type'):
        return [data]
    inner = [(t, data.get(k)) for t, k in
             (('claim', 'claims'), ('source', 'sources'))]
    if any(isinstance(v, list) for _, v in inner):
        return [{**d, 'type': t} for t, v in inner for d in (v or [])
                if isinstance(d, dict)]
    return [data]      # 缺 type 也不猜，交给 merge 点名拒收


def _read_shard_text(path: Path) -> Tuple[str, Optional[str]]:
    """严格按 UTF-8 读分片，返回 (文本, 拒收原因)。

    原先用 read_text(errors='ignore')：Windows 写文件默认 GBK，中文字节被两两拼成
    合法 UTF-8 序列，JSON 照样解析得过——实测 '该政策「支持」中小（企业）发展' 落成
    'ߡ֧֡Сҵչ2026 겹 3~5 Ԫ' 并计入"新增 claim 1 条"。乱码当结论入库比丢数据更糟，
    所以解码失败一律点名拒收，并顺带试出真实编码，别让人自己猜。
    """
    raw = path.read_bytes()
    try:
        return raw.decode('utf-8-sig'), None      # utf-8-sig：Windows 宿主常写 BOM
    except UnicodeDecodeError:
        pass
    for enc in ('gbk', 'gb18030', 'big5', 'shift_jis'):
        try:
            raw.decode(enc)
            return '', (f'看起来是 {enc.upper()} 存的，本工具只收 UTF-8；写分片时显式'
                        f'指定 encoding="utf-8"，否则中文会被解成乱码，进了账本也看不出来')
        except UnicodeDecodeError:
            continue
    return '', '不是任何可识别的文本编码，本工具只收 UTF-8'


def _load_shard(path: Path) -> Tuple[List[Any], List[str]]:
    """读子 Agent 产物，返回 (扁平记录, 解析错误)。

    解析失败必须回话：静默读成 0 条等于把整份分片丢掉而没人知道
    （2026-09-22 实跑：merge 报"拒收 5 条"，正好是 5 个形状不合的分片）。
    """
    txt, why = _read_shard_text(path)
    if why:
        return [], [why]
    items: List[Any] = []
    errors: List[str] = []
    if path.suffix.lower() == '.jsonl':
        for n, line in enumerate(txt.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                items += _flat_records(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                errors.append(f'第 {n} 行不是合法 JSON，该行未进账本')
        return items, errors
    try:
        items = _flat_records(json.loads(txt))
    except (json.JSONDecodeError, ValueError) as e:
        errors.append(f'整份文件不是合法 JSON（{e}），一条都没进账本')
    return items, errors


class ResearchLedger:
    """证据账本。session_dir 即 ledger 根目录。"""

    ENTRIES = 'ledger.jsonl'
    EVIDENCE = 'evidence.jsonl'
    CLAIMS_DIR = 'claims'
    SOURCES_DIR = 'sources'

    def __init__(self, session_dir: str):
        self.root = Path(session_dir)
        self.entries_path = self.root / self.ENTRIES
        self.evidence_path = self.root / self.EVIDENCE
        self.claims_dir = self.root / self.CLAIMS_DIR
        self.sources_dir = self.root / self.SOURCES_DIR
        # merge 的诊断计数（CLI 用）：新增/去重/拒收，让噪声进不了账本也看得见
        self.last_merge = {'claims': 0, 'sources': 0, 'deduped': 0, 'rejected': 0}

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def init(self) -> 'ResearchLedger':
        """创建目录结构（幂等）。"""
        for d in (self.root, self.claims_dir, self.sources_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not self.entries_path.exists():
            self.entries_path.write_text('', encoding='utf-8')
        self._write_session_marker()
        return self

    def _write_session_marker(self) -> None:
        """给 Stop 钩子留一张会话身份证：它靠 session.json 定位账本在哪一层、本轮何时开始。

        原先只有 MCP 的 drux_session_start 写这个文件，而实跑走的是 research.py / ledger.py
        这条 CLI 链——那条链下钩子一条会话都找不到，形同不在场（v6.15 反馈第 15 条）。
        已存在就不覆盖：init 幂等，started_at 不能被重跑刷成"刚刚"。
        """
        sess = self.root.parent if self.root.name == 'ledger' else self.root
        marker = sess / 'session.json'
        if marker.exists():
            return
        marker.write_text(json.dumps({
            'session_id': sess.name,
            'started_at': datetime.now().isoformat(timespec='seconds'),
            'ledger_dir': self.root.relative_to(sess).as_posix(),
        }, ensure_ascii=False), encoding='utf-8')

    def require(self) -> 'ResearchLedger':
        """升/降级前置门：账本必须已存在。

        init() 幂等建目录，路径写错时会让 set-status/verify-primary
        静默建出空账本再返回"0 条"，调用方无从发现 --session 指错了层。
        """
        if not self.entries_path.exists():
            raise FileNotFoundError(
                f'账本不存在: {self.entries_path}'
                f'（--session 应指向 ledger 目录；先执行 init 或用 research.py 的默认路径）')
        return self

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def add_claim(self, claim: str, topic: str = 'general',
                  status: str = 'pending', perspective: str = 'general',
                  confidence: float = 0.5, claim_id: Optional[str] = None,
                  note: str = '') -> Dict[str, Any]:
        """写入一条 claim。

        status ∈ {verified, conflict, supplementing, pending, completed}
        注意：默认 pending——verified 必须由交叉验证（≥2 独立来源）显式赋予，
        未验证的搜索结果一律 pending，防止账本覆盖率虚高。
        """
        status = status if status in VALID_STATUS else 'pending'
        cid = claim_id or f'c-{uuid.uuid4().hex[:10]}'
        entry = {
            'type': 'claim', 'id': cid, 'text': _one_line(claim),
            'topic': str(topic).strip() or 'general',
            'status': status, 'perspective': perspective,
            'confidence': float(min(max(confidence, 0.0), 1.0)),
            'note': note, 'created_at': _now(),
        }
        _atomic_append(self.entries_path, json.dumps(entry, ensure_ascii=False))
        return entry

    def add_source(self, claim_id: str, url: str, title: str = '',
                   tier: Optional[int] = None,
                   craap_score: Optional[float] = None) -> Dict[str, Any]:
        """为 claim 关联一条来源（多源）。tier 缺省时自动分级。

        可点击性闸门与 add_evidence / merge 同一条：三条写入路径漏任何一条，
        点不开的字符串都会拿到 primary_index 编号进报告的引用登记表。
        """
        url = str(url).strip()
        if not _is_traceable(url):
            raise ValueError(f'来源 {url[:60] or "(空)"} 点不回原文，是假溯源 —— '
                             f'只收 http(s) 绝对地址')
        t = int(tier) if tier is not None else (domain_tier(url) if domain_tier else 3)
        t = min(max(t, 1), 4)
        entry = {
            'type': 'source', 'claim_id': claim_id, 'url': url,
            'title': _one_line(title), 'tier': t,
            'craap_score': float(craap_score) if craap_score is not None else None,
            'created_at': _now(),
        }
        _atomic_append(self.entries_path, json.dumps(entry, ensure_ascii=False))
        return entry

    def add_evidence(self, url: str, title: str = '', query: str = '',
                     engine: str = '', tier: Optional[int] = None,
                     craap_score: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """登记一条检索命中的原始证据（它不是 claim）。

        引擎给回的标题是别人页面的标题，不是本调研的论断；把它写成 claim 会让
        5 星空仓库和培训班广告进入覆盖率与引用统计（实测 391 条 merge 后变 602 条）。
        证据只进 evidence.jsonl，Lead 读过内容后再用 add-claim 显式立论。
        """
        url = str(url).strip()
        if not _is_traceable(url):
            return None
        seen = {str(e.get('url') or '') for e in _iter_entries(self.evidence_path)}
        if url in seen:
            return None
        t = int(tier) if tier is not None else (domain_tier(url) if domain_tier else 3)
        entry = {
            'type': 'evidence', 'id': f'e-{uuid.uuid4().hex[:10]}', 'url': url,
            'title': str(title).strip(), 'query': str(query).strip(),
            'engine': engine, 'tier': min(max(t, 1), 4),
            'craap_score': float(craap_score) if craap_score is not None else None,
            'created_at': _now(),
        }
        _atomic_append(self.evidence_path, json.dumps(entry, ensure_ascii=False))
        return entry

    # ------------------------------------------------------------------
    # Lead 归并：原地改状态
    # ------------------------------------------------------------------
    def set_status(self, claim_ids: List[str], status: Optional[str],
                   note: str = '', extra: Optional[Dict[str, Any]] = None,
                   text: str = '') -> int:
        """Lead 在归并阶段把达标 claim 升 verified（或降 pending）。

        必须原地改写而非追加：status() 按条目计数、不做 id 去重，
        追加同 id 新行会让该 claim 被数两次。
        整文件重写 → 只能在全部子 Agent 退出后调用。

        text 非空时同时就地更正 claim 原文：反查常会发现"有一句写错了"，
        只加 note 会让错误原文作为 verified 结论永久留在交付物里。
        status 传 None 表示只改文字不动状态——改错一句话不该顺手把 pending 判成 verified。
        """
        if status is not None and status not in VALID_STATUS:
            return 0
        wanted = {c.strip() for c in claim_ids if c and c.strip()}
        if not wanted:
            return 0
        entries = list(_iter_entries(self.entries_path))
        changed = 0
        for e in entries:
            if e.get('type') == 'claim' and e.get('id') in wanted:
                if status is not None:
                    e['status'] = status
                    e['promoted_at'] = _now()
                if note:
                    e['note'] = note
                if text:
                    e['text'] = text
                    e['amended_at'] = _now()
                for k, v in (extra or {}).items():
                    e[k] = v
                changed += 1
        if changed:
            tmp = self.entries_path.with_suffix('.jsonl.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + '\n')
            os.replace(tmp, self.entries_path)
        return changed

    def verify_primary(self, claim_ids: List[str], check_url: str,
                       check_title: str = '', method: str = '') -> int:
        """档 B 验证：一手来源 + Lead 反查，用于归属型 claim。

        归属型 claim（"某仓库 README 现状是 X"/"某论文原文说 Y"）的对象就是那
        一个制品，要求第二个注册域来"交叉验证"它自身是判据错配——实测本次调研
        有 ~110 条这样的 claim 全被卡在 pending。

        为防止它变成"想升就升"的后门，这里硬性要求：
        1. claim 必须已有至少一条来源；
        2. 反查 URL 必须与既有来源之一指向**同一个制品**（见 `_artifact_key`：
           同域同路径，blob 页与 raw 字节流算同一个）。只比注册域会被批量误用——
           一次传多篇论文的 claim + 一个 check-url，域全对却把别人的证据记到自己头上。
        """
        wanted = {c.strip() for c in claim_ids if c and c.strip()}
        if not wanted or not check_url.strip():
            return 0
        entries = list(_iter_entries(self.entries_path))
        claims = {e['id']: e for e in entries
                  if e.get('type') == 'claim' and e.get('id')}
        src_hosts: Dict[str, set] = {}
        src_urls: Dict[str, set] = {}
        for e in entries:
            if e.get('type') == 'source' and e.get('claim_id'):
                src_hosts.setdefault(e['claim_id'], set()).add(
                    _artifact_key(e.get('url', '')))
                src_urls.setdefault(e['claim_id'], set()).add(
                    str(e.get('url', '')))
        check_host = _artifact_key(check_url)
        targets = []
        for cid in wanted:
            c = claims.get(cid)
            if not c or c.get('type') != 'claim':
                continue
            hosts = src_hosts.get(cid, set())
            if not hosts:
                print(f"拒绝 verify-primary：claim {cid} 无任何来源，"
                      f"归属型断言也必须指向一个制品", file=sys.stderr)
                continue
            if any(_same_url(check_url, u) for u in src_urls.get(cid, set())):
                print(f"拒绝 verify-primary：claim {cid} 的反查 URL 与账本里已有的"
                      f"来源是同一条，重填它没有任何验证动作——换一个通道"
                      f"（同一篇论文的 /pdf、/html、OAI 接口，或同一文件的 raw / "
                      f"REST API）再报", file=sys.stderr)
                continue
            if check_host not in hosts:
                print(f"拒绝 verify-primary：claim {cid} 的反查制品 "
                      f"{check_host!r} 不在其来源制品 {sorted(hosts)} 内 —— "
                      f"反查必须打在同一个制品上（不同分支/不同文件算不同制品）",
                      file=sys.stderr)
                continue
            targets.append(cid)
        if not targets:
            return 0
        changed = self.set_status(targets, 'verified',
                                  note=f'Lead 反查（{method or "unspecified"}）：'
                                       f'{check_url}',
                                  extra={'evidence_tier': 'B',
                                         'verify_method': method})
        for cid in targets:
            self.add_source(cid, check_url, title=check_title, tier=1)
        return changed

    # ------------------------------------------------------------------
    # 合并（子 Agent 产物）
    # ------------------------------------------------------------------
    def _own_paths(self) -> set:
        """账本自己写出来的文件——归并扫目录时要跳过，按路径认不按文件名。

        子 Agent 的分片可以叫任何名字，包括恰好叫 ledger.jsonl；只按名字跳会把真分片丢掉。
        """
        sess = self.root.parent if self.root.name == 'ledger' else self.root
        return {os.path.normcase(str(p.resolve()))
                for p in (self.entries_path, self.evidence_path, sess / 'session.json')}

    def merge(self, src_dir: str) -> Tuple[int, int]:
        """合并 src_dir 下的全部子产物（.jsonl / .json），按 id 去重。

        src_dir 也可以是单个分片文件——把文件路径写成目录路径是最常见的误用，
        原先它对文件与不存在都回 "0 条 + 合并完成"，Lead 分不清"子 Agent 真没产出"
        和"我路径写错了"。

        返回 (新增 claim 数, 新增 source 数)；去重/拒收计数记在 self.last_merge，
        让"有多少噪声被挡在门外"看得见，而不是静默变少。
        """
        src = Path(src_dir)
        stats = {'files': 0, 'claims': 0, 'sources': 0, 'deduped': 0, 'rejected': 0}
        self.last_merge = stats
        if not src.exists():
            raise FileNotFoundError(
                f'分片路径不存在: {src}'
                f'（--dir 传放分片的目录，或直接传单个 .json/.jsonl 文件）')
        if src.is_file():
            files = [src]
        else:
            # --dir 与 --session 同目录是 SKILL.md 写的标准用法，此时 rglob 会扫到
            # 账本自己的文件——它们是合并的结果，不是子 Agent 的产物
            own = self._own_paths()
            files = [f for f in sorted(src.rglob('*.jsonl')) + sorted(src.rglob('*.json'))
                     if os.path.normcase(str(f.resolve())) not in own]
        stats['files'] = len(files)
        if not files:
            print(f'{src} 下没有 *.json / *.jsonl 分片，本次没有可合并的子产物',
                  file=sys.stderr)
        existing = self._ids()
        existing_src = existing_sources(self.root)
        rejects: Dict[Tuple[str, str], int] = {}

        def reject(fname: str, reason: str):
            stats['rejected'] += 1
            rejects[(fname, reason)] = rejects.get((fname, reason), 0) + 1

        for f in files:
            if f.name == self.EVIDENCE:
                continue                       # 证据不是结论，永不进 claim/source 表
            items, errors = _load_shard(f)
            for msg in errors:
                reject(f.name, msg)
            for item in items:
                if not isinstance(item, dict):
                    reject(f.name, '记录不是 JSON 对象')
                    continue
                typ = item.get('type')
                if typ == 'evidence':
                    continue
                elif typ == 'claim':
                    if item.get('id') in existing:
                        stats['deduped'] += 1
                        continue
                    if not str(item.get('text') or '').strip():
                        reject(f.name, 'claim 缺 text，空断言不进账本')
                        continue
                    # 缺 status 一律 pending：合并动作不能自己批准结论
                    self.add_claim(
                        claim=item.get('text', ''), topic=item.get('topic', 'general'),
                        status=item.get('status') or 'pending',
                        perspective=item.get('perspective', 'general'),
                        confidence=item.get('confidence', 0.5),
                        claim_id=item.get('id'), note=item.get('note', ''),
                    )
                    existing.add(item.get('id'))    # 同一份产物里重复 id 也算去重
                    stats['claims'] += 1
                elif typ == 'source':
                    cid = str(item.get('claim_id', ''))
                    url = str(item.get('url', ''))
                    if not cid:
                        reject(f.name, 'source 缺 claim_id，不知道这条来源支撑谁')
                        continue
                    if not _is_traceable(url):
                        reject(f.name, f'来源 {url[:60] or "(空)"} 点不回原文，是假溯源')
                        continue
                    key = (cid, url)
                    if key in existing_src:
                        stats['deduped'] += 1
                        continue
                    self.add_source(cid, url, item.get('title', ''),
                                    item.get('tier'), item.get('craap_score'))
                    existing_src.add(key)
                    stats['sources'] += 1
                else:
                    reject(f.name, '记录没有 type 字段：逐条记录要写 '
                                   '"type": "claim" / "source"，或用 '
                                   '{"claims": [...], "sources": [...]} 容器')
        for (fname, reason), n in sorted(rejects.items()):
            tail = f'（{n} 条）' if n > 1 else ''
            print(f'拒收 {fname}: {reason}{tail}', file=sys.stderr)
        return stats['claims'], stats['sources']

    def _ids(self) -> set:
        return {e['id'] for e in self._all() if e.get('type') == 'claim'}

    # ------------------------------------------------------------------
    # 读取 / 统计
    # ------------------------------------------------------------------
    def _all(self) -> List[Dict[str, Any]]:
        return list(_iter_entries(self.entries_path))

    def claims(self, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        out = [e for e in self._all() if e.get('type') == 'claim'
               and (topic is None or e.get('topic') == topic)]
        out.sort(key=lambda e: e.get('created_at', ''))
        return out

    def sources_for_claim(self, claim_id: str) -> List[Dict[str, Any]]:
        return [e for e in self._all()
                if e.get('type') == 'source' and e.get('claim_id') == claim_id]

    def status(self, topic: Optional[str] = None) -> Dict[str, Any]:
        """按 topic 统计状态与证据充分性。"""
        topics: Dict[str, Dict[str, Any]] = {}
        for e in self._all():
            if e.get('type') != 'claim':
                continue
            if topic is not None and e.get('topic') != topic:
                continue
            t = topics.setdefault(e.get('topic', 'general'), {
                'claims': 0, 'verified': 0, 'conflict': 0, 'supplementing': 0,
                'pending': 0, 'source_urls': set(), 'topics': set(),
            })
            t['claims'] += 1
            st = e.get('status', '')
            if st in t:
                t[st] += 1
        # 补来源统计（独立 URL 集合）
        src_map: Dict[str, set] = {}
        for e in self._all():
            if e.get('type') != 'source':
                continue
            cid = e.get('claim_id', '')
            url = e.get('url', '')
            src_map.setdefault(cid, set()).add(url)
        claim_topic = {e['id']: e.get('topic', 'general')
                       for e in self._all() if e.get('type') == 'claim'}
        for cid, urls in src_map.items():
            top = claim_topic.get(cid)
            if top in topics:
                topics[top]['source_urls'].update(urls)

        result = {}
        for t, s in topics.items():
            n = max(s['claims'], 1)
            # v6.4：独立来源用语义指纹去重（同一通稿跨站转载只算 1），
            # 取代 URL 并集计数——旧法把 N 个转载站当作 N 个独立来源
            verified_claims = [e for e in self.claims(t)
                               if e.get('status') == 'verified']
            insufficient = []
            for c in verified_claims:
                srcs = [{'title': src.get('title', ''), 'url': src.get('url', ''),
                         'tier': src.get('tier')}
                        for src in self.sources_for_claim(c['id'])]
                if effective_independent_count(srcs) < 2:
                    insufficient.append(c['id'])
            result[t] = {
                'claims': s['claims'],
                'verified': s['verified'],
                'conflict': s['conflict'],
                'supplementing': s['supplementing'],
                'pending': s['pending'],
                'independent_sources': len(s['source_urls']),   # 原始 URL 数（参考）
                'effective_sources': sum(
                    effective_independent_count(
                        [{'title': src.get('title', ''), 'url': src.get('url', ''),
                          'tier': src.get('tier')}
                         for src in self.sources_for_claim(c['id'])])
                    for c in self.claims(t)),
                'coverage': round(s['verified'] / n, 2),
                'sufficient': (s['verified'] >= 1 and not insufficient
                               and len(s['source_urls']) >= 2),
                'insufficient_claim_ids': insufficient,
            }
        if topic is not None:
            return result.get(topic, {})
        return result

    def export_json(self, path: Optional[str] = None) -> Dict[str, Any]:
        """导出为完整 JSON（供 validate_report 与报告引用锚定使用）。

        v6.3：为每条 source 注入稳定编号 primary_index（1 起始，按写入顺序），
        报告 [N] 引用与校验门反查共用此编号，实现"引用→具体来源 URL"强契约。
        """
        all_entries = self._all()
        claims = [e for e in all_entries if e.get('type') == 'claim']
        sources = []
        for idx, e in enumerate(
                (e for e in all_entries if e.get('type') == 'source'), start=1):
            e = dict(e)
            e['primary_index'] = idx
            sources.append(e)
        data = {
            'exported_at': _now(),
            'stats': self.status(),
            'claims': claims,
            'sources': sources,
        }
        if path:
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return data

    def export_md(self, path: Optional[str] = None) -> str:
        """导出为 Markdown（按 topic 分组，claim + sources 表格）。"""
        lines = ['# 证据账本（Research Ledger）', '', f'导出时间：{_now()}', '']
        st = self.status()
        lines += ['| 子主题 | claims | verified | conflict | 独立来源 | 覆盖 | 充分 |',
                  '|--------|--------|----------|----------|----------|------|------|']
        for t, s in sorted(st.items()):
            lines.append(f"| {t} | {s['claims']} | {s['verified']} | {s['conflict']} "
                         f"| {s['independent_sources']} | {s['coverage']} | {'✅' if s['sufficient'] else '⚠️'} |")
        lines.append('')
        for topic in sorted(set(c['topic'] for c in self.claims())):
            lines += [f"## {topic}", '']
            for c in self.claims(topic):
                lines.append(f"- [{c['id']}] **{c['text']}**"
                             f"（状态:{c['status']} 视角:{c['perspective']} 置信:{c['confidence']}）")
                for s in sorted(self.sources_for_claim(c['id']), key=lambda x: x['tier']):
                    lines.append(f"  - Tier{s['tier']} [{s['title'] or s['url']}]({s['url']})"
                                 + (f" CRAAP:{s['craap_score']}" if s.get('craap_score') is not None else ''))
            lines.append('')
        md = '\n'.join(lines)
        if path:
            Path(path).write_text(md, encoding='utf-8')
        return md


def existing_sources(root: Path) -> set:
    """已存在的 (claim_id, url) 集合（供 merge 去重）。"""
    out = set()
    if (root / ResearchLedger.ENTRIES).exists():
        for e in _iter_entries(root / ResearchLedger.ENTRIES):
            if e.get('type') == 'source':
                out.add((e.get('claim_id', ''), e.get('url', '')))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    def _session():
        if '--session' not in args:
            print('缺少 --session <目录>', file=sys.stderr)
            sys.exit(2)
        return args[args.index('--session') + 1]

    def _opt(name: str, default: str = '') -> str:
        if name in args:
            return args[args.index(name) + 1]
        return default

    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        print('''\n用法:
  python ledger.py init --session <dir>
  python ledger.py add-claim --session <dir> --text <claim> [--topic <t>] [--status <s>]
                    [--perspective <p>] [--confidence <0-1>] [--id <id>] [--note <n>]
  python ledger.py add-source --session <dir> --claim-id <id> --url <u>
                    [--title <t>] [--tier <1-4>] [--craap <score>]
                    # --url 只收 http(s) 绝对地址：站内相对链接、javascript:、
                    # "见前面报告"这类点不回原文的一律退 2 拒收，不占引用编号
  python ledger.py status --session <dir> [--topic <t>]
                    # 无 --topic：{"topics": {主题: 明细}, "totals": {全局合计}}
                    # 有 --topic：只出该主题的明细；主题名打错会列出现有主题并退 2
  python ledger.py set-status --session <dir> --claim-id <id>[,<id>...]
                    [--status <s>] [--note <n>] [--text <就地更正后的 claim 原文>]
                    # --status 与 --text 至少给一个；只给 --text 时状态原样不动
  python ledger.py verify-primary --session <dir> --claim-id <id>[,<id>...] \
      --check-url <一手制品URL> [--check-title <t>] [--method repo_health]
  python ledger.py merge --session <dir> --dir <src_dir|分片文件>
                    # 递归收 *.json/*.jsonl（--dir 给单个文件也认）；只收 UTF-8 分片，
                    # 编码不对/路径不存在都点名回话，不会静默报"0 条"
                    # 记录形状两种都认：
                    # 逐条 {"type":"claim","id","text","topic"} /
                    #      {"type":"source","claim_id","url","title","tier"}
                    # 容器 {"claims":[...], "sources":[...]}（容器内可省 type）
  python ledger.py export --session <dir> [--format json|md] [--out <path>]''')
        return 0

    cmd = args[0]
    session = _session()
    ledger = ResearchLedger(session)

    if cmd == 'init':
        ledger.init()
        print(f'已初始化账本: {session}')
        return 0

    if cmd == 'add-claim':
        ledger.init()
        if '--text' not in args:
            print('缺少 --text <claim>', file=sys.stderr)
            return 2
        entry = ledger.add_claim(
            claim=args[args.index('--text') + 1],
            topic=_opt('--topic', 'general'),
            status=_opt('--status', 'pending'),
            perspective=_opt('--perspective', 'general'),
            confidence=float(_opt('--confidence', '0.5')),
            claim_id=_opt('--id', '') or None,
            note=_opt('--note', ''),
        )
        print(json.dumps(entry, ensure_ascii=False))
        return 0

    if cmd == 'add-source':
        ledger.init()
        cid = _opt('--claim-id')
        url = _opt('--url')
        if not cid or not url:
            print('缺少 --claim-id / --url', file=sys.stderr)
            return 2
        try:
            entry = ledger.add_source(
                claim_id=cid, url=url, title=_opt('--title'),
                tier=int(_opt('--tier')) if _opt('--tier') else None,
                craap_score=float(_opt('--craap')) if _opt('--craap') else None,
            )
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(json.dumps(entry, ensure_ascii=False))
        return 0

    if cmd == 'verify-primary':
        try:
            ledger.require()
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        ids = [i.strip() for i in _opt('--claim-id').split(',') if i.strip()]
        check_url = _opt('--check-url')
        if not ids or not check_url:
            print('缺少 --claim-id / --check-url', file=sys.stderr)
            return 2
        changed = ledger.verify_primary(
            ids, check_url, check_title=_opt('--check-title'),
            method=_opt('--method'))
        print(f'档 B 升级 {changed} 条 claim（反查：{check_url}）')
        return 0 if changed else 1

    if cmd == 'set-status':
        try:
            ledger.require()
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        ids = [i.strip() for i in _opt('--claim-id').split(',') if i.strip()]
        status, text = _opt('--status'), _opt('--text')
        if not ids:
            print('缺少 --claim-id', file=sys.stderr)
            return 2
        if not status and not text:
            print('缺少 --status（改状态）或 --text（就地更正原文），至少给一个',
                  file=sys.stderr)
            return 2
        changed = ledger.set_status(ids, status or None, note=_opt('--note'),
                                    text=text)
        print(f'已更新 {changed} 条 claim'
              + (f' → {status}' if status else '')
              + ('（原文已就地更正）' if text else ''))
        return 0 if changed else 1

    if cmd == 'status':
        topic = _opt('--topic', '') or None
        data = ledger.status(topic)
        if topic is not None:
            if not data:
                names = ', '.join(sorted(ledger.status())) or '（账本里还没有 claim）'
                print(f'账本里没有主题「{topic}」，现有主题：{names}', file=sys.stderr)
                return 2
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        # 固定信封：主题明细放 topics，全局合计放 totals。
        # 只改 CLI 出口——进程内 status() 仍是主题字典，发布门按它迭代主题。
        claims = sum(s.get('claims', 0) for s in data.values())
        verified = sum(s.get('verified', 0) for s in data.values())
        totals = {
            'topics': len(data),
            'claims': claims,
            'verified': verified,
            'conflict': sum(s.get('conflict', 0) for s in data.values()),
            'supplementing': sum(s.get('supplementing', 0) for s in data.values()),
            'pending': sum(s.get('pending', 0) for s in data.values()),
            'coverage': round(verified / claims, 2) if claims else 0.0,
            'sufficient_topics': sum(1 for s in data.values() if s.get('sufficient')),
            'insufficient_topics': [t for t, s in data.items()
                                    if not s.get('sufficient')],
        }
        print(json.dumps({'topics': data, 'totals': totals},
                         ensure_ascii=False, indent=2))
        return 0

    if cmd == 'merge':
        src = _opt('--dir')
        if not src:
            print('缺少 --dir <src_dir>', file=sys.stderr)
            return 2
        try:
            c, s = ledger.merge(src)
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        st = ledger.last_merge
        if not st['files']:
            return 0        # 一份分片都没看见，别再打一行像是成功 receipts 的统计
        print(f'合并完成：收到 {st["files"]} 份分片，新增 claim {c} 条，source {s} 条，'
              f'去重 {st["deduped"]} 条，拒收 {st["rejected"]} 条'
              '（拒收＝点不回原文、缺类型或编码不对的记录，不会进账本；逐条原因已按文件名打在 stderr）')
        return 0

    if cmd == 'export':
        fmt = _opt('--format', 'json')
        out = _opt('--out', '') or None
        if fmt == 'md':
            print(ledger.export_md(out))
        else:
            data = ledger.export_json(out)
            if not out:
                print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f'未知命令: {cmd}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    from console import force_utf8
    force_utf8()
    sys.exit(_main())