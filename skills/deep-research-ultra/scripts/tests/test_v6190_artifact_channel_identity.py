"""v6.19.0 回归：档 B 的"同一制品"判据把三种真实反查通道判成了不同制品。

实测（2026-09-24，端到端实跑「AI 编码 Agent 的证据溯源」，93 条 claim）：
63 条单源 claim 里 33 条按文档说法"有第二通道可反查"，子研究员**真把内容取回来逐字
比对过、30 条判 PASS**，结果 Lead 跑 verify-primary 时 17 条被 `_artifact_key` 拒掉。
三条被拒的理由各暴露一类判据缺陷：

1. 仓库根 ≠ 仓库的 README。来源登记成 `https://github.com/o/r`（key 尾部路径为空），
   反查打在 `https://api.github.com/repos/o/r/readme`（key 尾部 `readme`）→ 判成不同制品。
   而 GitHub 打开仓库根页渲染的就是 README，这两个 URL 是同一份内容的两个入口，
   恰是文档让 Lead 走的那条通道（"blob 页 → raw / REST contents"）。
2. DOI 家族全灭。来源是 `https://doi.org/10.xxxx`，OpenAlex 记录
   （`api.openalex.org/works/https://doi.org/10.xxxx`）与 Semantic Scholar 记录
   （`graph/v1/paper/DOI:10.xxxx`）解析出的都是**同一篇作品**，key 却是三个不同域。
   单源 claim 里 21 条是 DOI 型——按现判据一条都升不上去。
   （本次另派子研究员实测：8 条样本里 OpenAlex 4/4 命中并带回题录+摘要，
   Wayback 在本机 0/4 且 TCP 不通，所以放行 OpenAlex/S2 而不引入存档快照判据。）
3. 换行符混进 URL 就变"另一个制品"。Windows 上从 CRLF 文本里读出的 URL 常带尾随 `\\r`，
   `readme\\r` 与 `readme` 判成两个制品，报错信息里那个 `\r` 还看不见，
   Lead 只能猜。argv 传参是本项目文档推荐用法，这条路径必须有归一。

拒收本身是对的（防止拿无关制品自批），错在把**同一制品的官方第二入口**也判成无关。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import _artifact_key  # noqa: E402


# ---------------------------------------------------------------- 1 GitHub README 家族
def test_repo_root_and_readme_are_one_artifact():
    """仓库根页、REST /readme、blob README.md、raw 字节流＝同一制品。"""
    root = 'https://github.com/chrisyangsong/citegate'
    rest = 'https://api.github.com/repos/chrisyangsong/citegate/readme'
    blob = 'https://github.com/chrisyangsong/citegate/blob/HEAD/README.md'
    raw = 'https://raw.githubusercontent.com/chrisyangsong/citegate/HEAD/README.md'
    keys = {_artifact_key(u) for u in (root, rest, blob, raw)}
    assert len(keys) == 1, f'同一仓库的 README 四个入口被判成 {len(keys)} 个制品: {keys}'


def test_other_file_in_same_repo_is_still_a_different_artifact():
    """同仓库的另一个文件仍是不同制品——放行 README 不许顺手放行整个仓库。"""
    readme = 'https://api.github.com/repos/chrisyangsong/citegate/readme'
    changelog = 'https://github.com/chrisyangsong/citegate/blob/HEAD/CHANGELOG.md'
    other_repo = 'https://github.com/chrisyangsong/other'
    assert _artifact_key(readme) != _artifact_key(changelog), \
        'README 与 CHANGELOG 判成了同一个制品'
    assert _artifact_key(readme) != _artifact_key(other_repo), \
        '不同仓库判成了同一个制品'


def test_named_branch_readme_still_differs_from_head():
    """具名分支不参与归一：分支差异本身可能就是结论。"""
    head = 'https://api.github.com/repos/chrisyangsong/citegate/readme'
    v1 = 'https://github.com/chrisyangsong/citegate/blob/v1.0/README.md'
    assert _artifact_key(head) != _artifact_key(v1), \
        'v1.0 分支的 README 与默认分支判成了同一个制品'


# ---------------------------------------------------------------- 2 DOI 家族
DOI = '10.1007/s11192-013-1089-2'


def test_doi_and_bibliographic_records_are_one_artifact():
    """doi.org 解析页、OpenAlex 记录、S2 记录＝同一篇作品的三个官方入口。"""
    keys = {
        _artifact_key(f'https://doi.org/{DOI}'),
        _artifact_key(f'https://api.openalex.org/works/https://doi.org/{DOI}'),
        _artifact_key(f'https://api.semanticscholar.org/graph/v1/paper/DOI:{DOI}'),
    }
    assert len(keys) == 1, f'同一篇论文的 DOI 与书目记录被判成 {len(keys)} 个制品: {keys}'


def test_different_dois_are_different_artifacts():
    """归一只到"同一个 DOI"为止，不许把两篇论文并成一个制品。"""
    a = _artifact_key(f'https://doi.org/{DOI}')
    b = _artifact_key('https://api.openalex.org/works/https://doi.org/10.1162/qss_a_00112')
    assert a != b, '两个不同 DOI 判成了同一个制品'


def test_non_doi_openalex_work_id_is_not_merged_into_doi_key():
    """OpenAlex 自己的 work id（W438…）不含 DOI，不许误挂到 DOI 家族上。"""
    a = _artifact_key(f'https://doi.org/{DOI}')
    b = _artifact_key('https://api.openalex.org/works/W4386510404')
    assert a != b, '无 DOI 的 OpenAlex work id 被误归一进 DOI 家族'


# ---------------------------------------------------------------- 3 URL 里的控制字符
def test_artifact_key_ignores_surrounding_whitespace_and_cr():
    """CRLF 文本里读出的 URL 带尾随 \\r，不许因此变成另一个制品。"""
    clean = 'https://github.com/chrisyangsong/citegate/readme'
    for dirty in (clean + '\r', clean + '\r\n', '  ' + clean + ' \t'):
        assert _artifact_key(dirty) == _artifact_key(clean), \
            f'URL 尾部混入空白/回车被判成另一个制品: {dirty!r}'


def test_source_registered_with_cr_is_still_refutable_by_clean_url(tmp_path):
    """端到端：来源带 \r 登记、反查给干净 URL，仍算打在同一个制品上。"""
    from ledger import ResearchLedger
    led = ResearchLedger(str(tmp_path / 'ledger')).init()
    led.add_claim('citegate 把引用校验装进了仓库自己的钩子里',
                  topic='引用对齐与一致性校验', claim_id='c-x-01')
    led.add_source('c-x-01', 'https://github.com/chrisyangsong/citegate\r',
                   title='citegate')
    assert led.verify_primary(['c-x-01'],
                              'https://api.github.com/repos/chrisyangsong/citegate/readme',
                              method='cross_channel') == 1, \
        '尾随 \\r 让一次真实反查被误拒'


# ------------------------------------------------- 4 「同一条 URL」判等的两处漏口
def test_same_url_treats_one_url_with_two_capitals_as_one():
    """owner/repo 的大小写不是内容差异：GitHub 两种写法是同一个页面。

    账本里存 `Socialpranker/deepdive`、反查填 `socialpranker/deepdive` 时，
    若判成两条不同 URL，「拒绝对已有来源重填一遍」这道反自批门就形同虚设——
    换一下大小写即可复用同一条通道伪装成反查（制品键那边本来就忽略大小写）。
    """
    from ledger import _same_url
    assert _same_url('https://github.com/Socialpranker/deepdive',
                     'https://github.com/socialpranker/deepdive/'), \
        '同一仓库页的大小写/尾斜杠差异被判成两条不同 URL'


def test_clean_url_is_the_single_normalizer_used_by_both_sides():
    """两条判等通道（制品键、字面同一条）必须共用同一个清洗口径。

    各自清洗一遍迟早会长出差异：一边切了控制字符、另一边只 strip，
    就会出现「键相同但判成同一条 URL」这类自相矛盾，拒收理由互相打架。
    """
    from ledger import _artifact_key, _clean_url, _same_url
    dirty = 'https://GitHub.com/ChrisYangSong/CiteGate\r\n'
    assert _clean_url(dirty) == 'https://GitHub.com/ChrisYangSong/CiteGate'
    assert _artifact_key(dirty) == _artifact_key('https://github.com/chrisyangsong/citegate')
    assert _same_url(dirty, 'https://github.com/chrisyangsong/citegate'), \
        '控制字符/大小写/尾斜杠在 _same_url 里没被归一'
