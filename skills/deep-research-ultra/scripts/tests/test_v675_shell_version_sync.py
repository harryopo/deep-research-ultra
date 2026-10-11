"""v6.75：插件壳版本号必须四处一致（加这个是因为这次就漏了）。

## 为什么加这个测试

升 7.0.0 → 7.1.0 时，`README.md` 与 `plugin.json` 我改了，**`install.py` 漏了**——
而那处是**代码里 mkdir 的插件缓存路径**。用户照脚本提示建目录，会把新代码装到
`cache/local/deep-research-ultra/7.0.0/` 里，然后宿主读的却是 7.1.0 的目录，
结果是"改了没生效"。

同一件事在四个地方各写了一遍版本号，靠记性同步就是会漏——这与 v6.71 那次
"HANDOFF 两处体量数字只同步了一处、陈旧 6 个版本"是同一类毛病。所以让测试读。

## 只管当前值，不管历史

`docs/plans/`、`docs/specs/`、`docs/dev/CHANGELOG-archive.md`、`.ai/HANDOFF.md`
里的 7.0.0 是历史记录（"2026-09-20 那轮把插件壳定成 7.0.0"），改了就是改写历史，
所以本测试只认下面这四个**会被用户看到或被代码执行**的位置。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PLUGIN_JSON = REPO / '.qoder-plugin' / 'plugin.json'
README = REPO / 'README.md'
INDEX = REPO / 'index.html'
INSTALL = REPO / 'skills' / 'deep-research-ultra' / 'scripts' / 'install.py'


def _shell_version() -> str:
    return json.loads(PLUGIN_JSON.read_text(encoding='utf-8'))['version']


def test_install_py_path_matches_plugin_json():
    """**这一条是本文件存在的理由**——7.0.0→7.1.0 时就是这里漏的。

    它不是文案，是 `install.py` 提示用户 mkdir 的实际路径。漏了的后果是
    "装了但没生效"：代码落在 7.0.0 目录，宿主读 7.1.0 目录。
    """
    v = _shell_version()
    txt = INSTALL.read_text(encoding='utf-8')
    found = re.findall(r'cache/local/deep-research-ultra/([\d.]+)', txt)
    assert found, 'install.py 里找不到插件缓存路径——它变了形状？先看一眼再改测试'
    for got in found:
        assert got == v, (
            f'install.py 提示的缓存路径是 {got}，plugin.json 是 {v}——'
            '用户会照着装到旧目录去，然后"改了没生效"')


def test_readme_package_name_matches():
    v = _shell_version()
    txt = README.read_text(encoding='utf-8')
    names = set(re.findall(r'deep-research-ultra-v([\d.]+)\.zip', txt))
    assert names == {v}, f'README 里的包名版本 {names} ≠ plugin.json {v}'
    paths = set(re.findall(r'deep-research-ultra/([\d.]+)', txt))
    assert paths == {v}, f'README 里的插件缓存路径 {paths} ≠ plugin.json {v}'


def test_landing_page_shell_version_matches():
    v = _shell_version()
    txt = INDEX.read_text(encoding='utf-8')
    m = re.search(r'插件壳版本</span><b>([\d.]+)</b>', txt)
    assert m, 'index.html 里找不到「插件壳版本」那块'
    assert m.group(1) == v, f'宣传页写 {m.group(1)}，plugin.json 是 {v}'
    m2 = re.search(r'内核 ([\d.]+) / 插件壳 ([\d.]+)', txt)
    assert m2 and m2.group(2) == v, f'页脚插件壳 {m2.group(2) if m2 else "?"} ≠ {v}'


def test_no_stale_shell_version_in_live_surfaces():
    """当前值面上不该有别的插件壳版本号残留。

    历史文档（docs/plans、docs/specs、CHANGELOG-archive、HANDOFF）里出现 7.0.0
    是正常的——那记录的是当时的事。所以只扫这四个文件，不扫整个仓库。
    """
    v = _shell_version()
    stale = set()
    for p in (README, INDEX, INSTALL):
        txt = p.read_text(encoding='utf-8')
        for cand in re.findall(r'(?<![\d.])(7\.\d+\.\d+)(?![\d.])', txt):
            if cand != v:
                stale.add(f'{p.name}: {cand}')
    # README 里的代理端口 127.0.0.1:7890 不匹配这个模式，不会误伤
    assert not stale, f'当前值面上还有别的插件壳版本号：{sorted(stale)}'


def test_release_notes_agrees_with_the_shipped_versions():
    """dist/release-notes.md 不在版本控制内，最容易忘了跟着改。"""
    v = _shell_version()
    rn = REPO / 'dist' / 'release-notes.md'
    if not rn.exists():
        return                      # 没打过包就不检查
    txt = rn.read_text(encoding='utf-8')
    m = re.search(r'内核 ([\d.]+) / 插件壳 ([\d.]+)', txt)
    assert m, 'release-notes 首行没写内核/插件壳版本'
    assert m.group(2) == v, f'release-notes 写插件壳 {m.group(2)}，plugin.json 是 {v}'
    sk = REPO / 'skills' / 'deep-research-ultra' / 'SKILL.md'
    km = re.search(r'version: ([\d.]+)', sk.read_text(encoding='utf-8'))
    assert km and m.group(1) == km.group(1), (
        f'release-notes 写内核 {m.group(1)}，SKILL.md 是 {km.group(1) if km else "?"}')