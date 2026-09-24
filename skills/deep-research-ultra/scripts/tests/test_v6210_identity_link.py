"""v6.21.0 回归：跨标识符的同一作品靠第三方书目记录判同，不靠 Lead 一句话。

实跑 2026-09-24（v6.20.1 之后仍剩 6 条升不了档）：反查打在作者预印本
arxiv.org/abs/2005.10732，账本来源是期刊 DOI doi.org/10.1162/qss_a_00112——
同一篇论文的两个标识符，从网址文本互推不出来。

探针实测出可用的判据：以账本已有来源为锚查一次 Semantic Scholar（fields 带
externalIds），返回里就写着 ArXiv 字段（另有 DBLP/MAG/CorpusId）。PMC 那条同理
（10.1016/j.psychres.2023.115334 的记录带 PubMedCentral）。

要点是判同凭据必须是落在账本里的第三方记录，不是 Lead 的口头声明：
link_identity 负责解析并写一条 identity 记录，verify_primary 只认已存在的记录。
这样解析失败时一律拒绝（不会"取不到就当通过"），事后也能查是谁把哪两个标识符绑在一起的。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ledger as L  # noqa: E402

C = chr(58)
DOI = "10.1162/qss_a_00112"
ARXIV = "2005.10732"
OTHER_ARXIV = "9999.00001"
ANCHOR = "https://doi.org/" + DOI
TARGET = "https://arxiv.org/abs/" + ARXIV
OTHER = "https://arxiv.org/abs/" + OTHER_ARXIV
RECORD = "https://api.semanticscholar.org/graph/v1/paper/DOI" + C + DOI


def _resolver(ids):
    return lambda url: {"externalIds": ids, "record_url": RECORD,
                        "corpus_id": ids.get("CorpusId")}


def _mk(tmp_path, cid="c-x-01"):
    led = L.ResearchLedger(str(tmp_path / "ledger")).init()
    led.add_claim("五大书目库两两比对显示重叠部分是同一份上游数据的镜像",
                  topic="已知失效场景与风险", claim_id=cid)
    led.add_source(cid, ANCHOR, title="Large-scale comparison", tier=1)
    return led, cid


def _rows(led, typ):
    return [e for e in L._iter_entries(led.entries_path) if e.get("type") == typ]


def test_link_identity_records_the_third_party_evidence(tmp_path):
    """判同成功时要把凭据写进账本，而不是只改一个状态。"""
    led, cid = _mk(tmp_path)
    n = led.link_identity([cid], ANCHOR, TARGET,
                          resolver=_resolver({"CorpusId": 218763501, "ArXiv": ARXIV}))
    assert n == 1, "externalIds 里有目标 arXiv 号，应当判同一作品"
    rows = _rows(led, "identity")
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["matched"] == "arxiv:" + ARXIV
    assert r["corpus_id"] == 218763501
    assert r["record_url"] == RECORD, "凭据必须是那条书目记录，事后要能点开复查"


def test_verify_primary_accepts_only_after_the_link_exists(tmp_path):
    """放行顺序不能反：没有 identity 记录时照旧拒绝。"""
    led, cid = _mk(tmp_path)
    assert led.verify_primary([cid], TARGET, method="cross_channel") == 0, \
        "还没判同就放行，等于给自批留了后门"
    led.link_identity([cid], ANCHOR, TARGET,
                      resolver=_resolver({"CorpusId": 7, "ArXiv": ARXIV}))
    assert led.verify_primary([cid], TARGET, method="cross_channel") == 1, \
        "已有 identity 记录仍拒绝，判同白做了"
    done = [e for e in L._iter_entries(led.entries_path) if e.get("id") == cid][0]
    assert done["status"] == "verified" and done.get("evidence_tier") == "B"


def test_unmatched_external_ids_refuses_the_link(tmp_path):
    """反向锁：记录里没有目标标识符就不得判同（不许"同站即同文"式放水）。"""
    led, cid = _mk(tmp_path)
    n = led.link_identity([cid], ANCHOR, TARGET,
                          resolver=_resolver({"CorpusId": 7, "DOI": DOI}))
    assert n == 0, "目标标识符不在 externalIds 里却判成同一作品"
    assert not _rows(led, "identity")
    assert led.verify_primary([cid], TARGET) == 0


def test_link_for_another_target_does_not_open_the_gate(tmp_path):
    """记录指向别的预印本时，不许顺手放行另一条反查。"""
    led, cid = _mk(tmp_path)
    led.link_identity([cid], ANCHOR, OTHER,
                      resolver=_resolver({"CorpusId": 7, "ArXiv": OTHER_ARXIV}))
    assert led.verify_primary([cid], TARGET) == 0, "同锚点不同目标被一起放行了"


def test_resolver_failure_refuses_without_network(tmp_path):
    """解析失败一律拒绝：判同不许"取不到就当通过"。"""
    led, cid = _mk(tmp_path)
    assert led.link_identity([cid], ANCHOR, TARGET, resolver=lambda url: None) == 0
    assert led.link_identity([cid], ANCHOR, TARGET, resolver=lambda url: {}) == 0


def test_pmcid_prefix_difference_still_counts_as_same(tmp_path):
    """S2 把 PubMedCentral 存成裸数字、网址里写 PMC10424704：写法差不能判成不同作品。

    实跑 c-d7-09 第一次就被这个差异挡下（记录值 10424704 vs 网址 PMC10424704）。
    """
    led, cid = _mk(tmp_path)
    led.add_source(cid, "https://doi.org/10.1016/j.psychres.2023.115334",
                   title="ChatGPT and Bard…", tier=1)
    target = "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10424704/"
    n = led.link_identity([cid], "https://doi.org/10.1016/j.psychres.2023.115334", target,
                          resolver=_resolver({"CorpusId": 9, "PubMedCentral": "10424704"}))
    assert n == 1, "PMC 前缀差异把同一篇判成了对不上"


def test_anchor_must_be_one_of_the_claims_own_sources(tmp_path):
    """锚点必须是该 claim 已有的来源，否则等于拿别人的记录给自己背书。"""
    led, cid = _mk(tmp_path)
    stranger = "https://doi.org/10.9999/not-in-this-claim"
    assert led.link_identity([cid], stranger, TARGET,
                             resolver=_resolver({"CorpusId": 7, "ArXiv": ARXIV})) == 0
    assert not _rows(led, "identity")
