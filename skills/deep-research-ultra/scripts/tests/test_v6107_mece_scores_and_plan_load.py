# -*- coding: utf-8 -*-
"""v6.107：MECE 校验的两个分数 + 计划读回 —— 三处「看起来有、实际空着/坏的」。

## 三个缺陷

1. **overlap_score 是写死的 0.0** —— 它**永远**说「无重叠」，
   而同一份输出里的 `issues` 却在报真实重叠。**同一份输出自相矛盾**。
2. **coverage_score 名不副实** —— 叫「覆盖度」，算的却是「叶子有没有假设」，
   而 `suggestions` 说的是另一件事（子问题数量 3-7）。规格（dr-023）要求
   「覆盖不全时 coverage_score < 1.0 并给出 suggestions」——旧实现里两者无关。
3. **`ResearchPlan.load()` 读回来的计划是坏的** —— `from_dict` 只还原顶层，
   嵌套的 `children` 仍是 dict，任何遍历都 `AttributeError`。
   旧测试只断言 `loaded.topic`，没碰树，所以一直没露头。

## 这份测试盯住什么

- 有重叠 → overlap_score > 0 且与 issues 一致（不许再自相矛盾）；
- 覆盖不全 → coverage_score < 1.0 **且** suggestions 非空（两者同一件事）；
- 干净树 → overlap 0、coverage 1、is_mece True（三者互不矛盾）；
- 计划读回后**能遍历**（这条是最容易漏的：只断言 topic 等于没测）。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

S = Path(__file__).resolve().parents[1]
if str(S) not in sys.path:
    sys.path.insert(0, str(S))

from plan import IssueTree, ResearchPlan  # noqa: E402


def _overlapping():
    t = IssueTree()
    root = t.add_root('向量数据库选型', hypothesis='H0', data_sources=['arxiv'])
    t.add_child(root, '性能对比', hypothesis='H1', data_sources=['arxiv'],
                keywords=['性能', '吞吐', '延迟'])
    t.add_child(root, '性能基准', hypothesis='H2', data_sources=['arxiv'],
                keywords=['性能', '吞吐', 'qps'])
    return t


def _narrow():
    t = IssueTree()
    root = t.add_root('根', hypothesis='H0', data_sources=['arxiv'])
    t.add_child(root, '甲', hypothesis='H1', data_sources=['arxiv'],
                keywords=['a', 'b', 'c'])
    t.add_child(root, '乙', hypothesis='H2', data_sources=['arxiv'],
                keywords=['d', 'e', 'f'])
    return t


def _clean():
    t = IssueTree()
    root = t.add_root('根', hypothesis='H0', data_sources=['arxiv'])
    for i, kw in enumerate([['a', 'b', 'c'], ['d', 'e', 'f'], ['g', 'h', 'i']]):
        t.add_child(root, '子%d' % i, hypothesis='H%d' % i,
                    data_sources=['github'], keywords=kw)
    return t


# ============================================================ 两个分数


def test_overlap_score_agrees_with_issues():
    """有重叠 → overlap_score > 0（旧实现恒为 0.0，与 issues 自相矛盾）。"""
    v = _overlapping().validate_mece()
    assert any('关键词重叠' in i for i in v['issues']), "issues 没说有重叠"
    assert v['overlap_score'] > 0, (
        "issues 报了重叠，overlap_score 却是 %r —— 同一份输出自相矛盾"
        % v['overlap_score'])
    assert v['overlap_score'] < 1.0


def test_coverage_score_and_suggestions_are_the_same_thing():
    """覆盖不全 → coverage_score < 1.0 **且** suggestions 非空。"""
    v = _narrow().validate_mece()
    assert v['coverage_score'] < 1.0, (
        "子问题只有 2 个（未穷尽），coverage_score 却是 %r —— 它和 suggestions 说的不是一件事"
        % v['coverage_score'])
    assert v['suggestions']


def test_clean_tree_scores_do_not_contradict_each_other():
    """干净的树 → overlap 0、coverage 1、is_mece True、无 issues/suggestions。"""
    v = _clean().validate_mece()
    assert v['overlap_score'] == 0.0
    assert v['coverage_score'] == 1.0
    assert v['is_mece'] is True
    assert not v['issues']
    assert not v['suggestions']


# ============================================================ 计划读回


def test_loaded_plan_can_be_traversed():
    """读回的计划**能遍历**（旧实现：children 仍是 dict → AttributeError）。"""
    t = IssueTree()
    root = t.add_root('主题', hypothesis='H0', data_sources=['arxiv'])
    mid = t.add_child(root, '子问题', hypothesis='H1', data_sources=['github'])
    t.add_child(mid, '孙问题', hypothesis='H2', data_sources=['arxiv'])
    p = ResearchPlan(topic='主题', issue_tree=[root])
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / 'research_plan.json')
        p.save(path)
        back = ResearchPlan.load(path)
        all_q = back.get_all_questions()
        leaves = back.get_leaf_questions()
    assert len(all_q) == 3, "读回后遍历不到 3 个节点：%r" % len(all_q)
    assert len(leaves) == 1
    assert all_q[0].children, "子问题的 children 读回来是空的"


def test_loaded_children_are_objects_not_dicts():
    """读回后的子问题要是 SubQuestion 对象（不是 dict）。"""
    t = IssueTree()
    root = t.add_root('主题', hypothesis='H0', data_sources=['arxiv'])
    t.add_child(root, '子问题', hypothesis='H1', data_sources=['github'])
    p = ResearchPlan(topic='主题', issue_tree=[root])
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / 'research_plan.json')
        p.save(path)
        back = ResearchPlan.load(path)
        child = back.issue_tree[0].children[0]
    assert isinstance(child, __import__('plan').SubQuestion)


# ============================================================ 复算入口


def test_mece_analysis_check_passes():
    """v6.107 的数字要能被复算（过程门会调它）。"""
    import subprocess
    r = subprocess.run(
        [sys.executable, str(S / 'analysis' / 'mece.py'), '--check'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=900)
    assert r.returncode == 0, "mece --check 没过：\n%s\n%s" % (
        r.stdout[-600:], r.stderr[-400:])
    assert '与 CHANGELOG v6.107 一致' in (r.stdout or '')
