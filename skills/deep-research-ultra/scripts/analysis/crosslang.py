# -*- coding: utf-8 -*-
"""crosslang —— 跨语言相关性判定：**问题有多大、几种修法各管不管用**。

## 这份脚本回答什么

一个中文查询打进英文库（arxiv / GitHub / npm / skills.sh …）时，
`score.py` 的相关性判定器是**判不出来**的：

- `_score_relevance` 把查询切成「英文词 + 中文 2-gram」，
  2-gram 在英文语料里**恒零命中**（"深度调研" → 深度/度调/调研，在
  "Deep Research Tool" 里一个都碰不到）；
- `_relevance_is_reliable` 于是判「这次判定不可信」，
  把 relevance 封顶成 0、grade 标成 `unrated`、总分封顶 45。

**「unrated」是诚实的**（v6.63 起的设计：判定不出来就不装懂），
但它对用户没用：一条真切的英文结果与一条完全无关的英文结果，
在账本里长得一模一样 —— 全部 0 分，谁都不比谁高。

## 三套量法（每套的偏袒方向都写在标题里）

| 量法 | 参照物 | 它的偏袒 |
|---|---|---|
| 调参集 | 同语种判定器当 oracle | 查询是**看着候选表写的** → 偏乐观 |
| 留出集 | 同语种判定器当 oracle | oracle 严（4~5 个英文词）而表覆盖浅 → 偏悲观 |
| 人工标注 | fixture 的 `manual_label` | 每个查询的语料**主题同质** → 偏乐观 |

**没有任何一套是「真值」**。所以修法要**同时**过三套才算数；
只过其中一套的修法，这个项目已经吃过亏（v6.83 的锚词表、
v6.86 的留出集，都是靠第二套把乐观数字打下来的）。

## 被量的四种候选修法（**都不在生产路径上**）

| 名字 | 做法 |
|---|---|
| 现状 | 中文 2-gram 直判（今天的代码） |
| A 覆盖率门 | 术语表换词后，仍要求覆盖率达标才判 |
| B 听得懂就判 | 术语表换词后，只要命中术语就判（0 覆盖 = 确实不相关） |
| C 至少两个词 | 别名词不足 2 个就不判（一个泛词谁都匹配得上） |
| D 全覆盖才判 | 查询里**每个**中文字都被术语表覆盖才判 |

术语表是**候选修法的原型**（就在本文件里），**不在 `score.py`** ——
因为实测结论是它没过门槛（见 `docs/dev/v6.104-跨语言相关性判据.md`），
所以它没有资格进生产路径。

## 用法

    python scripts/analysis/crosslang.py            # 打印报告
    python scripts/analysis/crosslang.py --check    # 断言与 CHANGELOG 一致（供过程门调用）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from score import CraapScorer as CS  # noqa: E402

FIXTURE = SCRIPTS / "tests" / "fixtures" / "relevance_samples.json"

CJK = re.compile(r'[\u4e00-\u9fff]')

# ---------------------------------------------------------------------------
# 候选修法的术语表（原型，不在生产路径上）
# ---------------------------------------------------------------------------
ALIASES = {
    '深度调研': 'deep research', '调研': 'research', '研究': 'research',
    '工具': 'tool', '实现': 'implementation', '开源': 'open source',
    '方案': 'solution', '对比': 'comparison', '比较': 'comparison',
    '向量': 'vector', '数据库': 'database', '微调': 'fine-tuning',
    '大模型': 'large language model', '大语言模型': 'large language model',
    '语言模型': 'language model', '模型': 'model',
    '机器学习': 'machine learning', '深度学习': 'deep learning',
    '人工智能': 'artificial intelligence', '神经网络': 'neural network',
    '检索增强': 'retrieval augmented', '检索': 'retrieval',
    '增强': 'augmented', '生成': 'generation', '知识图谱': 'knowledge graph',
    '幻觉': 'hallucination', '部署': 'deployment', '推理': 'inference',
    '训练': 'training', '数据集': 'dataset', '评测': 'evaluation',
    '评估': 'evaluation', '基准': 'benchmark', '论文': 'paper',
    '综述': 'survey', '框架': 'framework', '架构': 'architecture',
    '算法': 'algorithm', '智能体': 'agent', '插件': 'plugin',
    '技能': 'skill', '扩展': 'extension', '协议': 'protocol',
    '接口': 'interface', '源码': 'source code', '仓库': 'repository',
    '版本': 'version', '维护': 'maintenance', '社区': 'community',
    '评价': 'review', '口碑': 'reputation', '新闻': 'news',
    '最新': 'latest', '教程': 'tutorial', '文档': 'documentation',
    '原理': 'principle', '性能': 'performance', '优化': 'optimization',
    '成本': 'cost', '安全': 'security', '隐私': 'privacy', '测试': 'testing',
    '集群': 'cluster', '容器': 'container', '编排': 'orchestration',
    '监控': 'monitoring', '可观测性': 'observability', '日志': 'logging',
    '缓存': 'cache', '中间件': 'middleware', '消息队列': 'message queue',
    '微服务': 'microservice', '服务网格': 'service mesh',
    '分布式': 'distributed', '并发': 'concurrency',
    '高可用': 'high availability', '容错': 'fault tolerance',
    '搜索': 'search', '爬虫': 'crawler', '推荐': 'recommendation',
    '图像': 'image', '语音': 'speech', '提示': 'prompt',
    '上下文': 'context', '供应链': 'supply chain', '许可证': 'license',
    '漏洞': 'vulnerability', '加密': 'encryption', '审计': 'audit',
    '指标': 'metric',
}

# ---------------------------------------------------------------------------
# 查询集 ①：调参集（看着候选表写的 → 偏乐观）
# ---------------------------------------------------------------------------
QUERIES = [
    ("深度调研工具", "deep research tool"),
    ("开源实现", "open source implementation"),
    ("向量数据库", "vector database"),
    ("大模型微调", "large language model fine-tuning"),
    ("检索增强生成", "retrieval augmented generation"),
    ("大语言模型", "large language model"),
    ("知识图谱", "knowledge graph"),
    ("模型幻觉", "model hallucination"),
    ("模型部署", "model deployment"),
    ("智能体框架", "agent framework"),
    ("推荐系统", "recommender system"),
    ("训练数据集", "training dataset"),
]

# ---------------------------------------------------------------------------
# 查询集 ②：留出集（候选表定稿之后才写的 → 泛化的真实水平）
# 里面**故意有表没覆盖的词**（多智能体/长期记忆/量化压缩/云原生…）。
# ---------------------------------------------------------------------------
HOLDOUT_QUERIES = [
    ("多智能体系统协作", "multi agent system collaboration"),
    ("代码生成模型评测", "code generation model evaluation"),
    ("长期记忆与检索", "long term memory and retrieval"),
    ("隐私计算与联邦学习", "privacy computing and federated learning"),
    ("模型量化压缩", "model quantization compression"),
    ("视觉语言模型", "vision language model"),
    ("智能体评估指标", "agent evaluation metrics"),
    ("云原生可观测性", "cloud native observability"),
]

# ---------------------------------------------------------------------------
# 查询集 ③：人工标注口径（中英对照）
#
# fixture 的 211 条标注样本只对应 **9 条不同的查询**，所以译文只有 9 条
# （原文是词列表，逐词译；译文忠实 ⇒ 人工标签随之沿用）。
# ---------------------------------------------------------------------------
HUMAN_QUERIES = [
    ("检索增强生成 忠实性", "retrieval augmented generation faithfulness"),
    ("检索增强生成 评测 基准", "retrieval augmented generation evaluation benchmark"),
    ("kubernetes 生产部署 可靠性", "kubernetes production deployment reliability"),
    ("RAG 评测 基准 数据集 忠实性", "rag evaluation benchmark dataset faithfulness"),
    ("检索增强生成 忠实性 评估", "retrieval-augmented generation faithfulness evaluation"),
    ("向量数据库", "vector database"),
    ("检索增强生成 评估", "retrieval augmented generation evaluation"),
    ("kubernetes 生产 最佳实践", "kubernetes production best practice"),
    ("检索增强生成 忠实性 评估", "retrieval augmented generation faithfulness evaluation"),
]


# ---------------------------------------------------------------------------
# 词与分数的小工具
# ---------------------------------------------------------------------------

def alias_words(query: str) -> list:
    """命中术语表的中文词 → 英文词（长词优先，跳过被长词包住的短词，输出去重）。"""
    q = query or ''
    out: list = []
    seen = set()
    covered: list = []
    for zh in sorted(ALIASES, key=len, reverse=True):
        start = 0
        while True:
            i = q.find(zh, start)
            if i < 0:
                break
            span = (i, i + len(zh))
            if not any(a <= span[0] and span[1] <= b for a, b in covered):
                covered.append(span)
                for w in ALIASES[zh].split():
                    if w not in seen:
                        seen.add(w)
                        out.append(w)
            start = i + 1
    return out


def covered_chars(query: str) -> set:
    """被术语表完整覆盖的中文字符下标。"""
    q = query or ''
    hits = set()
    spans: list = []
    for zh in sorted(ALIASES, key=len, reverse=True):
        start = 0
        while True:
            i = q.find(zh, start)
            if i < 0:
                break
            span = (i, i + len(zh))
            if not any(a <= span[0] and span[1] <= b for a, b in spans):
                spans.append(span)
                hits.update(range(span[0], span[1]))
            start = i + 1
    return hits


def is_cross(query: str, title: str, content: str) -> bool:
    """查询含中文、而语料不含中文 → 跨语言场景。"""
    if not query or not CJK.search(query):
        return False
    return not CJK.search(f'{title or ""} {content or ""}')


def legacy_words(query: str) -> list:
    """现状的查询词切法：英文词 + 中文 2-gram。"""
    q = (query or '').lower()
    words = re.findall(r'[a-zA-Z]+', q)
    chars = re.findall(r'[\u4e00-\u9fff]', query or '')
    for i in range(len(chars) - 1):
        words.append(chars[i] + chars[i + 1])
    if len(chars) == 1:
        words.append(chars[0])
    return words


def formula(words, title: str, content: str) -> float:
    """`score.py` 的相关性公式（内容覆盖度只算正文，与代码同式）。"""
    if not words:
        return 50.0
    t_len = len(title)
    length_score = 1.0 if 10 <= t_len <= 80 else (0.5 if t_len < 10 else 0.7)
    t_cov = _coverage(words, (title or '').lower())
    c_cov = _coverage(words, (content or '').lower())
    return min(100, t_cov * 50 + c_cov * 30 + length_score * 20)


def _coverage(words, hay: str) -> float:
    if not words:
        return 0.0
    return sum(1 for w in words if w in hay) / len(words)


# ---------------------------------------------------------------------------
# 四个候选修法（都不在生产路径上）
# ---------------------------------------------------------------------------

def current_score(query, title, content):
    """**今天 `score.py` 的真实行为**（不是复刻 —— 直接调它）。"""
    out = CS().score({'title': title, 'url': '', 'content': content},
                      query=query)
    return float(out.get('relevance') or 0.0), bool(out.get('relevance_capped'))


def _same_language(query, title, content):
    """同语种：一律走今天的代码（候选修法不碰它）。"""
    return current_score(query, title, content)


def gated_score(query, title, content):
    """修法 A：术语表换词 + 覆盖率门。"""
    if not is_cross(query, title, content):
        return _same_language(query, title, content)
    words = re.findall(r'[a-zA-Z]+', (query or '').lower()) + alias_words(query)
    if not words:
        return 0.0, True
    rel = formula(words, title, content)
    reliable = _coverage(words, f'{(title or "").lower()} {(content or "").lower()}') \
        >= CS.RELEVANCE_COVERAGE_FLOOR
    return (0.0 if not reliable else rel), (not reliable)


def understood_score(query, title, content):
    """修法 B：命中术语就判（0 覆盖 = 确实不相关）。"""
    if not is_cross(query, title, content):
        return _same_language(query, title, content)
    words = re.findall(r'[a-zA-Z]+', (query or '').lower()) + alias_words(query)
    if not words:
        return 0.0, True
    return formula(words, title, content), False


def min_words_score(query, title, content, n=2):
    """修法 C：别名词不足 N 个就不判（一个泛词谁都匹配得上）。"""
    if not is_cross(query, title, content):
        return _same_language(query, title, content)
    words = re.findall(r'[a-zA-Z]+', (query or '').lower()) + alias_words(query)
    if len(words) < n:
        return 0.0, True
    return formula(words, title, content), False


def full_coverage_score(query, title, content):
    """修法 D：查询里**每个**中文字都被术语表覆盖才判。"""
    if not is_cross(query, title, content):
        return _same_language(query, title, content)
    cjk = {i for i, ch in enumerate(query or '') if CJK.match(ch)}
    if not cjk or not cjk.issubset(covered_chars(query)):
        return 0.0, True
    words = re.findall(r'[a-zA-Z]+', (query or '').lower()) + alias_words(query)
    if not words:
        return 0.0, True
    return formula(words, title, content), False


VARIANTS = (
    ('current', '现状（中文查询直判，今天的代码）', current_score),
    ('gated', '修法 A：术语表 + 覆盖率门', gated_score),
    ('understood', '修法 B：听得懂就直判', understood_score),
    ('min2', '修法 C：别名词 ≥2 个才判', min_words_score),
    ('full', '修法 D：每个中文字都被覆盖才判', full_coverage_score),
)


# ---------------------------------------------------------------------------
# 三套量法
# ---------------------------------------------------------------------------

def load_corpus():
    rows = json.loads(FIXTURE.read_text(encoding='utf-8'))
    return [(r.get('title') or '', r.get('snippet') or '') for r in rows]


def _auc(pos, neg):
    if not pos or not neg:
        return 0.5
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return (wins + ties / 2) / (len(pos) * len(neg))


def _pr(pos_scores, neg_scores, thr=50):
    """(precision, recall)。以阈值判「留下」，与 v6.83 同一口径。"""
    tp = sum(1 for x in pos_scores if x >= thr)
    fp = sum(1 for x in neg_scores if x >= thr)
    on = len(pos_scores)
    p = tp / (tp + fp) * 100 if (tp + fp) else 100.0
    r = tp / on * 100 if on else 0.0
    return round(p, 1), round(r, 1)


def oracle_eval(queries):
    """量法 ①②：oracle = 同语种判定器（英文译文 × 同一语料）。"""
    corpus = load_corpus()
    total = 0
    acc = {k: {'capped': 0, 'pos': [], 'neg': []} for k, _, _ in VARIANTS}
    for zh, en in queries:
        for title, content in corpus:
            total += 1
            o_rel, _o_cap = current_score(en, title, content)
            on = o_rel >= 50
            for key, _label, fn in VARIANTS:
                rel, cap = fn(zh, title, content)
                acc[key]['capped'] += int(cap)
                (acc[key]['pos'] if on else acc[key]['neg']).append(rel)
    out = {"pairs": total, "n_queries": len(queries)}
    for key, _label, _fn in VARIANTS:
        p, r = _pr(acc[key]['pos'], acc[key]['neg'])
        out[f"{key}_unrated_pct"] = round(acc[key]['capped'] / total * 100, 1)
        out[f"{key}_auc"] = round(_auc(acc[key]['pos'], acc[key]['neg']), 3)
        out[f"{key}_precision"] = p
        out[f"{key}_recall"] = r
    return out


def human_eval():
    """量法 ③：同一批人工标注（fixture 的 manual_label）+ 同一个尺子。"""
    rows = [r for r in json.loads(FIXTURE.read_text(encoding='utf-8'))
            if r.get('manual_label') in ('on', 'off')]
    en2zh = {en: zh for zh, en in HUMAN_QUERIES}
    arms = {'same_lang': {'pos': [], 'neg': []}}
    for key, _label, _fn in VARIANTS:
        arms[key] = {'pos': [], 'neg': []}
    used = 0
    for r in rows:
        en = r.get('query') or ''
        zh = en2zh.get(en)
        if not zh:
            continue
        used += 1
        title = r.get('title') or ''
        content = r.get('snippet') or ''
        on = r.get('manual_label') == 'on'
        s_rel, _s_cap = current_score(en, title, content)
        (arms['same_lang']['pos'] if on else arms['same_lang']['neg']).append(s_rel)
        for key, _label, fn in VARIANTS:
            rel, _cap = fn(zh, title, content)
            (arms[key]['pos'] if on else arms[key]['neg']).append(rel)
    out = {'human_n': used}
    for key, v in arms.items():
        p, r = _pr(v['pos'], v['neg'])
        out[f"human_{key}_precision"] = p
        out[f"human_{key}_recall"] = r
    return out


def compute_all():
    out = oracle_eval(QUERIES)
    for k, v in oracle_eval(HOLDOUT_QUERIES).items():
        out['holdout_' + k] = v
    out.update(human_eval())
    return out


# 与 CHANGELOG v6.104 对账用。改动本脚本的量法或候选修法后必须同步改并说明理由。
EXPECTED = {
    # 现状（今天代码的真实行为）
    "current_unrated_pct": 100.0,
    "current_auc": 0.5,
    "current_recall": 0.0,
    # 人工标注口径：尺子（同语种，今天的代码）
    "human_same_lang_precision": 90.5,
    "human_same_lang_recall": 85.7,
    # 人工标注口径：现状
    "human_current_recall": 0.0,
    # 留出集：候选修法 B（看得懂就判）过不了门槛
    "holdout_understood_precision": 19.0,
    "holdout_understood_recall": 87.3,
    "holdout_min2_precision": 38.3,
    "holdout_min2_recall": 74.5,
    "holdout_full_precision": 70.0,
    "holdout_full_recall": 12.7,
}
TOLERANCE = 0.15


def report(got):
    print("=" * 80)
    print("跨语言相关性判定：问题有多大 + 四种候选修法各管不管用")
    print("=" * 80)
    print()
    print("  ── 量法 ①②：oracle = 同语种判定器（英文译文 × 同一语料）──")
    print(f"  {'判定':<34} {'unrated':>9} {'AUC':>7} {'precision':>10} {'recall':>8}")
    print("  " + "-" * 68)
    for tag, qs in (('调参集', QUERIES), ('留出集', HOLDOUT_QUERIES)):
        print(f"  【{tag}】{len(qs)} 条查询 × 211 条真实语料")
        for key, label, _fn in VARIANTS:
            pre = '' if tag == '调参集' else 'holdout_'
            print(f"  {label:<34} {got[pre + key + '_unrated_pct']:>8.1f}% "
                  f"{got[pre + key + '_auc']:>7.3f} "
                  f"{got[pre + key + '_precision']:>9.1f}% "
                  f"{got[pre + key + '_recall']:>7.1f}%")
        print()
    print("  ── 量法 ③：人工标注口径（同一批 manual_label，同一个尺子）──")
    print(f"  {'判定':<34} {'precision':>10} {'recall':>8}")
    print("  " + "-" * 54)
    print(f"  {'同语种（英文查询，今天的代码）= 尺子':<34} "
          f"{got['human_same_lang_precision']:>9.1f}% "
          f"{got['human_same_lang_recall']:>7.1f}%")
    for key, label, _fn in VARIANTS:
        print(f"  {label:<34} {got['human_' + key + '_precision']:>9.1f}% "
              f"{got['human_' + key + '_recall']:>7.1f}%")
    print(f"  （样本 {got['human_n']} 条，标签来自 fixture 的 manual_label）")
    print()
    print("=" * 80)
    print("结论：现状在**三套量法**里都排最后（recall 0%：它从来没判过任何一条）。")
    print("      候选修法在**人工标注口径**（主题同质）上看着都好，")
    print("      但在**留出集**（语料混合、查询表没覆盖）上 B 掉到 19% ——")
    print("      一个泛词（agent / model / retrieval）就能让不相关语料被判切题。")
    print("      所以：术语表方案**没过门槛**，不进生产路径。")
    print("      详见 docs/dev/v6.104-跨语言相关性判据.md")
    print("=" * 80)


def check(got):
    bad = []
    for k, want in EXPECTED.items():
        have = float(got[k])
        if abs(have - float(want)) > TOLERANCE:
            bad.append(f"{k}: CHANGELOG 记 {want}，实算 {have}")
    if bad:
        print("❌ 与 CHANGELOG 对不上：")
        for b in bad:
            print("   " + b)
        print("\n   数字变了可能是三件事之一，**别直接改 CHANGELOG**：")
        print("   ① 量法改了（查询集/语料/口径）→ 在本文件里写明为什么")
        print("   ② 候选修法改了 → 那是结论变了，要重新看三套量法")
        print("   ③ score.py 的跨语言行为变了 → 那是**行为改动**，要单独说明与钉子")
        return 1
    print(f"✅ {len(EXPECTED)} 个关键数字与 CHANGELOG v6.104 一致"
          f"（容差 ±{TOLERANCE}，只容忍浮点，不容忍结论退化）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="跨语言相关性判定：问题与候选修法实测")
    ap.add_argument("--check", action="store_true",
                    help="断言与 CHANGELOG 记录的数字一致（供测试/过程门调用）")
    a = ap.parse_args(argv)
    got = compute_all()
    if a.check:
        return check(got)
    report(got)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
