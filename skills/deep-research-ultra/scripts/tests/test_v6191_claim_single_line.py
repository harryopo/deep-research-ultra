"""v6.19.1 回归：claim 文本里的换行会把"每条 claim 一行"的骨架切坏。

实测（2026-09-24 端到端实跑）：分片 JSON 里一条 claim 的正文含一个换行
（"…编号不应由写作者或模型手填：…另有 \\\\nocite{*} 之类手段…" 里的转义换行被原样带进账本），
skeleton.py 按"每条 claim 一行、行尾带编号与状态标注"渲染，于是这一条被切成两行：

    - ⚠️ 仅作线索：<前半句> [15]（状态 pending…      ← 带标注的前半行
      <后半句> [17]（状态 pending，未达 verified 判据）  ← 编号落在没有标注的第二行

后果有两层：读者看到的是一条断成两截的论断；发布门的行级归因（哪一行在说哪条 claim）
认不出第二行，把这条 pending claim 判成"正文引用了但没标 ⚠️"而硬拦——
Lead 无论怎么改正文都消不掉，因为缺陷在渲染侧。
所以换行必须在两处任一处被压掉：写进账本时（真值），与骨架渲染时（对既有账本兜底）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ledger as L            # noqa: E402
from skeleton import _one_line  # noqa: E402


def test_add_claim_collapses_internal_newlines(tmp_path):
    """写进账本的 claim 必须是单行：内部换行压成一个空格。"""
    led = L.ResearchLedger(str(tmp_path / 'ledger')).init()
    multiline = '编号不应由模型手填：unsrt 按引用次序生成' + chr(10) + 'ocite 之类手段可并排对比'
    led.add_claim(multiline, topic='引用对齐与一致性校验', claim_id='c-n-01')
    entry = [e for e in L._iter_entries(led.entries_path) if e.get('id') == 'c-n-01'][0]
    text = entry['text']
    assert chr(10) not in text and chr(13) not in text, 'claim 文本带了换行，骨架会把它切成两行: ' + repr(text)
    assert '生成 ocite' in text, '压换行时把两侧文字粘掉了'

def test_one_line_keeps_visible_text_intact():
    """压平本身不许丢字：首尾空白去掉，内部空白收成单个空格。"""
    assert _one_line('  甲\n\n  乙  \t 丙 ') == '甲 乙 丙'


def test_skeleton_renders_one_claim_per_line(tmp_path):
    """既有账本里已经带换行的 claim，渲染时也要兜底压平。"""
    import json
    from skeleton import build_skeleton
    led = L.ResearchLedger(str(tmp_path / 'ledger')).init()
    rows = [
        {'type': 'claim', 'id': 'c-n-02', 'text': '前半句\n后半句',
         'topic': '引用对齐与一致性校验', 'status': 'pending', 'confidence': 0.6},
        {'type': 'source', 'claim_id': 'c-n-02', 'url': 'https://tex.example/43276',
         'title': 'Unused bibliography', 'tier': 3},
    ]
    # 直接写文件，绕开写入侧闸门，模拟历史账本里已经躺着一条带换行的 claim
    led.entries_path.write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
    md = build_skeleton(str(tmp_path / 'ledger'), title='换行测试')
    hit = [ln for ln in md.split('\n') if '后半句' in ln]
    assert hit and '前半句' in hit[0], f'同一条 claim 被渲染成了两行: {hit}'
    assert '[1]' in hit[0], '编号没落在 claim 自己那一行上，行级归因会失效'
