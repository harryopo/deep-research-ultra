"""
similarity.py — 语义级相似度与转载检测核心  [v6.4 新增]

解决真实性验证链两处语义盲区：
1. 独立来源按 URL 并集计数 → 认不出"同一通稿跨站转载=N 个独立来源"
   → 内容指纹（归一化标题）去重：同指纹的多个来源算 1 个独立来源
2. claim 聚类靠词集 Jaccard → 数值矛盾（2.8x vs 3x）被并入同组、表述差异漏聚
   → 字符 n-gram 加权相似度聚类 + 数值提取做差异检测

设计约束：
- 纯标准库（无 numpy/sklearn 依赖），中文/英文混合文本均可用
- 确定性可复现，全部可测试；可选 LLM 回调接口预留（默认关闭）
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 文本归一化
# ---------------------------------------------------------------------------

_PUNCT = re.compile(r'[\s\W_]+', re.UNICODE)
_EN_WORD = re.compile(r'[a-zA-Z0-9]+')
_NUM = re.compile(r'(\d+(?:\.\d+)?)')


def normalize_text(text: str) -> str:
    """归一化：全角→半角、去标点空白、统一大小写（保留中文与字母数字）。"""
    if not text:
        return ''
    t = unicodedata.normalize('NFKC', str(text)).lower()
    t = _PUNCT.sub(' ', t)          # 非字母数字/中文 → 空格
    t = re.sub(r'\s+', '', t)       # 去空白（中文无分词）
    return t.strip()


def normalize_title(text: str) -> str:
    """标题指纹：归一化 + 去站名/转载冗余词（转载站标题常带站点/栏目后缀）。"""
    t = normalize_text(text)
    # 直接删除常见站名/栏目/转载冗余词（normalize 已去掉分隔符，此处不依赖 '|'）
    for w in ('新浪', '网易', '腾讯', '搜狐', '澎湃', '36氪', 'cnbeta', 'ithome',
              '转载', '转自', '转发', '快讯', '独家', '首发', '视频', '新闻',
              '资讯', '报道'):
        t = t.replace(w, '')
    t = re.sub(r'站$', '', t)   # 尾部 '站' 残留（转载站）
    return t.strip()


# ---------------------------------------------------------------------------
# 相似度
# ---------------------------------------------------------------------------

def char_ngrams(text: str, n: int = 3) -> Set[str]:
    """字符 n-gram（中文无词边界，字符级即可；英文先切词再取词 n-gram 混合）。"""
    t = normalize_text(text)
    grams = set()
    if not t:
        return grams
    # 连续字母数字串作为整体 token
    tokens = _EN_WORD.findall(t)
    for tok in tokens:
        grams.add('W:' + tok)
    # 中文按字符 n-gram（过滤纯英文串内的 ascii 字符也参与，覆盖混合）
    pure = re.sub(r'[a-zA-Z0-9]', '', t)   # 仅中文字符
    for i in range(len(pure) - n + 1):
        grams.add('C:' + pure[i:i + n])
    return grams


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def text_similarity(a: str, b: str) -> float:
    """两个文本的语义相似度（0-1）：字符 3-gram Jaccard + 长串回退。"""
    if not a or not b:
        return 0.0
    ga, gb = char_ngrams(a, 3), char_ngrams(b, 3)
    sim = jaccard(ga, gb)
    # 短文本（<8 字符）n-gram 稀疏 → 用归一化等价补偿
    if sim < 0.4 and len(normalize_text(a)) <= 6 and len(normalize_text(b)) <= 6:
        if normalize_text(a) == normalize_text(b):
            return 1.0
    return sim


def is_same_content(a: str, b: str, threshold: float = 0.86) -> bool:
    """转载/同稿判定：归一化标题等价或高相似 → True。"""
    if not a or not b:
        return False
    na, nb = normalize_title(a), normalize_title(b)
    if na and na == nb:
        return True
    return text_similarity(a, b) >= threshold


# ---------------------------------------------------------------------------
# 转载去重（来源指纹分组）
# ---------------------------------------------------------------------------

def dedupe_by_content(sources: Sequence[Dict[str, Any]],
                      title_key: str = 'title',
                      url_key: str = 'url') -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """按内容指纹（标题相似）对来源去重，返回 (去重后列表, 统计)。

    - 同一通稿跨站转载（标题指纹相同/高相似）→ 只保留 1 条（优先官方/权威域）
    - 统计: {total, groups, deduped_cnt}
    """
    items = list(sources)
    groups: List[List[Dict[str, Any]]] = []
    for it in items:
        title = str(it.get(title_key, '') or '')
        placed = False
        for g in groups:
            g_title = str(g[0].get(title_key, '') or '')
            if is_same_content(title, g_title):
                g.append(it)
                placed = True
                break
        if not placed:
            groups.append([it])

    def _rank(s: Dict[str, Any]) -> int:
        """组内排序：Tier 越小越官方，其次有 URL。"""
        tier = s.get('tier') or 5
        return (int(tier), 0 if s.get(url_key) else 1)

    deduped = []
    for g in groups:
        g_sorted = sorted(g, key=_rank)
        deduped.append(g_sorted[0])

    return deduped, {
        'total': len(items),
        'groups': len(groups),
        'deduped_cnt': len(items) - len(deduped),
    }


def effective_independent_count(sources: Sequence[Dict[str, Any]],
                                title_key: str = 'title',
                                url_key: str = 'url') -> int:
    """有效独立来源数：转载去重后的组数。"""
    if not sources:
        return 0
    deduped, _ = dedupe_by_content(sources, title_key, url_key)
    return len(deduped)


# ---------------------------------------------------------------------------
# 数值提取与矛盾检测
# ---------------------------------------------------------------------------

_UNIT_STRIP = re.compile(r'[^\d.+\-%倍x×XBGTKMm亿万%]')


def extract_numbers(text: str) -> List[Dict[str, float]]:
    """提取数值（含单位上下文），返回 [{value, raw, unit}]。

    覆盖：3倍 / 2.8x / 30.5% / 100ms / 5 万 / 1e6 等常见表达。
    """
    t = str(text)
    out = []
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(倍|x|×|%|ms|s|ms|k|kbps|mb|gb|tb|cpu|v|人|万|亿)?', t, re.I):
        try:
            val = float(m.group(1))
            unit = (m.group(2) or '').lower()
            if unit == '万':
                val *= 1e4
            elif unit == '亿':
                val *= 1e8
            out.append({'value': val, 'raw': m.group(0).strip(),
                        'unit': unit})
        except ValueError:
            continue
    return out


def numeric_conflict(a: str, b: str, ratio_threshold: float = 0.2) -> Optional[Dict[str, Any]]:
    """检测两个 claim 是否数值矛盾。

    取双方同单位数值对，若差异 |x-y|/max(|x|,|y|) > ratio_threshold 且量级可比 →
    返回冲突证据（含两边数值），否则 None。
    """
    nums_a = [n for n in extract_numbers(a) if n['value'] != 0]
    nums_b = [n for n in extract_numbers(b) if n['value'] != 0]
    if not nums_a or not nums_b:
        return None
    for na in nums_a:
        for nb in nums_b:
            if na['unit'] != nb['unit']:
                continue
            denom = max(abs(na['value']), abs(nb['value']))
            if denom == 0:
                continue
            ratio = abs(na['value'] - nb['value']) / denom
            if ratio > ratio_threshold and min(abs(na['value']), abs(nb['value'])) >= 1:
                return {
                    'a': f"{na['raw']}",
                    'b': f"{nb['raw']}",
                    'ratio': round(ratio, 2),
                }
    return None


# ---------------------------------------------------------------------------
# claim 聚类（verify 用）
# ---------------------------------------------------------------------------

def group_by_similarity(statements: Sequence[str],
                        threshold: float = 0.34) -> List[List[int]]:
    """按相似度聚类：返回每组在 statements 中的下标列表。

    贪心单链聚类。判据二选一（任一命中即同组）：
    a) char n-gram 相似度 ≥ threshold（长句高度重叠）
    b) 核心 token（汉字 2-gram + 英文词）重叠 ≥2（近义改写：同主体+同关键词，
       解决"Transformer 是主流 LLM 架构" vs "Transformer 是当下主流的大模型架构"
       这类字符 n-gram 召回不足的问题）
    """
    n = len(statements)
    used = [False] * n
    groups: List[List[int]] = []

    def _core_tokens(text: str) -> Set[str]:
        t = normalize_text(text)
        toks = set()
        toks.update(_EN_WORD.findall(t))
        cn = re.sub(r'[a-zA-Z0-9]', '', t)
        for i in range(len(cn) - 1):
            toks.add(cn[i:i + 2])
        return toks

    def _similar(a: str, b: str) -> bool:
        if text_similarity(a, b) >= threshold:
            return True
        return len(_core_tokens(a) & _core_tokens(b)) >= 2

    for i in range(n):
        if used[i]:
            continue
        group = [i]
        used[i] = True
        for j in range(i + 1, n):
            if used[j]:
                continue
            if any(_similar(statements[gi], statements[j]) for gi in group):
                group.append(j)
                used[j] = True
        groups.append(group)
    return groups