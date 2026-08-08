#!/usr/bin/env python3
"""
Deep Research Ultra v4.0 — CRAAP 质量评分系统

实现 CRAAP 五维评估标准（信息可信度评估）：
- C (Currency): 时效性 — 信息是否近期？是否有过时内容？
- R (Relevance): 相关性 — 是否回答了研究问题？受众是否合适？
- A (Authority): 权威性 — 作者是否 qualified？出版方是否可信？
- A (Accuracy): 准确性 — 是否可验证？是否有引用？是否经过同行评审？
- P (Purpose): 目的性 — 写作意图是什么？是否有偏见/商业目的？

同时支持：
- LLM 语义评分（可选，--llm-score 启用）
  解决纯关键词匹配的局限：识别"标题党"、低质量内容、AI 生成内容
- 综合可信度等级：high / medium / low

修复 v3.2.0 的问题：
- v3 评分维度过于简单（标题40+内容30+权威20+时效10）
  → v4 采用 CRAAP 五维标准
- v3 中文查询通常无空格，query_lower.split() 直接失效
  → v4 使用 jieba/字符级匹配 + LLM 语义评分
- v3 没有 LLM 语义评分
  → v4 新增 LLM 语义评分（可选）

输出：每条结果带 craap_score 字段
    {
        'currency': float,    # 0-100
        'relevance': float,   # 0-100
        'authority': float,   # 0-100
        'accuracy': float,    # 0-100
        'purpose': float,     # 0-100
        'total': float,       # 加权总分
        'grade': str,         # high/medium/low
        'llm_evaluated': bool # 是否经过 LLM 评分
    }
"""

import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

# 延迟导入以避免循环依赖
try:
    from .engines.base import SearchResult
except ImportError:
    # 直接运行时的 fallback
    pass


# ============================================================
# 权威域名清单
# ============================================================

AUTHORITATIVE_DOMAINS = {
    # 学术
    'arxiv.org': 95, 'pubmed.ncbi.nlm.nih.gov': 95, 'scholar.google.com': 95,
    'semanticscholar.org': 90, 'openalex.org': 90, 'crossref.org': 90,
    'biorxiv.org': 85, 'medrxiv.org': 85, 'doi.org': 85,
    'nature.com': 95, 'science.org': 95, 'ieee.org': 90,
    'acm.org': 90, 'springer.com': 85, 'wiley.com': 80,
    # 官方文档
    'docs.python.org': 95, 'developer.mozilla.org': 90,
    'learn.microsoft.com': 90, 'developers.google.com': 90,
    'react.dev': 85, 'vuejs.org': 85, 'angular.io': 85,
    'nodejs.org': 85, 'go.dev': 85, 'rust-lang.org': 85,
    'typescriptlang.org': 85, 'java.com': 80,
    # 技术社区
    'github.com': 80, 'stackoverflow.com': 75, 'stackexchange.com': 75,
    'dev.to': 65, 'medium.com': 60, 'hashnode.dev': 60,
    # 中文技术
    'zhihu.com': 60, 'csdn.net': 50, 'juejin.cn': 55,
    'segmentfault.com': 55, 'infoq.cn': 65, 'cnblogs.com': 55,
    'ruanyifeng.com': 70, 'wiki.jikexueyuan.com': 50,
    # 百科
    'wikipedia.org': 70, 'baike.baidu.com': 55,
    # 标准/规范
    'w3.org': 95, 'ietf.org': 95, 'iso.org': 95,
    # 新闻/媒体
    'techcrunch.com': 60, 'ars technica.com': 65,
    'theverge.com': 55, 'wired.com': 55,
}

# 商业/低可信度域名
LOW_CREDIBILITY_DOMAINS = {
    'content farms': 30,
    'csdn.net': 50,  # 内容质量参差不齐
    'jianshu.com': 45,
    'baijiahao.baidu.com': 35,  # 自媒体平台
    'toutiao.com': 40,
    'sohu.com': 40,
    '360doc.com': 30,
}


# ============================================================
# 评分器
# ============================================================

