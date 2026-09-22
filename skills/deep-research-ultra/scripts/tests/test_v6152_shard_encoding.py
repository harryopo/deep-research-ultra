"""v6.15.2 回归：子 Agent 分片的编码与路径错了必须点名报错，不能静默成功。

起因是 X-D6 那条"Windows GBK 会把中文 argv 打乱"的备忘。实测下来 **argv 是无损的**
（Git Bash 与 cmd.exe /c 两路、含全角引号/半角引号/换行/300 字长文本共 5 例，
落盘字节与原文全部一致），真正被打乱的是**文件通道**：Windows 上写文件的默认编码
是 GBK，而 `_load_shard` 用 `read_text(encoding='utf-8', errors='ignore')` 读它——
GBK 字节被两两拼成合法 UTF-8 序列，JSON 照样解析通过，于是：

    '该政策「支持」中小（企业）发展，2026 年补贴 3~5 万元'
      → merge 报「新增 claim 1 条」，落账文本 'ߡ֧֡Сҵչ2026 겹 3~5 Ԫ'

乱码当结论进账本、进报告，比丢掉更糟：它看起来是数据。

顺带收掉同一次实测撞上的两处静默 0：`--dir` 传成单个分片文件、`--dir` 路径打错，
两者都 rc=0 且打「合并完成：新增 claim 0 条」，Lead 无从分辨"子 Agent 真没产出"
还是"我自己把路径写错了"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import ResearchLedger, _main  # noqa: E402

CLAIM = '该政策「支持」中小（企业）发展，2026 年补贴 3~5 万元'


def _shard(base: Path, name: str, data, *, encoding='utf-8', bom=False) -> Path:
    src = base / 'sub'
    src.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(data, ensure_ascii=False)
    p = src / name
    payload = txt.encode(encoding)
    p.write_bytes(b'\xef\xbb\xbf' + payload if bom else payload)
    return src


def _payload():
    return {'claims': [{'id': 'c-1', 'text': CLAIM, 'topic': '补贴'}]}


def _texts(L):
    return [c['text'] for c in L.claims()]


# --------------------------------------------------------------------------
# 编码：错了要点名，不能翻成乱码入库
# --------------------------------------------------------------------------
def test_gbk_shard_is_refused_by_name_not_transliterated(tmp_path, capsys):
    src = _shard(tmp_path, 'a.json', _payload(), encoding='gbk')
    L = ResearchLedger(str(tmp_path / 'led')).init()

    added, _ = L.merge(str(src))

    err = capsys.readouterr().err
    assert added == 0
    assert _texts(L) == []
    assert 'a.json' in err
    assert 'UTF-8' in err


def test_gbk_shard_refusal_names_the_actual_encoding(tmp_path, capsys):
    src = _shard(tmp_path, 'a.json', _payload(), encoding='gbk')
    L = ResearchLedger(str(tmp_path / 'led')).init()
    L.merge(str(src))
    assert 'GBK' in capsys.readouterr().err      # 指明"这份是 GBK 存的"，别让人猜


def test_utf8_shard_with_bom_still_merges_byte_identical(tmp_path, capsys):
    """正向对照：Windows 宿主常写 BOM，拒收非 UTF-8 不该顺手拒掉 BOM。"""
    src = _shard(tmp_path, 'a.json', _payload(), bom=True)
    L = ResearchLedger(str(tmp_path / 'led')).init()

    added, _ = L.merge(str(src))

    assert added == 1
    assert _texts(L) == [CLAIM]
    assert capsys.readouterr().err == ''


# --------------------------------------------------------------------------
# 路径：传文件要能收，路径错了要报错，空目录要说明"没找到分片"
# --------------------------------------------------------------------------
def test_merge_accepts_a_single_shard_file(tmp_path):
    src = _shard(tmp_path, 'a.json', _payload())
    L = ResearchLedger(str(tmp_path / 'led')).init()

    added, _ = L.merge(str(src / 'a.json'))

    assert added == 1
    assert _texts(L) == [CLAIM]


def test_merge_of_missing_path_raises_instead_of_reporting_zero(tmp_path):
    L = ResearchLedger(str(tmp_path / 'led')).init()
    with pytest.raises(FileNotFoundError) as e:
        L.merge(str(tmp_path / 'typo'))
    assert 'typo' in str(e.value)


def test_cli_merge_bad_dir_exits_nonzero(tmp_path, capsys):
    L = ResearchLedger(str(tmp_path / 'led')).init()
    L.init()
    rc = _main(['merge', '--session', str(tmp_path / 'led'), '--dir',
                str(tmp_path / 'typo')])
    out = capsys.readouterr()
    assert rc == 2
    assert '合并完成' not in out.out
    assert 'typo' in out.err


def test_cli_merge_empty_dir_says_no_shard_found(tmp_path, capsys):
    (tmp_path / 'sub').mkdir()
    ResearchLedger(str(tmp_path / 'led')).init()
    rc = _main(['merge', '--session', str(tmp_path / 'led'), '--dir',
                str(tmp_path / 'sub')])
    out = capsys.readouterr()
    assert rc == 0
    assert '没有' in out.err and '.json' in out.err
    assert '新增 claim 0 条' not in out.out
