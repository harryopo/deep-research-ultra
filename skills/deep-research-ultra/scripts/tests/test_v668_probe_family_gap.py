"""v6.68.0：探针同族限流——机制建起来，但**没有证明它能救回 S2**。

## 起因

体检 P1-11 实测：`--probe` 跑完，`semantic-scholar` 与 `s2-citation-graph` 双双
`HTTP 429`。`s2-citation-graph` 的 `search()` 委托 S2，两个引擎匿名打同一个端点、
还共用同一个探针词——第二发吃的就是第一发刚攒出来的限流窗，而 429 在回执里长得很像
"这个源没配好"。**自检制造了它本该检测的故障。**

## 这版做了什么 / 没做什么

做了：探针认识"同族 = 共用同一上游"，同族之间让一拍（默认 3s，`--probe-gap` 可调、
设 0 关掉），失败时在回执里点名同族。

**没做到：没能证明这个间隔救得回 S2。** 实测把间隔从 0 放到 12 秒，两个引擎**仍然双双
429**。也就是说匿名配额可能早被本轮之前（甚至别的进程）的调用耗尽——是共享额度问题，
不是这一轮连发造成的。

所以回执的措辞刻意写成"优先怀疑该上游的共享配额/限流窗，而不只是同族连发"，
**不把相关性写成因果**。这个区分是本测试的核心：防的是把"改了代码"当成"修好了"。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe import ENGINE_FAMILY, FAMILY_GAP_SECONDS  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 同族表要有真实依据
# ---------------------------------------------------------------------------

def test_s2_engines_are_NOT_paired_as_one_family():
    """**这一条是纠错**：v6.68.0 第一版按域名把 S2 两引擎配成同族，被实测否掉了。

    实测（2026-10-11）：
      · 单发 `semantic-scholar`（前面零调用）→ 429
      · 30 秒后单发 `s2-citation-graph`  → ✅ 5 条
    既不是同族连发，也不是共享配额耗尽（配额 30 秒后就恢复了）。
    真相是**端点不同、限流桶不同**：`SemanticScholarEngine.SEARCH_URL` 打
    `graph/v1/paper/search`（S2 限流最严的端点，匿名单发即拒），
    `CitationGraphEngine` 走 `recommendations/v1`（宽松）。**同域 ≠ 同桶。**
    """
    assert 'semantic-scholar' not in ENGINE_FAMILY, (
        'S2 两引擎走不同端点、不同限流桶，不该配成同族——'
        '这个错误假设会让让拍机制保护不了任何东西，却给回执塞进错误的归因')
    assert 's2-citation-graph' not in ENGINE_FAMILY


def test_only_genuinely_shared_quotas_are_paired():
    """留下来的两对必须真的共享配额，否则这张表就该清空。"""
    # GitHub 两引擎吃同一个 GITHUB_TOKEN 的 5000/h 配额——真同桶
    assert (ENGINE_FAMILY.get('github-deep-search')
            == ENGINE_FAMILY.get('github-code-search') == 'github-token-quota')
    # 百度两个直连解析打同一个 IP
    assert (ENGINE_FAMILY.get('baidu-serp')
            == ENGINE_FAMILY.get('baidu-html') == 'baidu-ip')
    # arxiv 那对拆掉了：MCP server 与 HTTP 直连是两条通道，各有各的限流
    assert 'arxiv' not in ENGINE_FAMILY and 'arxiv-fulltext' not in ENGINE_FAMILY


def test_family_table_has_no_orphan_entries():
    """孤儿键（同族表里写了不存在的引擎名）会让"同族让拍"永远不触发。"""
    from research import build_registry
    known = {e.get_name() for e in build_registry().get_all()}
    unknown = set(ENGINE_FAMILY) - known
    assert not unknown, f'同族表里有不存在的引擎名：{unknown}'


def test_gap_is_a_few_seconds_not_ninety():
    """90 秒是"人工隔一会儿重跑单发"的建议，不是一轮自检的间隔。

    照搬 90 秒会让整轮自检多花好几分钟，用户就不会再跑它了。
    """
    assert 0 < FAMILY_GAP_SECONDS <= 10, (
        f'间隔 {FAMILY_GAP_SECONDS} 秒：太小挡不住限流，太大自检没人愿意等')


# ---------------------------------------------------------------------------
# 2. 措辞不许把相关性说成因果
# ---------------------------------------------------------------------------

def test_note_does_not_blame_only_the_family_collision():
    """回执不许把可疑原因说成确定结论。

    这一版的教训比上一版更重：上一版写"优先怀疑共享配额"也是错的——配额 30 秒后就
    恢复了。**两次都把"改了什么"当成了"是什么在起作用"。**
    """
    src = (Path(__file__).resolve().parents[1] / 'research.py').read_text(encoding='utf-8')
    assert '可能' in src, '回执把可疑原因说成了确定结论'
    assert '共享配额' not in src, (
        '"共享配额耗尽"已被实测否掉（30 秒后单发就恢复），别再当归因写进回执')


def test_s2_gets_an_endpoint_specific_advice():
    """semantic-scholar 的 429 要说清"等 90 秒没用，得配 key"。

    实测：那个端点匿名单发即拒。而同域的 s2-citation-graph 30 秒后单发能出 5 条，
    所以"两个 S2 都不通 = 配额问题"是错的推断。
    """
    from probe import S2_PAPER_SEARCH_NOTE, _advice_for
    note = S2_PAPER_SEARCH_NOTE
    assert 'paper/search' in note, '没点名是哪个端点限流'
    assert '单发' in note, '没说明单发也会被拒（那正是"等 90 秒"无效的原因）'
    assert 'key' in note.lower(), '没给出真正的解法（配 key）'
    assert 'recommendations' in note, '没解释同域另一个引擎为什么能通'


def test_s2_advice_is_only_for_semantic_scholar():
    """挂到两个引擎上会被 guidance 并成一行，出现自相矛盾的两句话。"""
    from probe import _advice_for
    s2a = _advice_for({'engine': 'semantic-scholar', 'status': 'failed',
                       'note': '引擎返回 None（HTTP 429 rate limited）'})
    s2b = _advice_for({'engine': 's2-citation-graph', 'status': 'failed',
                       'note': '引擎返回 None（HTTP 429 rate limited）'})
    joined_a, joined_b = ' '.join(s2a), ' '.join(s2b)
    assert 'paper/search' in joined_a, 'semantic-scholar 没拿到端点专属说明'
    assert 'paper/search' not in joined_b, \
        '端点专属说明挂到了 s2-citation-graph 上——两条并成一行会自相矛盾'


def test_probe_gap_flag_is_wired():
    """`--probe-gap` 必须真的接进 parser，且 0 能关掉间隔。

    parser 建在 `main()` 里（模块级没有导出的 parser 属性），所以跑真脚本，
    用一个会立刻失败的方式验证 flag 被认得：设 0 时不应报"unrecognized arguments"。
    """
    import subprocess
    cwd = str(Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, 'research.py', '--probe', '--probe-gap', '0',
                        '--sources', 'baidu-html', '--limit', '1'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', cwd=cwd)
    out = (r.stdout or '') + (r.stderr or '')
    assert 'unrecognized arguments' not in out, f'--probe-gap 没被认得：{out[-300:]}'
    assert 'usage: research.py' not in out, f'argparse 认为参数非法：{out[-300:]}'
