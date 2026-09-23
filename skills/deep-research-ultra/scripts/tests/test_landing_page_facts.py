"""宣传页事实核对：页面上的每个数字都要能由代码或注册表推出来。

真实故障：页面曾写"30 个数据源""本机可用 20/32""v6.14"，都是手抄旧文案留下的。
其中"可用 N 个"这类数还根本不该印——它取决于此刻的网络（见 test_v6162）。
所以这里不比对快照，而是把页面声明与注册表实际值对撞。
"""

import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

REPO_ROOT = Path(__file__).resolve().parents[4]
PAGE = REPO_ROOT / 'index.html'

import pytest  # noqa: E402


@pytest.fixture(scope='module')
def html():
    assert PAGE.exists(), f'找不到宣传页 {PAGE}'
    return PAGE.read_text(encoding='utf-8')


def _registry():
    from research import build_registry
    return build_registry()


# ------------------------------------------------------------
# 数据源清单：数量与"需配置"标记
# ------------------------------------------------------------

def test_chip_count_matches_registry(html):
    chips = re.findall(r'<span class="chip([^"]*)">([^<]+)</span>', html)
    assert len(chips) == len(_registry().get_all()), \
        '页面上的源数量与注册表不一致'


def test_key_marked_chips_are_exactly_the_required_config_engines(html):
    """虚线框（chip key）＝真的需要配 key 才能用。判据与 --list 同源。"""
    from engines.base import missing_required_config
    chips = re.findall(r'<span class="chip([^"]*)">([^<]+)</span>', html)
    marked = {n.strip().lower() for cls, n in chips if 'key' in cls}
    import os
    saved = dict(os.environ)
    try:
        for k in ('TAVILY_API_KEY', 'FIRECRAWL_API_KEY', 'GITEE_TOKEN',
                  'CRAWL4AI_URL', 'CRAWL4AI_API_TOKEN', 'SEARXNG_URL'):
            os.environ.pop(k, None)
        need = {e.get_name() for e in _registry().get_all()
                if missing_required_config(e.metadata)}
    finally:
        os.environ.clear()
        os.environ.update(saved)
    # 页面用商品名（Tavily），注册表用引擎名（tavily）——按小写包含关系对齐
    assert marked, '一个 key 标记都没有，选择器可能失效了'
    for name in marked:
        assert any(name in n or n in name for n in need | {'crawl4ai', 'searxng'}), \
            f'页面把 {name} 标成需配置，注册表里它并不需要'
    assert len(marked) == len(need), f'页面标了 {len(marked)} 个，实际需要 {len(need)} 个'


def test_layer_totals_match_registry_and_sum_to_chip_count(html):
    chips = re.findall(r'<span class="chip[^"]*">[^<]+</span>', html)
    cnts = [int(x) for x in re.findall(r'<span class="cnt">(\d+) 个</span>', html)]
    assert len(cnts) == 4, f'四层计数没齐：{cnts}'
    assert sum(cnts) == len(chips), f'四层之和 {sum(cnts)} != 清单条数 {len(chips)}'
    import collections
    real = collections.Counter(e.get_layer() for e in _registry().get_all())
    assert cnts == [real[1], real[2], real[3], real[4]], \
        f'页面四层 {cnts} 与注册表 {[real[i] for i in (1,2,3,4)]} 不符'


# ------------------------------------------------------------
# 不许出现"取决于此刻网络"的静态数
# ------------------------------------------------------------

def test_page_does_not_print_a_live_availability_count(html):
    for pat in (r'\b\d+\s*/\s*32', r'当前可用', r'本机可用'):
        assert not re.search(pat, html), f'页面又在印实时可达类计数：{pat}'


# ------------------------------------------------------------
# 版本与测试数：必须与代码一致，且不留旧值
# ------------------------------------------------------------

def test_kernel_and_shell_versions_match_the_code(html):
    from research import skill_version
    import json
    shell = json.loads((REPO_ROOT / '.qoder-plugin' / 'plugin.json')
                       .read_text(encoding='utf-8'))['version']
    assert skill_version() in html, \
        f'页面没提当前内核版本 {skill_version()}（改了版本要同步页面）'
    assert shell in html, f'页面没提插件壳版本 {shell}'
    stale = re.findall(r'内核\s*(\d+\.\d+\.\d+)', html)
    assert stale and set(stale) <= {skill_version()}, \
        f'页面残留旧内核版本号 {set(stale) - {skill_version()}}'


def test_test_count_matches_what_is_on_disk(html):
    """页面写"N 项测试"就必须等于仓库里真的能收集到的用例数。"""
    m = re.search(r'<strong>(\d+)</strong><span>项测试', html)
    assert m, '页面上的测试数声明不见了'
    claimed = int(m.group(1))
    import subprocess
    out = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q', '--no-header',
         'tests', str(REPO_ROOT / 'tests'), '-p', 'no:cacheprovider'],
        cwd=SCRIPTS, capture_output=True).stdout.decode('utf-8', 'replace')
    got = re.findall(r'(\d+) tests? collected', out)
    assert got, f'收集用例失败：{out[-300:]}'
    assert claimed == sum(int(x) for x in got), \
        f'页面写 {claimed} 项，实际收集到 {sum(int(x) for x in got)} 项'


# ------------------------------------------------------------
# 链接与结构完整性
# ------------------------------------------------------------

def test_no_unbalanced_tags_or_dead_anchors(html):
    for t in ('div', 'section', 'p', 'span', 'a', 'h1', 'h2', 'h3', 'pre', 'button'):
        o = len(re.findall(r'<%s[\s>]' % t, html))
        c = len(re.findall(r'</%s>' % t, html))
        assert o == c, f'标签不闭合：{t} 开 {o} 闭 {c}'
    ids = set(re.findall(r'id="([^"]+)"', html))
    for h in re.findall(r'href="#([^"]+)"', html):
        assert h in ids, f'页内锚点 #{h} 没有对应元素'


def test_only_expected_external_hosts_are_linked(html):
    hosts = set(re.findall(r'href="https?://([^/"]+)', html))
    allowed = {'github.com', 'fonts.googleapis.com', 'fonts.gstatic.com'}
    assert hosts <= allowed, f'页面出现意外外链：{hosts - allowed}'


def test_install_commands_point_at_paths_that_exist(html):
    for rel in ('skills/deep-research-ultra/requirements.txt',
                'skills/deep-research-ultra/scripts/research.py'):
        assert rel in html, f'页面少了安装命令 {rel}'
        assert (REPO_ROOT / rel).exists(), f'页面让用户执行 {rel}，但仓库里没有这个路径'


def test_page_ends_cleanly(html):
    assert html.rstrip().endswith('</html>')
