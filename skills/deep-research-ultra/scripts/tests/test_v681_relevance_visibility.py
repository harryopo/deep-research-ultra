"""v6.81：把 relevance 露出（账本 + 控制台 + CSV），以及"实跑量测推翻了原修法"的记录。

## 背景：这一版的由来

2026-10-12 用这个 skill 跑真实实验（臂 1 基线），发现证据集里混进了完全无关的东西：
`L-FAME: Longitudinal Focused Attention Meditation EEG Dataset`（EEG 冥想数据集）
和 `Bitstream-Corrupted Video Recovery`（视频恢复）出现在「开源 RAG 评测框架选型」
的证据集中。当时给出的修法是"把相关性阈值改成要求关键词与查询有实际交集"。

**实测把那个修法否掉了**（脚本在 `.research/diag_rel_vs_total.py`，结论见 CHANGELOG）：

- 那两条噪声**本来就有关键词交集**（`dataset`、`benchmark` 命中）——交集检查一条都拦不住
- 也不是阈值问题：`L-FAME` 的 relevance **64 分排第 4/29**，高于真正切题的
  `MultiHop-RAG`（58，第 5）和 `CPRet`（58，第 6）。**排序本身就是错的**，降到 50 也留着它
- 「必须命中领域特征词」的规则只能剔掉 3 条里的 2 条——漏掉最严重的那个
  （`L-FAME` 的摘要里含 retrieval/generation）

所以**没有改评分公式**：手上只有 29 条里 3 条标注过的噪声，调权重就是猜。
这个项目有现成的前车之鉴——v6.70「宣称 34 源 vs 实出 14，是宣传口径问题……是我的修法
不如现状」。

这一版改的是**可见性**：账本只存 `craap_score`(total) 把 relevance 丢了，而 total
不是 relevance 的代理（实测两张名次只有 1/29 逐位重合）。加上控制台不报"留下的里
还有多少低相关"。判断仍留给 Lead——与本项目「提示不是门」一致。
"""
from __future__ import annotations

import ast
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

from ledger import ResearchLedger, _iter_entries      # noqa: E402
from research import _rel_note, _report_relevance_spread  # noqa: E402


# ---------------------------------------------------------------------------
# 一、账本：relevance 与 relevance_capped 落盘
# ---------------------------------------------------------------------------

def test_add_evidence_persists_relevance(tmp_path):
    """账本必须留下 relevance —— 以前只有 total，Lead 无从判断哪条切题。"""
    led = ResearchLedger(str(tmp_path / 'led')).init()
    ev = led.add_evidence(url='https://example.org/a', title='A',
                          relevance=64.0, relevance_capped=False,
                          craap_score=94.4)
    assert ev['relevance'] == 64.0
    assert ev['relevance_capped'] is False
    assert ev['craap_score'] == 94.4, 'craap_score 语义不变（total），别顺手改掉'


def test_relevance_capped_is_kept_distinct_from_zero(tmp_path):
    """capped 时 relevance 是 0.0，但**含义完全不同**。

    score.py 在判定失效时把 relevance 压成 0.0 并把 grade 标 `unrated`——
    那是 v6.63「不可判定时不装懂」的同一个区分。只存 0.0 不存 capped，
    读的人就分不清「评出来是 0」和「压根没评出来」，那个混淆又回来了。
    """
    led = ResearchLedger(str(tmp_path / 'led')).init()
    ev = led.add_evidence(url='https://example.org/b', title='B',
                          relevance=0.0, relevance_capped=True, craap_score=52.0)
    assert ev['relevance'] == 0.0 and ev['relevance_capped'] is True

    txt = _rel_note({'relevance': 0.0, 'relevance_capped': True})
    assert '未判定' in txt, f'capped 不得渲染成普通分数：{txt}'
    assert '不等于不相关' in txt, '必须说清是判定失效而非不相关'
    assert _rel_note({'relevance': 0.0, 'relevance_capped': False}) == '0/100'


def test_old_evidence_records_still_readable(tmp_path):
    """旧账本（v6.80 之前写的）没有这两个键，读方必须容错。

    判据是**实跑留下的那份**：本轮实验的 29 条证据就是老格式，直接拿它当夹具形状，
    而不是手搓一个"看起来像旧版"的样本。
    """
    led = ResearchLedger(str(tmp_path / 'led')).init()
    led.add_evidence(url='https://example.org/c', title='C', craap_score=91.0)
    p = led.evidence_path
    rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    for r in rows:                      # 抹掉新键，模拟 v6.80 之前的记录
        r.pop('relevance', None)
        r.pop('relevance_capped', None)
    p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
                 encoding='utf-8')

    reread = ResearchLedger(str(tmp_path / 'led')).init()
    entries = list(_iter_entries(reread.evidence_path))
    assert entries, '老记录读不出来了'
    for e in entries:
        assert e.get('relevance') is None, '缺键必须回落 None，不能 KeyError'
        assert e.get('relevance_capped') is None


