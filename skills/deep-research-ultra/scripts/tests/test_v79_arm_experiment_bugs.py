"""v6.79：端到端实跑（抗幻觉行为层实验）暴露的两个 bug，各钉一组回归。

## 触发场景

用 skill 跑一次真实的"Google 是否推荐 ARES"核实验，在收尾阶段
（正是它该给结论的时候）连续踩到两个问题：

### bug 1｜GBK 终端下 `claim_support.py` 崩（v6.73 引入）

v6.73 给 `claim_support.py` 加了定性检查，文案里带 `⚠️`/`→`。但该脚本的
`__main__` 没有调 `console.force_utf8()`（`validate_report.py` 早就有），
在 Windows GBK 终端下 print 抛 UnicodeEncodeError——**恰好在吐出告警的那一刻崩**，
等于把它唯一的存在意义抵消了。文档明写"脚本自身强制 UTF-8 输出"，当时漏了。

### bug 2｜否定语境的全称词被误判成"范围扩大"（v6.73 引入）

诚实标注的句式天然带全称词："查不到…的**任何**来源""**没有任何**一条提到…"。
闸 3 之前的逻辑只看"句里有全称词 + claim 里没有"就判 scope_widened，于是三处诚实
表述全被误报。为什么必须修：诚实标注是铁律 8 的要求，Lead 每写一句"未证实"都被误报，
很快学会忽略这个工具——那时误报就不是误报，是把唯一的语义护栏关掉了。

**误报比漏报贵，在这里更贵。** 修法是加闸 4（识别否定语境），但**不能收单字「不」**
（太泛，"不如基线"里的「不」不是否定语境，会连带吃掉真阳性）。否定词表收
"没有/无/未/并非/查不到/无法/未能/不能/尚无/暂无/缺乏/找不到/零"这类。

## 两条都要求：真阳性必须仍然报

bug 2 的修法最容易出的错是"否定词放水"——把 `v6.74` 那批真的极性反转/范围扩大
也一并放过。所以本文件末尾用 `test_real_positives_still_fire` 把它们全钉一遍。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S))

import claim_support as cs  # noqa: E402


# ---------------------------------------------------------------------------
# bug 1：GBK 终端下不崩
# ---------------------------------------------------------------------------

def test_main_forces_utf8_before_printing():
    """__main__ 必须在 print 之前强制 UTF-8。

    判据不是"文件里出现过 force_utf8"，而是**它出现在 sys.exit(main()) 之前**——
    写在后面等于没写（这正是第一版的错法）。
    """
    src = (S / 'claim_support.py').read_text(encoding='utf-8')
    tail = src[src.rindex("if __name__ == '__main__':"):]
    assert 'force_utf8' in tail, 'claim_support.py 的 __main__ 没有 force_utf8'
    assert tail.index('force_utf8') < tail.index('sys.exit(main())'), \
        'force_utf8 写在 sys.exit(main()) 之后——那样根本赶不上 print'


def test_runs_under_gbk_terminal_without_crashing(tmp_path):
    """真跑一次：把 stdout 换成 GBK，看它还崩不崩。

    这条是 bug 1 的实证复现——CI 大概率是 UTF-8，不显式造 GBK 就不复现。
    """
    led = tmp_path / 'ledger'
    led.mkdir()
    for args in (
            ('add-claim', '--text', '该方法在所有场景下优于基线', '--id', 'c1', '--topic', 'T'),
            ('add-source', '--claim-id', 'c1', '--url', 'https://example.org/a',
             '--title', 'A', '--tier', '1', '--craap', '80'),
            ('add-claim', '--text', '该方法优于基线', '--id', 'c2', '--topic', 'T'),
            ('add-source', '--claim-id', 'c2', '--url', 'https://dl.acm.org/b',
             '--title', 'B', '--tier', '1', '--craap', '80')):
        subprocess.run([sys.executable, str(S / 'ledger.py'), args[0], '--ledger', str(led),
                        *args[1:]], capture_output=True)
    rep = tmp_path / 'r.md'
    rep.write_text(
        '# T\n\n## 一页拍板\n\n查不到该方法的**任何**佐证 [1]。\n\n'
        '## 执行摘要\n\n**没有任何**来源支持 [1]。\n\n'
        '## 调研方法\n\n单次 [1]。\n\n## 结论与建议\n\n未证实 [1]。\n\n'
        '## 来源\n\n[1] https://example.org/a\n[2] https://dl.acm.org/b\n',
        encoding='utf-8')

    env = dict(os.environ)
    env['PYTHONIOENCODING'] = ''          # 清掉，靠脚本自己 force
    env.pop('PYTHONIOENCODING', None)
    env['PYTHONUTF8'] = ''
    env.pop('PYTHONUTF8', None)
    r = subprocess.run(
        [sys.executable, '-X', 'utf8=0', str(S / 'claim_support.py'),
         '--report', str(rep), '--ledger', str(led)],
        capture_output=True, env=env, cwd=str(S))
    blob = (r.stdout + r.stderr).decode('utf-8', errors='replace')
    assert 'UnicodeEncodeError' not in blob, f'GBK 终端下又崩了：{blob[-260:]}'
    assert 'Traceback' not in blob, blob[-260:]


# ---------------------------------------------------------------------------
# bug 2：否定语境不是范围扩大
# ---------------------------------------------------------------------------

def test_negated_universal_is_not_scope_widening():
    """诚实标注句式不该被误报。"""
    for sent in (
            '查不到 Stanford ARES 被 Google 官方推荐为 RAG 评测标准这一说法的任何来源 [4]。',
            '没有任何一条提到 Google 背书 [11]。',
            '未能证实该方法在所有场景下都优于基线 [1]。',
            '缺乏说明它在任何环境都成立的证据 [2]。'):
        risks = cs.qualitative_risks(sent, 'ARES 是一篇 RAG 评测论文')
        kinds = {r['kind'] for r in risks}
        assert 'scope_widened' not in kinds, (
            f'否定语境被误判成范围扩大：{sent[:44]} → {risks}')


def test_positive_universal_still_flagged():
    """反向：真的范围扩大仍要报（闸 4 不能放水）。"""
    risks = cs.qualitative_risks(
        '该方法在所有场景下都优于基线 [1]。', '该方法在低延迟场景下优于基线')
    assert any(r['kind'] == 'scope_widened' for r in risks), risks


def test_negation_list_excludes_bare_bu():
    """否定词表刻意不收单字「不」——它太泛，会连带吃掉真阳性。"""
    assert '不' not in cs._NEGATION, '单字「不」会把「不如基线」这类真阳性误判为否定'


# ---------------------------------------------------------------------------
# 最关键：真阳性必须仍然全部报（bug 2 修法的回归网）
# ---------------------------------------------------------------------------

def test_real_positives_still_fire():
    """v6.74 那批真阳性，逐条重跑一遍——闸 4 不能把它们一并放过。"""
    cases = [
        # (报告句, claim 池, 该报的 kind)
        ('框架 A 的召回率低于框架 B [1]。', '框架 A 的召回率高于框架 B', 'polarity_flip'),
        ('开源框架 A 效果最差 [3]。', '开源框架 A 效果最好', 'polarity_flip'),
        ('该方法在所有场景下都优于基线 [2]。', '该方法在低延迟场景下优于基线', 'scope_widened'),
    ]
    for sent, pool, want in cases:
        risks = cs.qualitative_risks(sent, pool)
        assert any(r['kind'] == want for r in risks), f'{sent[:40]} 该报 {want}，实得 {risks}'


# ---------------------------------------------------------------------------
# bug 3（收尾时才暴露）：写坏的草稿脚本能把测试套件打红
# ---------------------------------------------------------------------------

def test_transport_scan_skips_dot_directories(tmp_path):
    """`.research/` 等点开头目录被 .gitignore 排除、不进发布包，不该被传输层扫描。

    这条不是洁癖：本轮真的踩了。写文档补丁脚本时中文字符引号提前闭合，
    `ast.parse` 抛 SyntaxError，于是 `test_no_module_bypasses_the_shared_transport`
    红了——而红的原因跟"传输层"一个字都不相干，排查方向直接被带偏（我第一反应是
    去查 claim_support 的改动）。

    判据是**双向**的：点开头目录里的坏文件放行，非点开头的坏文件仍须炸。
    只测放行那一半，等于给后人留一个"把所有目录都点开头"的后门。
    """
    sys.path.insert(0, str(S / 'tests'))
    import test_v6151_transport as tt

    scratch = S / '.research'
    scratch.mkdir(exist_ok=True)
    bad_hidden = scratch / '_v79_tmp_broken.py'
    bad_visible = S / '_v79_tmp_broken_visible.py'
    broken = "x = '未闭合字符串\n"
    try:
        # 只种点开头目录里的坏文件 → 扫描不该抛
        bad_hidden.write_text(broken, encoding='utf-8')
        tt._bare_http_calls()

        # 再种受管目录里的坏文件 → **必须**仍然抛（否则等于给后人留了
        # "把目录改名成点开头就能绕过传输层检查"的后门）
        bad_visible.write_text(broken, encoding='utf-8')
        try:
            tt._bare_http_calls()
            raised = False
        except SyntaxError:
            raised = True
        assert raised, '受管目录里的语法错误不再被扫到——扫描范围被放得过宽了'
    finally:
        for p in (bad_hidden, bad_visible):
            p.unlink(missing_ok=True)