class CraapScorer:
    """
    CRAAP 五维评分器

    使用方式：
        scorer = CraapScorer()
        score = scorer.score(result, query="搜索关键词")
        # score = {'currency': 85, 'relevance': 90, ..., 'total': 87, 'grade': 'high'}
    """

    # 权重配置（总和=1.0）
    DEFAULT_WEIGHTS = {
        'currency': 0.15,   # 时效性
        'relevance': 0.35,  # 相关性（最重要）
        'authority': 0.20,  # 权威性
        'accuracy': 0.20,   # 准确性
        'purpose': 0.10,    # 目的性
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS

    # ------------------------------------------------------------
    # 主评分入口
    # ------------------------------------------------------------

    def score(self, result: Any, query: str = '',
              enable_llm: bool = False) -> Dict[str, Any]:
        """
        对单条搜索结果进行 CRAAP 评分

        Args:
            result: SearchResult 对象或字典
            query: 原始搜索关键词（用于相关性评分）
            enable_llm: 是否启用 LLM 语义评分

        Returns:
            CRAAP 评分字典
        """
        # 提取字段
        if hasattr(result, 'title'):
            title = result.title
            url = result.url
            content = result.content
            published_date = getattr(result, 'published_date', '')
            author = getattr(result, 'author', '')
            source = getattr(result, 'source', '')
        else:
            title = result.get('title', '')
            url = result.get('url', '')
            content = result.get('content', '')
            published_date = result.get('published_date', '')
            author = result.get('author', '')
            source = result.get('source', '')

        # 五维评分
        currency_score = self._score_currency(published_date, content)
        relevance_score = self._score_relevance(query, title, content)
        authority_score = self._score_authority(url, author, source)
        accuracy_score = self._score_accuracy(content, url)
        purpose_score = self._score_purpose(url, content)

        # LLM 语义评分（可选）
        llm_evaluated = False
        if enable_llm:
            llm_adjustment = self._llm_evaluate(query, title, content, url)
            if llm_adjustment:
                relevance_score = (relevance_score + llm_adjustment['relevance']) / 2
                accuracy_score = (accuracy_score + llm_adjustment['accuracy']) / 2
                purpose_score = (purpose_score + llm_adjustment['purpose']) / 2
                llm_evaluated = True

        # 加权总分
        total = (
            currency_score * self.weights['currency'] +
            relevance_score * self.weights['relevance'] +
            authority_score * self.weights['authority'] +
            accuracy_score * self.weights['accuracy'] +
            purpose_score * self.weights['purpose']
        )

        return {
            'currency': round(currency_score, 1),
            'relevance': round(relevance_score, 1),
            'authority': round(authority_score, 1),
            'accuracy': round(accuracy_score, 1),
            'purpose': round(purpose_score, 1),
            'total': round(total, 1),
            'grade': self._get_grade(total),
            'llm_evaluated': llm_evaluated,
        }

    def score_batch(self, results: List[Any], query: str = '',
                    enable_llm: bool = False) -> List[Any]:
        """
        批量评分

        在原结果对象上填充 craap_score 字段，并按总分降序排列。
        """
        for result in results:
            score = self.score(result, query, enable_llm)
            if hasattr(result, 'craap_score'):
                result.craap_score = score
            else:
                result['craap_score'] = score
        # 按总分降序
        def _get_total(r):
            if hasattr(r, 'craap_score'):
                return r.craap_score['total']
            return r.get('craap_score', {}).get('total', 0)
        results.sort(key=_get_total, reverse=True)
        return results

    # ------------------------------------------------------------
    # 五维评分实现
    # ------------------------------------------------------------

    def _score_currency(self, published_date: str, content: str) -> float:
        """
        时效性评分（0-100）

        - 有明确日期且近期 → 高分
        - 有日期但较旧 → 中分
        - 无日期 → 低分
        """
        if not published_date:
            # 尝试从内容提取日期
            date_match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月]?(\d{1,2})?', content)
            if date_match:
                published_date = date_match.group(0)
            else:
                return 40.0  # 无日期信息

        # 解析年份
        year_match = re.search(r'(20\d{2})', str(published_date))
        if not year_match:
            return 40.0

        try:
            year = int(year_match.group(1))
            current_year = datetime.now().year
            years_ago = current_year - year

            if years_ago <= 0:
                return 100.0  # 当年
            elif years_ago == 1:
                return 90.0
            elif years_ago == 2:
                return 75.0
            elif years_ago == 3:
                return 60.0
            elif years_ago <= 5:
                return 45.0
            else:
                return 25.0
        except (ValueError, IndexError):
            return 40.0

    def _score_relevance(self, query: str, title: str, content: str) -> float:
        """
        相关性评分（0-100）

        修复 v3 问题：v3 用 query_lower.split() 在中文查询下失效
        v4 改用字符级匹配 + 关键词覆盖度

        评分维度：
        - 查询词在标题中的覆盖度（50%）
        - 查询词在内容中的覆盖度（30%）
        - 标题长度合理性（20%，避免标题党）
        """
        if not query:
            return 60.0

        query_lower = query.lower()
        title_lower = title.lower()
        content_lower = content.lower() if content else ''

        # 提取查询关键词
        # 英文按空格分词
        query_words = re.findall(r'[a-zA-Z]+', query_lower)
        # 中文按字符提取（2-3 字符滑窗）
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', query)
        if chinese_chars:
            # 中文查询：提取 2-gram
            for i in range(len(chinese_chars) - 1):
                query_words.append(chinese_chars[i] + chinese_chars[i + 1])
            if len(chinese_chars) == 1:
                query_words.append(chinese_chars[0])

        if not query_words:
            return 50.0

        # 标题覆盖度
        title_matches = sum(1 for w in query_words if w in title_lower)
        title_coverage = title_matches / len(query_words)

        # 内容覆盖度
        content_matches = sum(1 for w in query_words if w in content_lower)
        content_coverage = content_matches / len(query_words)

        # 标题长度合理性（10-80 字符为佳）
        title_len = len(title)
        if 10 <= title_len <= 80:
            length_score = 1.0
        elif title_len < 10:
            length_score = 0.5
        else:
            length_score = 0.7  # 标题过长可能是标题党

        # 综合评分
        score = (
            title_coverage * 50 +
            content_coverage * 30 +
            length_score * 20
        )
        return min(100, score)

    def _score_authority(self, url: str, author: str, source: str) -> float:
        """
        权威性评分（0-100）

        基于域名权威度 + 作者可信度
        """
        url_lower = url.lower() if url else ''

        # 检查权威域名
        authority_score = 50.0  # 默认分
        for domain, score in AUTHORITATIVE_DOMAINS.items():
            if domain in url_lower:
                authority_score = max(authority_score, score)
                break

        # 检查低可信度域名
        for domain, score in LOW_CREDIBILITY_DOMAINS.items():
            if domain in url_lower:
                authority_score = min(authority_score, score)
                break

        # 作者加分
        if author:
            # 知名作者/机构
            if any(kw in author.lower() for kw in ['phd', 'dr', 'professor', '教授', '博士']):
                authority_score = min(100, authority_score + 10)

        # 数据源加分（来自可信 MCP/skill）
        if source in ['arxiv', 'paper-search', 'sciverse', 'tavily']:
            authority_score = min(100, authority_score + 5)
        elif source in ['baidu-html', 'bing-html']:
            authority_score = max(0, authority_score - 5)

        return authority_score

    def _score_accuracy(self, content: str, url: str) -> float:
        """
        准确性评分（0-100）

        启发式评估：
        - 内容长度（有足够细节）
        - 是否包含引用/参考链接
        - 是否包含数据/数字
        - 是否来自可验证来源
        """
        if not content:
            return 30.0

        score = 50.0

        # 内容长度
        content_len = len(content)
        if content_len > 1000:
            score += 20
        elif content_len > 500:
            score += 15
        elif content_len > 200:
            score += 10
        elif content_len > 50:
            score += 5
        else:
            score -= 10

        # 引用/参考
        if re.search(r'(参考文献|references|引用|cited|来源|source|according to)', content, re.IGNORECASE):
            score += 10
        if re.search(r'https?://', content):
            score += 5  # 包含链接

        # 数据/数字
        if re.search(r'\d+(\.\d+)?%', content):
            score += 5  # 包含百分比
        if re.search(r'\d{4}', content):
            score += 5  # 包含年份

        # 同行评审标识
        if re.search(r'(peer.?review|同行评审|arxiv|pubmed|doi)', content, re.IGNORECASE):
            score += 10

        return min(100, max(0, score))

    def _score_purpose(self, url: str, content: str) -> float:
        """
        目的性评分（0-100）

        评估信息的目的：
        - 教育/信息目的 → 高分
        - 商业/推广目的 → 低分
        - 偏见/立场明显 → 中分
        """
        url_lower = url.lower() if url else ''
        content_lower = content.lower() if content else ''
        score = 70.0  # 默认分

        # 商业/推广信号
        commercial_signals = ['buy', 'purchase', 'discount', '优惠', '购买', '立即购买',
                              '广告', 'ad', 'sponsored', '赞助', '推广']
        commercial_count = sum(1 for sig in commercial_signals if sig in content_lower)
        if commercial_count > 0:
            score -= min(30, commercial_count * 10)

        # 商业域名
        if any(d in url_lower for d in ['amazon.', 'taobao.', 'jd.com', 'ebay.']):
            score -= 20

        # 教育/信息信号
        educational_signals = ['tutorial', 'guide', '文档', '教程', '指南',
                               'how to', '如何', '原理', 'principle']
        educational_count = sum(1 for sig in educational_signals if sig in content_lower)
        if educational_count > 0:
            score += min(15, educational_count * 5)

        # 教育/政府域名
        if any(d in url_lower for d in ['.edu', '.gov', '.org']):
            score += 10

        # 偏见信号（过度绝对化表述）
        bias_signals = ['best ever', '绝对', '100%', '保证', 'guarantee', 'miracle']
        bias_count = sum(1 for sig in bias_signals if sig in content_lower)
        if bias_count > 0:
            score -= min(20, bias_count * 10)

        return min(100, max(0, score))

    # ------------------------------------------------------------
    # LLM 语义评分（可选）
    # ------------------------------------------------------------

    def _llm_evaluate(self, query: str, title: str, content: str,
                      url: str) -> Optional[Dict[str, float]]:
        """
        LLM 语义评分

        实际由 Claude 完成，本方法返回 None 表示需要 Claude 介入。
        Claude 读取以下提示后进行评分，并将结果填入 craap_score。

        提示模板（供 Claude 读取）：
        """
        # 本方法不直接调用 LLM，返回 None
        # 实际评分由 Claude 在 Execute 阶段完成
        return None

    @staticmethod
    def get_llm_eval_prompt(query: str, title: str, content: str,
                            url: str) -> str:
        """
        生成 LLM 评估提示词

        Claude 在执行语义评分时使用此提示词。
        """
        return f"""请对以下搜索结果进行 CRAAP 语义评分（0-100 分）：

查询关键词: {query}
标题: {title}
URL: {url}
内容摘要: {content[:500]}...

请评估以下三个维度（每项 0-100 分）：

1. **Relevance（相关性）**: 内容是否真正回答了查询？
   - 100: 完全相关，直接回答查询
   - 50: 部分相关，涉及主题但未深入
   - 0: 不相关或"标题党"

2. **Accuracy（准确性）**: 内容是否准确可信？
   - 100: 有引用、有数据、来自权威源
   - 50: 信息一般，无明显错误但缺乏引用
   - 0: 明显错误、虚假信息、AI 生成低质量内容

3. **Purpose（目的性）**: 信息目的是否客观？
   - 100: 教育性、信息性、客观
   - 50: 有一定商业目的但内容有价值
   - 0: 纯广告、偏见明显、误导性

请以 JSON 格式返回：
{{"relevance": <float>, "accuracy": <float>, "purpose": <float>}}
"""

    # ------------------------------------------------------------
    # 等级转换
    # ------------------------------------------------------------

    @staticmethod
    def _get_grade(total: float) -> str:
        """总分转可信度等级"""
        if total >= 75:
            return 'high'
        elif total >= 50:
            return 'medium'
        else:
            return 'low'

    @staticmethod
    def grade_to_chinese(grade: str) -> str:
        """等级转中文"""
        return {
            'high': '高可信度',
            'medium': '中可信度',
            'low': '低可信度',
        }.get(grade, '未知')