# ---------------------------------------------------------------------------
# 二、控制台：相关性分布 + 「留下的里还有多少低相关」
# ---------------------------------------------------------------------------

def _capture(results, threshold=50):
    buf = io.StringIO()
    with redirect_stderr(buf):
        _report_relevance_spread(results, threshold)
    return buf.getvalue()


class _R:
    """新鲜检索的结果是带属性的对象（不是 dict）。"""
    def __init__(self, craap):
        self.craap_score = craap


def test_spread_reports_low_survivors():
    """这是本版的核心信号：被丢与被留不是同一件事。

    实跑那次：29 条落盘、17 条 relevance < 50，控制台只说"丢弃 19 条"，
    对那 17 条一声不吭。
    """
    out = _capture([_R({'relevance': r}) for r in (74, 58, 58, 52, 42, 42, 42, 36)])
    assert '📐' in out and '36' in out and '74' in out, out
    assert '其中 4 条仍低于 50' in out, out
    assert '不保证' in out, '要说清过滤保证的是什么、不保证什么'


def test_spread_reads_dicts_too():
    """缓存命中时结果是 JSON 反序列化出的 **dict**，不是对象。

    第一版只写了 `getattr(r, 'craap_score', None)`，于是**最常见的路径静默拿不到
    分数**——分布行压根不打印，而且不报错。判据必须同时覆盖两种形状。
    """
    dicts = [{'craap_score': {'relevance': 74}}, {'craap_score': {'relevance': 30}}]
    out = _capture(dicts)
    assert '📐' in out, 'dict 形状读不到分数'
    assert '其中 1 条仍低于 50' in out, out


def test_capped_items_announced_separately():
    """判定失效要单独说，不能混在低相关里当零分。"""
    out = _capture([_R({'relevance': 0.0, 'relevance_capped': True}),
                    _R({'relevance': 70.0})])
    assert 'ℹ️' in out and '判定失效' in out, out
    assert '别当零分读' in out, '必须明说它不是零分'


def test_no_scores_prints_nothing_and_does_not_crash():
    """老缓存没有 craap_score 时不许炸，也不许假装有分布。"""
    assert _capture([{}, {'craap_score': '坏形状'}]) == ''
    assert _capture([]) == ''
    assert _capture(None) == ''


# ---------------------------------------------------------------------------
# 三、两条路径都得调（缓存命中那条会提前 return）
# ---------------------------------------------------------------------------

def test_both_code_paths_report_the_spread():
    """缓存命中分支直接 `return`，第一版把新逻辑只挂在新鲜检索那条路上。

    后果是"越常用缓存越看不到这个信号"——而缓存命中恰恰是常见路径。

    判据用 AST **比较行号**：调用必须在那个 return 之前。只数"有没有调用"是不够的，
    写在 return 后面等于没写（这正是第一版的错法）。
    """
    tree = ast.parse((S / 'research.py').read_text(encoding='utf-8'))

    cache_block = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == 'cached'):
            cache_block = node
            break
    assert cache_block is not None, '找不到 `if cached:` 分支——缓存命中路径改名了？先看一眼'

    call_lines, ret_lines = [], []
    for stmt in cache_block.body:
        for sub in ast.walk(stmt):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id == '_report_relevance_spread'):
                call_lines.append(sub.lineno)
            elif isinstance(sub, ast.Return):
                ret_lines.append(sub.lineno)

    assert call_lines, '`if cached:` 分支里没有这个调用'
    assert ret_lines, '`if cached:` 分支里没有 return（结构变了？先看一眼再改测试）'
    assert min(call_lines) < min(ret_lines), (
        f'调用在行 {call_lines}、return 在行 {ret_lines}——'
        '写在 return 之后等于没写')

    # 全文件至少两处调用（另一条是新鲜检索路径）
    total = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == '_report_relevance_spread']
    assert len(total) >= 2, f'只找到 {len(total)} 处调用（行 {total}）'


def test_rel_note_used_by_markdown_output():
    """markdown 输出要真的用上它，否则又是一个"定义了没人调"的函数。"""
    src = (S / 'research.py').read_text(encoding='utf-8')
    assert src.count('_rel_note(') >= 2, '只有定义处，没有调用处'
    assert "'relevance'" in src and "'relevance_capped'" in src, 'CSV 表头没加这两列'
