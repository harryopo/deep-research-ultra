"""v6.52 回归：四六级实跑（2026-10-03/04）暴露的五个工程问题的收口。

实跑撞到的原形（每个测试对应一个）：
1. raw 存成 .json 不进对账语料——verify_quotes 只收 *.txt/html/xml/md，
   与 SKILL.md「HTML/纯文本都行」的承诺不一致，Anki 仓库 claim 的引文因此 MISS。
2. DOI 落地页后缀不归一——frontiers 落地页（…/10.3389/x/full）与 Crossref API
   （works/10.3389/x）被判成两个制品，第一轮档 B 全拒，换 URL 形态才绕过。
3. 引文内嵌省略号 MISS 后无诊断——Lead 只能逐个 grep raw 找差在哪。
4. 骨架把「引仓库当证据」误判成选型调研——Lead 被迫手工改声明行。
5. 账本修复后必须重生成骨架，Lead 手写的六段全部要重贴——成本真实发生。

另含 SKILL.md 派单模板的引文纪律（『』内禁省略号、术语用〔〕、上游粘连照抄）的文档钉。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================
# 1. 对账语料收 .json（API 视图存档是合法 raw 形态）
# ============================================================

def test_quote_hits_json_raw(tmp_path):
    from verify_quotes import check_quotes

    led = tmp_path / 'ledger'
    led.mkdir()
    (led / 'ledger.jsonl').write_text(
        '{"type":"claim","id":"c-1","text":"官方描述自称『Anki is a smart spaced '
        'repetition flashcard program』","topic":"t","status":"pending"}\n',
        encoding='utf-8')
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'api.json').write_text(
        '{"description":"Anki is a smart spaced repetition flashcard program"}\n',
        encoding='utf-8')
    res = check_quotes(str(led), str(raw))
    assert res['error'] is None
    assert res['corpus_files'] == 1, '.json 存档必须进对账语料'
    assert res['misses'] == []


def test_quote_miss_in_json_still_detected(tmp_path):
    """收 .json 不能放水：命中不了照样 MISS。"""
    from verify_quotes import check_quotes

    led = tmp_path / 'ledger'
    led.mkdir()
    (led / 'ledger.jsonl').write_text(
        '{"type":"claim","id":"c-1","text":"『this exact sentence is archived here』",'
        '"topic":"t","status":"pending"}\n', encoding='utf-8')
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'api.json').write_text('{"description":"something else entirely"}\n',
                                  encoding='utf-8')
    res = check_quotes(str(led), str(raw))
    assert len(res['misses']) == 1


# ============================================================
# 2. DOI 落地页后缀归一（/full 等 = 同一篇作品）
# ============================================================

def test_doi_landing_suffix_same_artifact():
    from ledger import _artifact_key

    publisher = 'https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2020.602451/full'
    via_doi = 'https://doi.org/10.3389/feduc.2020.602451/full'
    bare = 'https://doi.org/10.3389/feduc.2020.602451'
    crossref = 'https://api.crossref.org/works/10.3389/feduc.2020.602451'
    keys = {_artifact_key(u) for u in (publisher, via_doi, bare, crossref)}
    assert len(keys) == 1, f'四种入口应归一成同一制品，实际 {keys}'


def test_doi_suffix_strip_does_not_eat_real_suffixes():
    from ledger import _artifact_key

    # 真实 DOI 后缀本身以这些词结尾的形状不许被剥掉
    ch1 = _artifact_key('https://doi.org/10.1002/0470841559.ch1')
    assert ch1 == 'doi:10.1002/0470841559.ch1'
    slashy = _artifact_key('https://doi.org/10.1093/acprof:oso/9780199566165.001.0001')
    assert slashy == 'doi:10.1093/acprof:oso/9780199566165.001.0001'
    # 不同 DOI 仍是不同制品
    a = _artifact_key('https://doi.org/10.3389/feduc.2020.602451')
    b = _artifact_key('https://doi.org/10.3389/fpsyg.2024.1428732')
    assert a != b


def test_verify_primary_accepts_crossref_against_publisher_suffix_source(tmp_path):
    """实跑原形回放：来源是出版方落地页（…/full），反查走 Crossref API——必须通过。"""
    from ledger import ResearchLedger

    led = ResearchLedger(str(tmp_path / 'l')).init()
    c = led.add_claim('某论文原文说 X（逐字引文够长所以这句是真实引文的样子）',
                      't', 'pending', 'general', 0.6)
    led.add_source(c['id'],
                   'https://www.frontiersin.org/journals/education/articles/'
                   '10.3389/feduc.2020.602451/full', tier=1)
    changed = led.verify_primary(
        [c['id']], 'https://api.crossref.org/works/10.3389/feduc.2020.602451',
        check_title='Crossref record', method='cross_channel')
    assert changed == 1, '落地页后缀归一后，Crossref 反查必须通过'


# ============================================================
# 3. MISS 诊断：内嵌省略号 → 分段报告各段是否命中
# ============================================================

def test_miss_with_ellipsis_reports_segment_hits(tmp_path):
    import json

    from verify_quotes import check_quotes

    led = tmp_path / 'ledger'
    led.mkdir()
    claim = {'type': 'claim', 'id': 'c-1',
             'text': '报告说『first part of the sentence and … second part continued here』'
                     '（省略号是摘抄时加的）', 'topic': 't', 'status': 'pending'}
    (led / 'ledger.jsonl').write_text(json.dumps(claim, ensure_ascii=False) + '\n',
                                      encoding='utf-8')
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'page.txt').write_text(
        'context first part of the sentence and then something else happened '
        'between second part continued here end\n', encoding='utf-8')
    res = check_quotes(str(led), str(raw))
    assert len(res['misses']) == 1, '整段含省略号当然对不上原文'
    m = res['misses'][0]
    assert m.get('segments'), 'MISS 必须带省略号分段诊断'
    hits = [s for s in m['segments'] if s.get('hit')]
    assert len(hits) == 2, f'两段各自都该命中 raw，实际 {m["segments"]}'


# ============================================================
# 4. 六维门：仓库只在证据节被引 → 自动豁免（未声明时）
# ============================================================

def _repo_report(link_line: str) -> str:
    return f'''# 报告

## 一页拍板
直接结论：选 A [1]。

## 执行摘要
摘要给出核心结论 [1]。

## 调研范围与方法
方法说明 [1]。

## 结论与建议
结论与落地步骤 [1]。

## 某主题
- 证据行：{link_line}

## 来源

| 编号 | Tier | 标题 | URL |
|------|------|------|-----|
| [1] | 2 | R | https://example.org/a |
| [2] | 1 | Repo | https://github.com/a/b |

---
> 引用编号与来源登记表由 skeleton.py 生成，不可手改。
'''


def _validate(md, tmp_path):
    from ledger import ResearchLedger
    from validate_report import validate_report

    led = ResearchLedger(str(tmp_path / 'l')).init()
    c = led.add_claim('结论 A 的账本依据足够长可以当一行引用', 't', 'verified',
                      'general', 0.9)
    led.add_source(c['id'], 'https://example.org/a', tier=2)
    led.add_source(c['id'], 'https://github.com/a/b', tier=1)
    return validate_report(md, ledger=led)


def test_six_dims_auto_exempt_for_evidence_only_repo_citation(tmp_path):
    r = _validate(_repo_report('Anki 仓库 https://github.com/a/b 活跃维护。'), tmp_path)
    assert r.stats.get('opensource_gate') == 'exempt-evidence-only', r.stats
    assert not any('六维' in i for i in r.issues)


def test_six_dims_fire_when_repo_in_decision_section(tmp_path):
    md = _repo_report('占位').replace(
        '结论与落地步骤 [1]。', '结论：推荐用 https://github.com/a/b。')
    r = _validate(md, tmp_path)
    assert r.stats.get('opensource_gate') == 'six-dims'
    assert any('六维' in i for i in r.issues), '拍板/结论节推荐仓库＝选型形态，六维照旧'


def test_six_dims_fire_when_repo_cited_in_bluf_via_index(tmp_path):
    md = _repo_report('占位').replace(
        '直接结论：选 A [1]。', '直接结论：选 Anki [2]。')
    r = _validate(md, tmp_path)
    assert r.stats.get('opensource_gate') == 'six-dims', '拍板节用 [N] 引仓库来源也算选型'


# ============================================================
# 5. 骨架 --merge-from：账本变了重生成，Lead 段落不重贴
# ============================================================

def _tiny_ledger(tmp_path):
    from ledger import ResearchLedger
    led = ResearchLedger(str(tmp_path / 'l')).init()
    c1 = led.add_claim('间隔重复对词汇学习有效的实证证据足够充分', '方法', 'verified',
                       'general', 0.9)
    led.add_source(c1['id'], 'https://doi.org/10.1000/aaa', tier=1)
    c2 = led.add_claim('学习风格匹配假说缺乏实证支持的反方证据成立', '迷思', 'conflict',
                       'general', 0.6)
    led.add_source(c2['id'], 'https://example.org/a', tier=2)
    return led, c1, c2


def test_skeleton_merge_from_preserves_lead_sections(tmp_path):
    from skeleton import build_skeleton

    led, c1, c2 = _tiny_ledger(tmp_path)
    v1 = build_skeleton(str(tmp_path / 'l'), title='T')
    old = tmp_path / 'old.md'
    old.write_text(v1, encoding='utf-8')

    # Lead 写掉全部待写段（含一条裁决）
    filled = v1
    filled = filled.replace(
        '【待写】 给"要拍板的人"用', '直接结论：用间隔重复，别按学习风格组织教学。')
    filled = filled.replace(
        '【待写】 3-5 句给出最关键结论', '摘要：间隔重复有证据，学习风格没有。')
    filled = filled.replace(
        '【待写】 写清两方证据、分歧根源与本报告的取舍',
        '  **裁决**：两说并取——操作结论一致，保留冲突标签。')
    filled = filled.replace(
        '【待写】 写检索窗口、数据源分层', '方法：本轮 2 个维度。')
    filled = filled.replace(
        '【待写】 结论、风险、落地步骤', '结论：证据支持间隔重复。')
    filled = filled.replace(
        '【待写】 分析性段落：本维度的关键发现', '分析：本维度发现关键证据。')
    assert '【待写】' not in filled
    old.write_text(filled, encoding='utf-8')

    # 账本变化：冲突条目升级 verified → 骨架必须重生成
    led.set_status([c2['id']], 'verified', note='交叉验证')
    v2 = build_skeleton(str(tmp_path / 'l'), title='T', merge_from=str(old))

    assert '直接结论：用间隔重复' in v2, '一页拍板段落必须保留'
    assert '摘要：间隔重复有证据' in v2, '执行摘要必须保留'
    assert '方法：本轮 2 个维度' in v2, '调研方法必须保留'
    assert '结论：证据支持间隔重复' in v2, '结论与建议必须保留'
    assert '【待写】' not in v2, '裁决段落保留后不应残留待写'
    assert '⚠️ 来源冲突' not in v2, 'claim 行要按账本新状态渲染'
    assert 'verified 2' in v2, '保留段里的账本事实行要刷新成新计数'


def test_skeleton_merge_skips_unfinished_sections(tmp_path):
    """旧报告里没写完的段（仍带【待写】）不许被保留——占位内容不出门。"""
    from skeleton import build_skeleton

    _tiny_ledger(tmp_path)
    v1 = build_skeleton(str(tmp_path / 'l'), title='T')
    old = tmp_path / 'old.md'
    old.write_text(v1, encoding='utf-8')  # 全是待写，等于 Lead 什么都没写
    v2 = build_skeleton(str(tmp_path / 'l'), title='T', merge_from=str(old))
    # v6.58：merge_from 不重复生成分析插槽（Lead 分析已在保留段落中）
    # v1 有 7 处（含 2 个分析 slot），v2 只有 5 处核心段落的待写
    assert v2.count('【待写】') == 5, \
        f'merge_from 应跳过分析插槽，核心段落待写应保留：实际 {v2.count("【待写】")}'


# ============================================================
# 6. SKILL.md 派单模板引文纪律（文档钉）
# ============================================================

def test_skill_md_template_bans_ellipsis_inside_verbatim_quotes():
    skill = (Path(__file__).resolve().parents[2] / 'SKILL.md').read_text(encoding='utf-8')
    assert '『』内不得含省略号' in skill, '派单模板必须有省略号禁令'
    assert '照原样抄' in skill, '上游排版粘连必须照抄，不许顺手修正'


def test_skill_md_template_terms_use_own_brackets():
    skill = (Path(__file__).resolve().parents[2] / 'SKILL.md').read_text(encoding='utf-8')
    assert '术语与概念强调一律用〔〕' in skill, '术语强调不得占用逐字引号'