# ============================================================
# 便捷函数
# ============================================================

def score_result(result: Any, query: str = '', enable_llm: bool = False) -> Dict[str, Any]:
    """对单条结果评分"""
    scorer = CraapScorer()
    return scorer.score(result, query, enable_llm)


def score_results(results: List[Any], query: str = '',
                  enable_llm: bool = False, min_score: float = 0) -> List[Any]:
    """
    批量评分并过滤

    Args:
        results: 搜索结果列表
        query: 搜索关键词
        enable_llm: 是否启用 LLM 评分
        min_score: 最低总分过滤（0=不过滤）

    Returns:
        评分后的结果列表（按总分降序）
    """
    scorer = CraapScorer()
    scorer.score_batch(results, query, enable_llm)
    if min_score > 0:
        results = [r for r in results if (
            r.craap_score['total'] if hasattr(r, 'craap_score')
            else r.get('craap_score', {}).get('total', 0)
        ) >= min_score]
    return results


def get_score_summary(results: List[Any]) -> Dict[str, Any]:
    """获取评分汇总"""
    if not results:
        return {'avg_total': 0, 'grade_distribution': {'high': 0, 'medium': 0, 'low': 0}}

    totals = []
    grades = {'high': 0, 'medium': 0, 'low': 0}
    for r in results:
        score = r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {})
        total = score.get('total', 0)
        grade = score.get('grade', 'low')
        totals.append(total)
        grades[grade] = grades.get(grade, 0) + 1

    return {
        'avg_total': round(sum(totals) / len(totals), 1),
        'max_total': max(totals),
        'min_total': min(totals),
        'grade_distribution': grades,
        'total_results': len(results),
    }


# ============================================================
# CLI 入口
# ============================================================

def _main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description='CRAAP 质量评分')
    parser.add_argument('query', help='搜索关键词')
    parser.add_argument('--title', required=True, help='结果标题')
    parser.add_argument('--url', default='', help='结果 URL')
    parser.add_argument('--content', default='', help='结果内容')
    parser.add_argument('--date', default='', help='发布日期')
    parser.add_argument('--llm', action='store_true', help='启用 LLM 评分')
    args = parser.parse_args()

    result = {
        'title': args.title,
        'url': args.url,
        'content': args.content,
        'published_date': args.date,
    }
    score = score_result(result, args.query, args.llm)
    import json
    print(json.dumps(score, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
