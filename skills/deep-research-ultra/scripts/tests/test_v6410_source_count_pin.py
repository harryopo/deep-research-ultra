"""数据源计数只能有一处权威：注册表。文档里写死的数字必须与它对齐。

为什么要有这条：v6.41 加 Europe PMC 时，页面上的条数/chip 有测试钉住（一改就红），
但 SKILL.md §四 抬头写的「28 个可搜索，20 个支持 --probe 自检」根本没人对过数——
实测那一刻已经是 27 个可搜索、21 个登记探针，两个方向都错，且错了很久没人发现。
README 里那句「N 个数据源」同样没人管。

这不代表文档写错了要紧，而是这套包的卖点是「数字可溯源」：
自己文档里的数对不上自己的注册表，就是最大的反例。
"""

import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SKILL_ROOT = SCRIPTS.parent                    # skills/deep-research-ultra/
REPO_ROOT = SKILL_ROOT.parent.parent           # 仓库根
sys.path.insert(0, str(SCRIPTS))

from research import build_registry            # noqa: E402
import probe                                   # noqa: E402


def real_counts():
    """注册表实际数：(总数, 可搜索数, 已登记探针数)"""
    engines = build_registry().get_all()
    searchable = sum(1 for e in engines if 'search' in e.metadata.capabilities)
    return len(engines), searchable, len(probe.PROBE_QUERIES)


def find_doc_drift(skill_text: str, readme_text: str, real) -> list:
    """把文档里写死的计数与注册表对数，返回所有不一致的描述。"""
    total, searchable, probes = real
    drift = []
    m = re.search(r'共 (\d+) 个数据源：(\d+) 个可搜索，(\d+) 个支持 --probe 自检', skill_text)
    if not m:
        drift.append('SKILL.md §四 抬头找不到那句计数')
    else:
        got = tuple(int(x) for x in m.groups())
        if got != (total, searchable, probes):
            drift.append(f'SKILL.md §四 写 {got}，注册表实为 '
                         f'{(total, searchable, probes)}')
    for label, text in (('SKILL.md', skill_text), ('README.md', readme_text)):
        for n in re.findall(r'(\d+) 个数据源', text):
            if int(n) != total:
                drift.append(f'{label} 写「{n} 个数据源」，注册表共 {total} 个')
    return drift


def test_docs_match_registry():
    skill = (SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
    readme = (REPO_ROOT / 'README.md').read_text(encoding='utf-8')
    drift = find_doc_drift(skill, readme, real_counts())
    assert not drift, '；'.join(drift)


def test_drift_checker_bites_on_a_stale_number():
    """钉本身要能咬：把抬头改回上一版的旧数，必须报出差异，而不是安静通过。"""
    skill = ('## 四、四层数据源架构（共 32 个数据源：28 个可搜索，'
             '20 个支持 --probe 自检，含 5 个 MCP）')
    drift = find_doc_drift(skill, '', real_counts())
    assert any('32' in d or '20' in d for d in drift), drift


def test_probe_registry_covers_every_searchable_script_engine():
    """新增引擎若忘了登记探针，它就会以「--list 绿、实跑 0 条」的形态逃过闸门。"""
    reg = build_registry()
    agent_only = {e.get_name() for e in reg.get_all() if probe.agent_invoked(e)}
    missing = [e.get_name() for e in reg.get_all()
               if 'search' in e.metadata.capabilities
               and e.get_name() not in probe.PROBE_QUERIES
               and e.get_name() not in agent_only
               and e.get_name() not in probe.LOOKUP_PROBES]
    assert not missing, f'这些可搜索引擎没有功能探针：{missing}'
