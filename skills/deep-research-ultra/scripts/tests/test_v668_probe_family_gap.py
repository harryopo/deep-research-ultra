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

def test_s2_engines_are_recognised_as_one_family():
    """它们共用同一个上游：s2-citation-graph 的 search() 委托 S2。"""
    assert ENGINE_FAMILY.get('semantic-scholar') == 's2'
    assert ENGINE_FAMILY.get('s2-citation-graph') == 's2'


def test_family_table_has_no_orphan_entries():
    """孤儿键（同族表里写了不存在的引擎名）会让"同族让拍"永远不触发。"""
    from research import build_registry
    known = {e.get_name() for e in build_registry().get_all()}
    unknown = set(ENGINE_FAMILY) - known
    assert not unknown, f'同族表里有不存在的引擎名：{unknown}'


def test_unrelated_engines_are_not_paired():
    """别把无关的引擎配成同族——那会让整轮平白变慢。

    反过来也别漏：确实共用上游的（百度 SERP 与百度 HTML 解析）必须成对。
    """
    assert ENGINE_FAMILY.get('openalex') is None and ENGINE_FAMILY.get('pubmed') is None, \
        'openalex 与 pubmed 是两个独立上游，不该进同族表'
    assert ENGINE_FAMILY.get('baidu-serp') == ENGINE_FAMILY.get('baidu-html') == 'baidu', \
        '百度 SERP 与百度 HTML 共用百度，必须成对，否则同族让拍漏掉这一对'
    assert ENGINE_FAMILY.get('sogou-weixin') is None, \
        '搜狗微信与百度 SERP 不是同一上游'


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
    """实测 12 秒间隔仍然双双 429 → 不能断言"就是同族连发造成的"。

    这是本版最要紧的一条：改了机制不等于修好了问题，回执要把真实成因留在选项里。
    """
    src = (Path(__file__).resolve().parents[1] / 'research.py').read_text(encoding='utf-8')
    seg = src[src.find("同属 {fam} 上游"):src.find("同属 {fam} 上游") + 400] \
        if '同属 {fam} 上游' in src else src
    assert '共享配额' in seg or '配额' in src, \
        '回执没提"上游共享配额"这个更可能的原因'
    assert '可能' in seg or '优先怀疑' in seg, \
        '回执把可疑原因说成了确定结论'


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
