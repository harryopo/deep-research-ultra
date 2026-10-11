"""v6.66.0：四处"文档/输出说了什么"与"代码实际是什么"对不上。

体检里这四条我最初都判成了"漂移/缺陷"，**读代码后有两条证明是误判**。
这里把真实缺陷与误判原因一起钉住——尤其是误判：写下来是为了防止下一次
（比如别人只看输出不看口径）又把它当成 bug 报一遍。

1. **分层数字（P1-12）**：`--list` 原先打 `configured_by_layer`（11/14/2/3），
   SKILL.md §四 结构图写全量（13/14/3/4）。两个数都"对"，只是口径不同且都没标。
   我最初判成"文档漂移"，实测注册表 `13/14/3/4` 与文档完全一致——**误判**。
   真缺陷是口径不明，现在两行并排打印并写明各自含义。
   （另一个坑：`summary['by_layer']` 是按 `available` 分的，走实时探测，
   本机 MCP 未连时 L1 只剩 6，比"就绪"还少——拿它当"全量"是第三个错误口径。）

2. **env_check 网络预检（P1-7）**：报 `github.com:443 不可达`，措辞却断言
   "这些源现在一条也取不到"。实测同时 `--probe` 里 GitHub 深搜各出 5 条。
   预检比真实调用更不可信 → 假阴性会让人放弃招牌能力，比不做预检更糟。

3. **duckduckgo 引擎（P1-8）**：名字是 DuckDuckGo，实现是 `ddgs` 聚合库，
   会在 DuckDuckGo/Bing/Brave/Startpage 等后端间轮换。排障时看到
   "duckduckgo 超时"实际是某个后端超时，误导定位。

4. **注册表单测可复核**：分层计数从注册表直接算，不硬编码。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SKILL_ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))


# ---------------------------------------------------------------------------
# 1. 分层数字：口径要明，且与注册表一致
# ---------------------------------------------------------------------------

def test_registry_layer_counts_match_the_doc_diagram():
    """SKILL.md §四 结构图的四个数字必须等于注册表实测值。

    体检初稿把这里判成"文档漂移 13 vs 11"，实测证明是误判：11 是"配置就绪"口径。
    这条断言现在把**全量**口径钉住，将来真漂移了会立刻红。
    """
    from research import build_registry
    reg = build_registry()
    counts = {l: sum(1 for e in reg.get_all() if e.get_layer() == l)
              for l in (1, 2, 3, 4)}
    md = (SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
    found = {int(m): int(n) for m, n in
             re.findall(r'Layer (\d)[^\n]*?（(\d+) 个引擎', md)}
    assert found, 'SKILL.md §四 的分层结构图不见了——这条断言会空转'
    assert found == counts, (
        f'文档分层 {found} ≠ 注册表实测 {counts}——这次是真的漂移了')


def test_list_output_shows_both_calibers():
    """两个口径都打，且各自标明含义。

    只打一个会让读者拿它去对文档，误以为文档错了——这正是体检初稿的误判。
    """
    import subprocess
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / 'research.py'), '--list'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(SCRIPTS))
    text = (out.stdout or '') + (out.stderr or '')
    assert '全量分层' in text and '配置就绪分层' in text, text[-400:]
    assert '同源' in text, '没说明「全量」那行与 §四 结构图同源'


def test_all_by_layer_is_not_the_available_based_one():
    """`summary['by_layer']` 按 available 分，不能拿来当"全量"。

    available 走实时探测：本机 MCP 没连时 L1 只剩 6，比"配置就绪"还少。
    拿它当全量会得出"L1 只有 6 个引擎"的荒谬结论——这是本条要防的事。
    """
    from research import build_registry
    reg = build_registry()
    total_by_registry = {l: sum(1 for e in reg.get_all() if e.get_layer() == l)
                         for l in (1, 2, 3, 4)}
    summary = reg.summary()
    # 三个口径互不相同：全量 ≥ 配置就绪 ≥ available（数字上不保证单调，
    # 但全量必须等于 get_all() 的直接统计，且 by_layer 绝不能冒充它）
    assert summary['total'] == sum(total_by_registry.values()), (
        f'全量分层之和 {sum(total_by_registry.values())} '
        f'≠ summary.total {summary["total"]}')
    for layer, n in total_by_registry.items():
        assert n >= 1, f'Layer {layer} 一个引擎都没有——统计口径坏了'
    assert 'by_layer' in summary, 'summary 应保留 by_layer（本条只要求不拿它当全量）'


# ---------------------------------------------------------------------------
# 2. env_check：预检不许断言引擎不可用
# ---------------------------------------------------------------------------

def test_env_check_does_not_claim_engines_are_unusable(monkeypatch):
    import env_check as EC
    monkeypatch.setattr(EC, '_check_net',
                        lambda host, timeout=3.0: (False, f'{host}:443 模拟断网'))
    text = EC.format_report(EC.run_env_check('academic', include_net=True))
    assert '这些源现在一条也取不到' not in text, (
        '预检又断言引擎不可用了——实测反例：env_check 报 github.com 不通的同时，'
        'probe 里 GitHub 深搜正常出 5 条')
    assert '唯一判据' in text or '--probe' in text, \
        '必须指向 --probe 作为"今天出不出得来数据"的判据'


def test_env_check_still_says_the_consequence():
    """不许从"说后果"退化成"只报一个不可达"。

    原测试钉的就是这条（"说清后果，不是只报个不可达"）。v6.66 只改后果的**说法**，
    不删后果——预检失败后用户仍需要知道该做什么。
    """
    import env_check as EC
    old = EC._check_net
    EC._check_net = lambda host, timeout=3.0: (False, f'{host}:443 模拟断网')
    try:
        text = EC.format_report(EC.run_env_check('academic', include_net=True))
    finally:
        EC._check_net = old
    for host in ('arxiv.org', 'api.openalex.org', 'doi.org'):
        assert host in text, f'失败的主机没点名：{host}'
    assert '不代表对应引擎取不到数据' in text, text[-500:]


# ---------------------------------------------------------------------------
# 3. duckduckgo：名字不是它干的事
# ---------------------------------------------------------------------------

def test_duckduckgo_engine_is_actually_an_aggregator():
    """它调的是 ddgs 聚合库，会在多个后端间轮换。

    排障时看到 "duckduckgo 超时"要去查 DuckDuckGo，实际超时的是某个后端
    （实测 probe 抓到的是 startpage.com）。描述必须如实说明。
    """
    from research import build_registry
    eng = next(e for e in build_registry().get_all() if e.get_name() == 'duckduckgo')
    text = eng.metadata.description
    assert 'ddgs' in text or '聚合' in text, (
        f'引擎描述没说清它是 ddgs 聚合库——按名字排障会找错地方：{text}')
    assert '轮换' in text or 'Startpage' in text, (
        f'描述没说清多后端轮换：{text}')


def test_skill_md_flags_the_aggregator_behaviour():
    """SKILL.md 的降级层注记也要写清——Lead 看到超时回执时第一眼看这里。"""
    md = (SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
    line = next((l for l in md.splitlines() if 'duckduckgo' in l.lower()), '')
    assert 'ddgs' in line or '聚合' in line, (
        f'结构图里的 duckduckgo 那行没说它是聚合库：{line}')


# ---------------------------------------------------------------------------
# 4. 首次配置不该只有 bash 一条路
# ---------------------------------------------------------------------------

def test_first_run_has_a_bash_free_path():
    """README 主打多宿主，而首次配置的第一步原本只有 `bash setup-mcp.sh`。

    Windows / 精简容器上没有 bash（仓库里那两条 skip 测试正是因此），
    照文档办事的新用户第一步就断了。项目里早就有跨平台的
    `mcp_config_writer.py`——它直接写 .mcp.json，不依赖任何宿主 CLI。
    """
    md = (SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
    sec = md.split('### 13.1', 1)[1].split('\n## ', 1)[0]
    assert 'bash' in sec, '13.1 不再是 bash 路径了？那这条断言要重写'
    assert 'mcp_config_writer.py' in sec, (
        '首次配置没有 bash 以外的路径——Windows 用户第一步就断')


def test_the_bash_free_path_actually_writes_a_readable_config(tmp_path):
    """不只验文档写了什么，跑一遍看它真能用。

    `mcp_config_writer` 写出的 .mcp.json 必须能被 `mcp_client` 读成已注册的
    server——否则文档给的是另一条死路。
    """
    import json
    from mcp_config_writer import merge_server

    cfg = tmp_path / '.mcp.json'
    cfg.write_text('{"mcpServers": {}}', encoding='utf-8')
    merge_server(cfg, 'open-websearch',
                 {'DEFAULT_SEARCH_ENGINE': 'bing', 'MODE': 'stdio'},
                 ['npx', '-y', 'open-websearch@latest'])
    data = json.loads(cfg.read_text(encoding='utf-8'))
    srv = data['mcpServers']['open-websearch']
    assert srv['command'] == 'npx', srv
    assert srv['args'][1] == 'open-websearch@latest', srv
    assert srv['env']['DEFAULT_SEARCH_ENGINE'] == 'bing', srv

    # 重复注册是幂等的（文档让用户逐条跑两遍，不能把配置堆坏）
    merge_server(cfg, 'open-websearch', {}, ['npx', '-y', 'open-websearch@latest'])
    again = json.loads(cfg.read_text(encoding='utf-8'))
    assert len(again['mcpServers']) == 1, again


def test_uvx_requirement_is_stated_for_the_arxiv_server():
    """`--core` 里 arxiv 依赖 uvx，缺 uv 时 setup-mcp.sh 是跳过而不是失败。

    文档里给的等价路径也得说清这条，否则用户照做后 arxiv server 没注册，
    却以为是 skill 的 bug。
    """
    md = (SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
    sec = md.split('### 13.1', 1)[1].split('\n## ', 1)[0]
    arxiv_line = next((l for l in sec.splitlines() if '--server arxiv' in l), '')
    follow = sec[sec.find('--server arxiv'):][:300]
    assert 'uvx' in arxiv_line or 'uvx' in follow, (
        '给 arxiv server 的等价命令没说它需要 uvx')
