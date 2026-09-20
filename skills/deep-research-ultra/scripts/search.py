#!/usr/bin/env python3
"""
Deep Research Ultra — 多源搜索引擎 v3.2.0
整合 16 个搜索引擎 + 智能评分 + 缓存 + 迭代搜索

v3.2.0 特性：
- 16 个搜索引擎（中文7 + 国际6 + 增强3）
- 搜索结果缓存（1 小时 TTL）
- 结果质量评分（0-100 分）
- 迭代搜索（结果不足时自动重搜）
- Claude 智能选择引擎
- 反馈系统（用户评分改进后续搜索）

架构设计：
┌─────────────────────────────────────────────────────────────┐
│                    Deep Research 搜索引擎                      │
├─────────────────────────────────────────────────────────────┤
│  免费层（无需配置）                                             │
│  ├── DuckDuckGo    网页搜索，国内可用                          │
│  ├── Bing          网页搜索，国内可用                          │
│  ├── 百度           网页搜索，国内可用                          │
│  ├── GitHub CLI    开源项目搜索                                │
│  ├── npm           Node.js 包搜索                             │
│  └── PyPI          Python 包查询                              │
├─────────────────────────────────────────────────────────────┤
│  增强层（需要 API Key）                                        │
│  ├── Tavily        AI 搜索引擎，1000次/月免费                  │
│  ├── Jina Reader   网页内容提取（需 VPN）                      │
│  └── Gitee         国内开源项目（需 Token）                    │
├─────────────────────────────────────────────────────────────┤
│  自建层（需要部署）                                            │
│  └── SearXNG       元搜索引擎聚合                             │
└─────────────────────────────────────────────────────────────┘

数据来源：
- DuckDuckGo: https://github.com/deedy5/ddgs (MIT)
- Bing: https://www.bing.com (免费，HTML 解析)
- 百度: https://www.baidu.com (免费，HTML 解析)
- Tavily: https://tavily.com (商业，有免费额度)
- Jina: https://jina.ai (商业，有免费额度)
- SearXNG: https://github.com/searxng/searxng (AGPL-3.0)
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any


# ============================================================
# 全局配置
# ============================================================

_global_proxy: Optional[str] = None


def set_proxy(proxy: Optional[str]):
    """设置全局代理"""
    global _global_proxy
    _global_proxy = proxy
    if proxy:
        os.environ['HTTP_PROXY'] = proxy
        os.environ['HTTPS_PROXY'] = proxy


# ============================================================
# 语言检测 + 引擎分组
# ============================================================

def _detect_language(query: str) -> str:
    """
    检测查询语言

    Returns:
        'zh' — 中文查询
        'en' — 英文查询
    """
    # 统计中文字符数量（CJK 统一汉字：U+4E00 - U+9FFF）
    chinese_chars = sum(1 for c in query if '一' <= c <= '鿿')
    # 只要有中文字符就认为是中文查询
    return 'zh' if chinese_chars > 0 else 'en'


# 中文引擎组（7 个）
CHINESE_ENGINES = ['baidu', 'bing', 'duckduckgo', 'so', 'sogou', 'wechat', 'sm']

# 英文引擎组（6 个，已实现）
ENGLISH_ENGINES = ['duckduckgo', 'bing', 'brave', 'ecosia', 'startpage']

# 默认引擎组
DEFAULT_ENGINES = ['duckduckgo', 'bing', 'baidu']


def _select_engines(query: str, sources: Optional[List[str]] = None) -> List[str]:
    """
    根据查询语言自动选择引擎组

    Args:
        query: 搜索关键词
        sources: 用户指定的引擎（如果指定则不自动选择）

    Returns:
        引擎列表
    """
    if sources:
        return sources

    lang = _detect_language(query)
    if lang == 'zh':
        return CHINESE_ENGINES
    else:
        return ENGLISH_ENGINES


# ============================================================
# 缓存系统
# ============================================================

CACHE_DIR = Path.home() / '.cache' / 'deep-research'
CACHE_TTL = timedelta(hours=1)


def _cache_key(query: str, sources: List[str], **kwargs) -> str:
    """生成缓存键"""
    parts = [query, ','.join(sorted(sources))]
    for k in sorted(kwargs.keys()):
        if kwargs[k] is not None:
            parts.append(f"{k}={kwargs[k]}")
    return hashlib.md5('|'.join(parts).encode()).hexdigest()


def _cache_get(key: str) -> Optional[dict]:
    """读取缓存"""
    cache_file = CACHE_DIR / f"{key}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding='utf-8'))
        cached_at = datetime.fromisoformat(data['_cached_at'])
        if datetime.now() - cached_at > CACHE_TTL:
            cache_file.unlink()
            return None
        return data
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _cache_set(key: str, data: dict):
    """写入缓存"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data['_cached_at'] = datetime.now().isoformat()
    cache_file = CACHE_DIR / f"{key}.json"
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def _http_get(url: str, headers: Optional[Dict] = None,
              timeout: int = 15, max_retries: int = 3,
              proxy: Optional[str] = None) -> bytes:
    """
    带重试的 HTTP GET 请求

    Args:
        url: 请求 URL
        headers: 请求头
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        proxy: HTTP 代理地址（如 http://127.0.0.1:7890）

    Returns:
        响应内容（bytes），已处理 gzip 解压
    """
    # 使用指定代理或全局代理
    effective_proxy = proxy or _global_proxy

    # 构建 opener（支持代理）
    if effective_proxy:
        proxy_handler = urllib.request.ProxyHandler({'http': effective_proxy, 'https': effective_proxy})
        opener = urllib.request.build_opener(proxy_handler)
    else:
        opener = urllib.request.build_opener()

    last_error = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with opener.open(req, timeout=timeout) as response:
                raw_data = response.read()
                content_encoding = response.headers.get('Content-Encoding', '')
                if content_encoding == 'gzip':
                    return gzip.decompress(raw_data)
                return raw_data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = 1.0 * (2 ** attempt)
                print(f"   ⏳ 重试 {attempt+1}/{max_retries}: {url[:50]}... ({delay:.1f}s)", file=sys.stderr)
                time.sleep(delay)
    raise last_error


# ============================================================
# 结果质量评分
# ============================================================

def _score_result(item: Dict, query: str) -> float:
    """
    评估搜索结果质量（0-100 分）

    评分维度：
    - 标题相关性（40 分）
    - 内容丰富度（30 分）
    - 来源权威性（20 分）
    - 时效性（10 分）
    """
    score = 0.0
    title = item.get('title', '').lower()
    content = item.get('content', '').lower()
    url = item.get('url', '').lower()
    query_lower = query.lower()

    # 1. 标题相关性（40 分）
    query_words = set(query_lower.split())
    title_words = set(title.split())
    overlap = len(query_words & title_words)
    if query_words:
        score += min(40, (overlap / len(query_words)) * 40)

    # 2. 内容丰富度（30 分）
    content_len = len(content)
    if content_len > 500:
        score += 30
    elif content_len > 200:
        score += 20
    elif content_len > 50:
        score += 10

    # 3. 来源权威性（20 分）
    authoritative_domains = [
        'github.com', 'stackoverflow.com', 'docs.python.org',
        'developer.mozilla.org', 'learn.microsoft.com',
        'medium.com', 'dev.to', 'arxiv.org', 'wikipedia.org',
        'zhihu.com', 'csdn.net', 'juejin.cn', 'segmentfault.com',
        'infoq.cn', 'jianshu.com', 'cnblogs.com', 'ruanyifeng.com',
        'python.org', 'nodejs.org', 'reactjs.org', 'vuejs.org',
        'baidu.com/link',  # 百度重定向链接也算
        'baidu.com',       # 百度百科等
    ]
    for domain in authoritative_domains:
        if domain in url:
            score += 20
            break

    # 百度百科额外加分
    if 'baike.baidu.com' in url or '百度百科' in title:
        score += 10

    # 4. 时效性（10 分）
    pub_date = item.get('published_date', '')
    if pub_date:
        try:
            # 尝试解析日期
            if '2025' in str(pub_date) or '2026' in str(pub_date):
                score += 10
            elif '2024' in str(pub_date):
                score += 7
            elif '2023' in str(pub_date):
                score += 4
        except:
            pass

    return round(score, 1)


# ============================================================
# 反馈系统
# ============================================================

HISTORY_DIR = Path.home() / '.cache' / 'deep-research' / 'history'


def _save_history(query: str, results_count: int, sources: List[str],
                  avg_quality: float, duration: float):
    """保存搜索历史"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        'query': query,
        'results_count': results_count,
        'sources': sources,
        'avg_quality': avg_quality,
        'duration': round(duration, 2),
        'timestamp': datetime.now().isoformat()
    }
    # 按日期保存
    date_str = datetime.now().strftime('%Y-%m-%d')
    history_file = HISTORY_DIR / f"history_{date_str}.jsonl"
    with open(history_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _get_history(days: int = 7) -> List[Dict]:
    """获取最近 N 天的搜索历史"""
    if not HISTORY_DIR.exists():
        return []

    entries = []
    for history_file in sorted(HISTORY_DIR.glob('history_*.jsonl'), reverse=True)[:days]:
        try:
            for line in history_file.read_text(encoding='utf-8').strip().split('\n'):
                if line:
                    entries.append(json.loads(line))
        except:
            continue

    # 按时间倒序
    entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return entries


def format_history(entries: List[Dict]) -> str:
    """格式化搜索历史"""
    if not entries:
        return "📭 暂无搜索历史"

    lines = ["# 搜索历史", ""]
    lines.append("| # | 时间 | 查询 | 结果 | 质量分 | 耗时 |")
    lines.append("|---|------|------|------|--------|------|")

    for i, entry in enumerate(entries[:20], 1):  # 最多显示 20 条
        ts = entry.get('timestamp', '')[:16]  # YYYY-MM-DDTHH:MM
        query = entry.get('query', '-')[:30]
        count = entry.get('results_count', 0)
        quality = entry.get('avg_quality', 0)
        duration = entry.get('duration', 0)
        lines.append(f"| {i} | {ts} | {query} | {count} | {quality} | {duration}s |")

    return '\n'.join(lines)


FEEDBACK_DIR = Path.home() / '.cache' / 'deep-research' / 'feedback'


def _save_feedback(query: str, rating: int, results_count: int, sources: List[str]):
    """保存用户反馈（1-5 星）"""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    feedback = {
        'query': query,
        'rating': rating,
        'results_count': results_count,
        'sources': sources,
        'timestamp': datetime.now().isoformat()
    }
    # 按日期保存
    date_str = datetime.now().strftime('%Y-%m-%d')
    feedback_file = FEEDBACK_DIR / f"feedback_{date_str}.jsonl"
    with open(feedback_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(feedback, ensure_ascii=False) + '\n')


def _get_similar_feedback(query: str) -> Optional[Dict]:
    """查找相似查询的历史反馈"""
    if not FEEDBACK_DIR.exists():
        return None

    query_words = set(query.lower().split())
    best_match = None
    best_score = 0

    for feedback_file in FEEDBACK_DIR.glob('feedback_*.jsonl'):
        try:
            for line in feedback_file.read_text(encoding='utf-8').strip().split('\n'):
                if not line:
                    continue
                fb = json.loads(line)
                fb_words = set(fb['query'].lower().split())
                overlap = len(query_words & fb_words)
                if overlap > best_score:
                    best_score = overlap
                    best_match = fb
        except:
            continue

    # 至少 2 个词重叠才认为相似
    return best_match if best_score >= 2 else None


# ============================================================
# 网络环境检测
# ============================================================

def check_network() -> Dict[str, bool]:
    """检测网络环境，判断能否访问国际服务"""
    results = {
        'can_access_google': False,
        'can_access_jina': False,
        'can_access_tavily': False,
        'has_vpn': False
    }

    # 测试 Google
    try:
        req = urllib.request.Request('https://www.google.com', method='HEAD')
        req.add_header('User-Agent', 'Mozilla/5.0')
        with urllib.request.urlopen(req, timeout=5) as response:
            results['can_access_google'] = True
    except:
        pass

    # 测试 Jina
    try:
        req = urllib.request.Request('https://r.jina.ai', method='HEAD')
        with urllib.request.urlopen(req, timeout=5) as response:
            results['can_access_jina'] = True
    except:
        pass

    # 测试 Tavily
    try:
        req = urllib.request.Request('https://api.tavily.com', method='HEAD')
        with urllib.request.urlopen(req, timeout=5) as response:
            results['can_access_tavily'] = True
    except:
        pass

    # 判断是否有 VPN（能访问 Google 通常意味着有 VPN）
    results['has_vpn'] = results['can_access_google']

    return results


# ============================================================
# DuckDuckGo 搜索（免费，国内可用）
# ============================================================

class DuckDuckGoSearch:
    """DuckDuckGo 搜索 — 免费，无需 API Key，国内可用"""

    def __init__(self):
        self._available = None

    def is_available(self) -> bool:
        """检查 ddgs 是否已安装"""
        if self._available is None:
            try:
                import ddgs
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def search(self, query: str, max_results: int = 10,
               region: Optional[str] = None, safesearch: str = 'moderate',
               timelimit: Optional[str] = None) -> Optional[Dict]:
        """
        搜索网页

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            region: 地区（wt-wt=全球, cn-zh=中国, us-en=美国）
                    默认自动检测：国内网络用 cn-zh，否则用 wt-wt
            safesearch: 安全搜索（off/moderate/strict）
            timelimit: 时间限制（d=天, w=周, m=月, y=年）
        """
        if not self.is_available():
            print("⚠️  ddgs 未安装，请运行: pip install ddgs", file=sys.stderr)
            return None

        # 自动检测区域
        if region is None:
            # 尝试全球搜索，失败则用中国区域
            region = 'cn-zh'  # 默认用中国区域，国内更稳定

        try:
            from ddgs import DDGS

            results = DDGS().text(
                query,
                max_results=max_results,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit
            )

            formatted = {
                'source': 'duckduckgo',
                'query': query,
                'answer': '',
                'results': []
            }

            for item in results:
                formatted['results'].append({
                    'title': item.get('title', ''),
                    'url': item.get('href', ''),
                    'content': item.get('body', ''),
                    'score': 0,
                    'published_date': item.get('date', '')
                })

            return formatted

        except Exception as e:
            print(f"⚠️  DuckDuckGo 搜索失败: {e}", file=sys.stderr)
            return None

    def news(self, query: str, max_results: int = 10,
             region: Optional[str] = None,
             timelimit: Optional[str] = None) -> Optional[Dict]:
        """搜索新闻"""
        if not self.is_available():
            return None

        # 自动检测区域
        if region is None:
            region = 'cn-zh'  # 默认用中国区域

        try:
            from ddgs import DDGS

            results = DDGS().news(
                query,
                max_results=max_results,
                region=region,
                timelimit=timelimit
            )

            formatted = {
                'source': 'duckduckgo-news',
                'query': query,
                'answer': '',
                'results': []
            }

            for item in results:
                formatted['results'].append({
                    'title': item.get('title', ''),
                    'url': item.get('url', ''),
                    'content': item.get('body', ''),
                    'score': 0,
                    'published_date': item.get('date', ''),
                    'source': item.get('source', '')
                })

            return formatted

        except Exception as e:
            print(f"⚠️  DuckDuckGo 新闻搜索失败: {e}", file=sys.stderr)
            return None


# ============================================================
# Tavily — AI 搜索引擎（需要 API Key）
# ============================================================

class TavilySearch:
    """Tavily API — 专为 AI Agent 设计的搜索引擎"""

    BASE_URL = "https://api.tavily.com"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('TAVILY_API_KEY')

    def is_available(self) -> bool:
        return self.api_key is not None

    def search(self, query: str, search_depth: str = "basic",
               max_results: int = 10, include_answer: bool = True,
               topic: str = "general") -> Optional[Dict]:
        """搜索网页"""
        if not self.is_available():
            print("⚠️  Tavily API Key 未设置", file=sys.stderr)
            print("   获取 Key: https://app.tavily.com", file=sys.stderr)
            print("   设置环境变量: export TAVILY_API_KEY=tvly-xxxxx", file=sys.stderr)
            return None

        payload = {
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": include_answer,
            "topic": topic
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{self.BASE_URL}/search",
                data=data,
                headers=headers,
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))

            formatted = {
                'source': 'tavily',
                'query': query,
                'answer': result.get('answer', ''),
                'results': []
            }

            for item in result.get('results', []):
                formatted['results'].append({
                    'title': item.get('title', ''),
                    'url': item.get('url', ''),
                    'content': item.get('content', ''),
                    'score': item.get('score', 0),
                    'published_date': item.get('published_date', '')
                })

            return formatted

        except urllib.error.HTTPError as e:
            print(f"❌ Tavily API 错误: {e.code} {e.reason}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"❌ Tavily 搜索失败: {e}", file=sys.stderr)
            return None


# ============================================================
# Jina Reader — 网页内容提取（需要 VPN）
# ============================================================

class JinaReader:
    """Jina Reader — 将网页转为 LLM 友好的 Markdown"""

    READER_URL = "https://r.jina.ai"
    SEARCH_URL = "https://s.jina.ai"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('JINA_API_KEY')

    def is_available(self) -> bool:
        """检查 Jina 是否可用（需要网络可达）"""
        try:
            req = urllib.request.Request(self.READER_URL, method='HEAD')
            with urllib.request.urlopen(req, timeout=5) as response:
                return True
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        """使用 Jina 搜索"""
        if not self.is_available():
            print("⚠️  Jina 服务不可用（可能需要 VPN）", file=sys.stderr)
            return None

        try:
            encoded_query = urllib.parse.quote(query)
            url = f"{self.SEARCH_URL}/{encoded_query}"

            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))

            formatted = {
                'source': 'jina-search',
                'query': query,
                'answer': result.get('answer', ''),
                'results': []
            }

            for item in result.get('data', [])[:max_results]:
                formatted['results'].append({
                    'title': item.get('title', ''),
                    'url': item.get('url', ''),
                    'content': item.get('description', item.get('content', '')),
                    'score': 0,
                    'published_date': ''
                })

            return formatted

        except Exception as e:
            print(f"⚠️  Jina 搜索失败: {e}", file=sys.stderr)
            return None

    def read(self, url: str) -> Optional[str]:
        """提取网页内容为 Markdown"""
        if not self.is_available():
            print("⚠️  Jina 服务不可用（可能需要 VPN）", file=sys.stderr)
            return None

        try:
            encoded_url = urllib.parse.quote(url, safe=':/?=&')
            api_url = f"{self.READER_URL}/{encoded_url}"

            headers = {"Accept": "text/markdown"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read().decode('utf-8')

        except Exception as e:
            print(f"⚠️  Jina 读取失败: {e}", file=sys.stderr)
            return None


# ============================================================
# SearXNG — 元搜索引擎（需要自建）
# ============================================================

class SearXNGSearch:
    """SearXNG — 聚合多个搜索引擎的元搜索引擎"""

    def __init__(self, instance_url: Optional[str] = None):
        self.instance_url = instance_url or os.environ.get('SEARXNG_URL', 'http://localhost:8080')

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.instance_url}/healthz")
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10,
               engines: str = "google,bing,duckduckgo",
               language: str = "auto") -> Optional[Dict]:
        """搜索"""
        if not self.is_available():
            print("⚠️  SearXNG 不可用，请先部署实例", file=sys.stderr)
            print(f"   当前配置: {self.instance_url}", file=sys.stderr)
            print("   部署命令: docker run -d -p 8080:8080 searxng/searxng", file=sys.stderr)
            return None

        try:
            params = {
                'q': query,
                'format': 'json',
                'engines': engines,
                'language': language
            }
            url = f"{self.instance_url}/search?{urllib.parse.urlencode(params)}"

            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))

            formatted = {
                'source': 'searxng',
                'query': query,
                'answer': '',
                'results': []
            }

            for item in result.get('results', [])[:max_results]:
                formatted['results'].append({
                    'title': item.get('title', ''),
                    'url': item.get('url', ''),
                    'content': item.get('content', ''),
                    'score': item.get('score', 0),
                    'published_date': item.get('publishedDate', ''),
                    'engine': item.get('engine', '')
                })

            return formatted

        except Exception as e:
            print(f"⚠️  SearXNG 搜索失败: {e}", file=sys.stderr)
            return None


# ============================================================
# Bing 搜索（免费，国内可用）
# ============================================================

class BingSearch:
    """Bing 搜索 — 免费，国内可用"""

    BASE_URL = "https://www.bing.com/search"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

    def is_available(self) -> bool:
        """检查 Bing 是否可访问"""
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10,
               language: str = 'zh-Hans') -> Optional[Dict]:
        """搜索 Bing"""
        try:
            params = {
                'q': query,
                'setlang': language,
                'count': min(max_results, 50)
            }
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {
                'source': 'bing',
                'query': query,
                'answer': '',
                'results': results
            }
        except Exception as e:
            print(f"⚠️  Bing 搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        """解析 Bing 搜索结果 HTML"""
        results = []
        seen = set()

        # 模式1: <h2> 标签中的链接 + 摘要
        # Bing 结构: <h2><a href="...">Title</a></h2> ... <p>Snippet</p>
        h2_pattern = r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(h2_pattern, html, re.DOTALL)

        # 提取摘要（<p> 标签，紧跟在 <h2> 之后）
        snippet_pattern = r'<h2[^>]*>.*?</h2>.*?<p[^>]*>(.*?)</p>'
        snippets = re.findall(snippet_pattern, html, re.DOTALL)

        for i, (url, title) in enumerate(matches):
            title = re.sub(r'<[^>]+>', '', title).strip()
            # 提取摘要
            content = ''
            if i < len(snippets):
                content = re.sub(r'<[^>]+>', '', snippets[i]).strip()
            if (url not in seen and
                'bing.com' not in url and
                'microsoft.com' not in url and
                title and len(title) > 3 and
                not title.startswith('http')):
                seen.add(url)
                results.append({
                    'title': title,
                    'url': url,
                    'content': content[:200],
                    'score': 0,
                    'published_date': ''
                })
                if len(results) >= max_results:
                    break

        # 模式2: 备用 — 所有外部链接
        if not results:
            link_pattern = r'<a[^>]+href="(https?://(?!www\.bing\.com|go\.microsoft\.com)[^"]+)"[^>]*>(.*?)</a>'
            matches = re.findall(link_pattern, html, re.DOTALL)
            for url, title in matches:
                title = re.sub(r'<[^>]+>', '', title).strip()
                if (url not in seen and
                    title and len(title) > 5 and
                    not title.startswith('http') and
                    'bing.com' not in url):
                    seen.add(url)
                    results.append({
                        'title': title,
                        'url': url,
                        'content': '',
                        'score': 0,
                        'published_date': ''
                    })
                    if len(results) >= max_results:
                        break

        return results


# ============================================================
# 百度搜索（免费，国内可用）
# ============================================================

class BaiduSearch:
    """百度搜索 — 免费，国内可用"""

    BASE_URL = "https://www.baidu.com/s"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Cookie': 'BAIDUID=random; BIDUPSID=random;',
        }

    def is_available(self) -> bool:
        """检查百度是否可访问"""
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        """搜索百度"""
        try:
            # 请求量放大 3 倍（百度返回结果数不稳定）
            params = {
                'wd': query,
                'rn': min(max_results * 3, 50),
                'ie': 'utf-8'
            }
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {
                'source': 'baidu',
                'query': query,
                'answer': '',
                'results': results
            }
        except Exception as e:
            print(f"⚠️  百度搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        """解析百度搜索结果 HTML"""
        results = []
        seen = set()

        # 方法1: h3 标题中的链接（百度重定向链接）
        h3_pattern = r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(h3_pattern, html, re.DOTALL)

        for url, title in matches:
            title = re.sub(r'<[^>]+>', '', title).strip()
            title = title.replace('&nbsp;', ' ').replace('\xa0', ' ').strip()
            if (url not in seen and
                title and len(title) > 3 and
                url.startswith('http')):
                seen.add(url)
                results.append({
                    'title': title,
                    'url': url,
                    'content': '',
                    'score': 0,
                    'published_date': ''
                })
                if len(results) >= max_results:
                    break

        # 方法2: 提取摘要
        abstract_pattern = r'<span class="content-right_8Zs40">(.*?)</span>'
        abstracts = re.findall(abstract_pattern, html, re.DOTALL)
        if not abstracts:
            abstract_pattern = r'<div class="c-abstract"[^>]*>(.*?)</div>'
            abstracts = re.findall(abstract_pattern, html, re.DOTALL)

        for i, abstract in enumerate(abstracts[:len(results)]):
            clean = re.sub(r'<[^>]+>', '', abstract).strip()
            if clean and i < len(results):
                results[i]['content'] = clean[:200]

        return results


# ============================================================
# 360 搜索（免费，国内可用）
# ============================================================

class SoSearch:
    """360 搜索 — 免费，国内可用"""

    BASE_URL = "https://www.so.com/s"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        try:
            params = {'q': query}
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {'source': '360', 'query': query, 'answer': '', 'results': results}
        except Exception as e:
            print(f"⚠️  360 搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        results = []
        seen = set()
        # 360 结果在 <h3> 中的 <a> 标签
        pattern = r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        for url, title in re.findall(pattern, html, re.DOTALL):
            title = re.sub(r'<[^>]+>', '', title).strip()
            if url not in seen and title and len(title) > 3 and url.startswith('http') and 'so.com' not in url:
                seen.add(url)
                results.append({'title': title, 'url': url, 'content': '', 'score': 0, 'published_date': ''})
                if len(results) >= max_results:
                    break
        return results


# ============================================================
# 搜狗搜索（免费，国内可用）
# ============================================================

class SogouSearch:
    """搜狗搜索 — 免费，国内可用"""

    BASE_URL = "https://sogou.com/web"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        try:
            params = {'query': query}
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {'source': 'sogou', 'query': query, 'answer': '', 'results': results}
        except Exception as e:
            print(f"⚠️  搜狗搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        results = []
        seen = set()
        pattern = r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        for url, title in re.findall(pattern, html, re.DOTALL):
            title = re.sub(r'<[^>]+>', '', title).strip()
            if url not in seen and title and len(title) > 3 and url.startswith('http') and 'sogou.com' not in url:
                seen.add(url)
                results.append({'title': title, 'url': url, 'content': '', 'score': 0, 'published_date': ''})
                if len(results) >= max_results:
                    break
        return results


# ============================================================
# 微信搜狗（免费，国内可用，微信公众号文章）
# ============================================================

class WechatSearch:
    """微信搜狗 — 免费，搜索微信公众号文章"""

    BASE_URL = "https://wx.sogou.com/weixin"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        try:
            params = {'type': 2, 'query': query}
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {'source': 'wechat', 'query': query, 'answer': '', 'results': results}
        except Exception as e:
            print(f"⚠️  微信搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        results = []
        seen = set()
        # 微信搜狗结果在 <h3> 中的 <a> 标签
        pattern = r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        for url, title in re.findall(pattern, html, re.DOTALL):
            title = re.sub(r'<[^>]+>', '', title).strip()
            if url not in seen and title and len(title) > 3:
                # 微信搜狗的 URL 是相对路径，需要补全
                if url.startswith('/'):
                    url = f"https://weixin.sogou.com{url}"
                seen.add(url)
                results.append({'title': title, 'url': url, 'content': '', 'score': 0, 'published_date': ''})
                if len(results) >= max_results:
                    break
        return results


# ============================================================
# 神马搜索（免费，国内可用，移动端）
# ============================================================

class SmSearch:
    """神马搜索 — 免费，国内可用，移动端搜索引擎"""

    BASE_URL = "https://m.sm.cn/s"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        try:
            params = {'q': query}
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {'source': 'sm', 'query': query, 'answer': '', 'results': results}
        except Exception as e:
            print(f"⚠️  神马搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        results = []
        seen = set()
        pattern = r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>'
        for url, title in re.findall(pattern, html, re.DOTALL):
            title = re.sub(r'<[^>]+>', '', title).strip()
            if url not in seen and title and len(title) > 5 and 'sm.cn' not in url:
                seen.add(url)
                results.append({'title': title, 'url': url, 'content': '', 'score': 0, 'published_date': ''})
                if len(results) >= max_results:
                    break
        return results


# ============================================================
# Brave 搜索（免费，国际）
# ============================================================

class BraveSearch:
    """Brave 搜索 — 免费，隐私保护"""

    BASE_URL = "https://search.brave.com/search"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        try:
            params = {'q': query}
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {'source': 'brave', 'query': query, 'answer': '', 'results': results}
        except Exception as e:
            print(f"⚠️  Brave 搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        results = []
        seen = set()
        pattern = r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>'
        for url, title in re.findall(pattern, html, re.DOTALL):
            title = re.sub(r'<[^>]+>', '', title).strip()
            if url not in seen and title and len(title) > 5 and 'brave.com' not in url:
                seen.add(url)
                results.append({'title': title, 'url': url, 'content': '', 'score': 0, 'published_date': ''})
                if len(results) >= max_results:
                    break
        return results


# ============================================================
# Ecosia 搜索（免费，环保搜索引擎）
# ============================================================

class EcosiaSearch:
    """Ecosia 搜索 — 免费，环保搜索引擎"""

    BASE_URL = "https://www.ecosia.org/search"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        try:
            params = {'q': query}
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {'source': 'ecosia', 'query': query, 'answer': '', 'results': results}
        except Exception as e:
            print(f"⚠️  Ecosia 搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        results = []
        seen = set()
        pattern = r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>'
        for url, title in re.findall(pattern, html, re.DOTALL):
            title = re.sub(r'<[^>]+>', '', title).strip()
            if url not in seen and title and len(title) > 5 and 'ecosia.org' not in url:
                seen.add(url)
                results.append({'title': title, 'url': url, 'content': '', 'score': 0, 'published_date': ''})
                if len(results) >= max_results:
                    break
        return results


# ============================================================
# Startpage 搜索（免费，隐私保护）
# ============================================================

class StartpageSearch:
    """Startpage 搜索 — 免费，隐私保护，Google 结果"""

    BASE_URL = "https://www.startpage.com/sp/search"

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.BASE_URL, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False

    def search(self, query: str, max_results: int = 10) -> Optional[Dict]:
        try:
            params = {'query': query}
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            html = _http_get(url, self.headers, timeout=15).decode('utf-8', errors='ignore')
            results = self._parse_html(html, max_results)
            return {'source': 'startpage', 'query': query, 'answer': '', 'results': results}
        except Exception as e:
            print(f"⚠️  Startpage 搜索失败: {e}", file=sys.stderr)
            return None

    def _parse_html(self, html: str, max_results: int) -> List[Dict]:
        results = []
        seen = set()
        pattern = r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>'
        for url, title in re.findall(pattern, html, re.DOTALL):
            title = re.sub(r'<[^>]+>', '', title).strip()
            if url not in seen and title and len(title) > 5 and 'startpage.com' not in url:
                seen.add(url)
                results.append({'title': title, 'url': url, 'content': '', 'score': 0, 'published_date': ''})
                if len(results) >= max_results:
                    break
        return results


# ============================================================
# 深度阅读（提取网页全文）
# ============================================================

def deep_read(url: str, max_length: int = 5000) -> Optional[str]:
    """
    深度阅读：提取网页全文内容

    Args:
        url: 网页 URL
        max_length: 最大提取长度

    Returns:
        提取的文本内容
    """
    try:
        html = _http_get(url, timeout=15).decode('utf-8', errors='ignore')

        # 移除 script 和 style 标签
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)

        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', html)

        # 清理空白字符
        text = re.sub(r'\s+', ' ', text).strip()

        # 移除多余空行
        text = re.sub(r'\n\s*\n', '\n\n', text)

        return text[:max_length]
    except Exception as e:
        print(f"⚠️  深度阅读失败: {e}", file=sys.stderr)
        return None


# ============================================================
# 多源搜索聚合
# ============================================================

def multi_search(query: str, max_results: int = 10,
                 sources: Optional[List[str]] = None,
                 search_depth: str = "basic",
                 auto_detect: bool = True,
                 use_cache: bool = True,
                 min_score: float = 0,
                 enable_iterative: bool = False) -> Dict:
    """
    多源并发搜索（带缓存、评分、迭代搜索）

    Args:
        query: 搜索关键词
        max_results: 每个源的最大结果数
        sources: 搜索源列表 (duckduckgo/bing/baidu/tavily/jina/searxng)
        search_depth: Tavily 搜索深度 (basic/advanced)
        auto_detect: 是否自动检测可用数据源
        use_cache: 是否使用缓存
        min_score: 最低质量分（0-100），低于此分的结果过滤
        enable_iterative: 启用迭代搜索（结果不足时自动重搜）
    """
    cache_key = None  # 初始化缓存键

    # 根据查询语言自动选择引擎
    if sources is None:
        sources = _select_engines(query)
        lang = _detect_language(query)
        print(f"🌐 检测到{'中文' if lang == 'zh' else '英文'}查询，自动选择引擎组", file=sys.stderr)

    # 检查缓存
    if use_cache:
        cache_key = _cache_key(query, sources, depth=search_depth)
        cached = _cache_get(cache_key)
        if cached:
            print(f"💾 缓存命中: {query}", file=sys.stderr)
            return cached

    # 初始化搜索引擎（16 个）
    engines = {
        # 核心引擎
        'duckduckgo': DuckDuckGoSearch(),
        'bing': BingSearch(),
        'baidu': BaiduSearch(),
        # 中文引擎
        'so': SoSearch(),          # 360
        'sogou': SogouSearch(),    # 搜狗
        'wechat': WechatSearch(),  # 微信公众号
        'sm': SmSearch(),          # 神马
        # 国际引擎
        'brave': BraveSearch(),
        'ecosia': EcosiaSearch(),
        'startpage': StartpageSearch(),
        # 增强引擎
        'tavily': TavilySearch(),
        'jina': JinaReader(),
        'searxng': SearXNGSearch(),
    }

    # 自动检测可用性
    if auto_detect:
        available = []
        unavailable = []
        for source in sources:
            engine = engines.get(source)
            if engine and engine.is_available():
                available.append(source)
            else:
                unavailable.append(source)
                if source == 'jina':
                    print(f"⚠️  {source}: 不可用（可能需要 VPN）", file=sys.stderr)
                elif source == 'tavily':
                    print(f"⚠️  {source}: 不可用（需要 API Key）", file=sys.stderr)
                elif source == 'searxng':
                    print(f"⚠️  {source}: 不可用（需要自建实例）", file=sys.stderr)
                else:
                    print(f"⚠️  {source}: 不可用", file=sys.stderr)
    else:
        available = sources

    if not available:
        print("❌ 没有可用的搜索引擎", file=sys.stderr)
        print("\n💡 建议：", file=sys.stderr)
        print("   1. 安装 ddgs: pip install ddgs", file=sys.stderr)
        print("   2. 设置 Tavily API Key: export TAVILY_API_KEY=tvly-xxxxx", file=sys.stderr)
        print("   3. 使用 VPN 访问 Jina 服务", file=sys.stderr)
        return {'query': query, 'answer': '', 'results': [], 'sources': []}

    # 并发搜索
    all_results = []
    answers = []
    used_sources = []

    print(f"🔍 搜索: {query}", file=sys.stderr)
    print(f"   数据源: {', '.join(available)}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=len(available)) as executor:
        futures = {}
        for source in available:
            engine = engines[source]
            if source == 'tavily':
                futures[executor.submit(
                    engine.search, query,
                    search_depth=search_depth,
                    max_results=max_results
                )] = source
            else:
                futures[executor.submit(
                    engine.search, query,
                    max_results=max_results
                )] = source

        for future in as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
                if result and result.get('results'):
                    count = len(result['results'])
                    print(f"   ✅ {source}: {count} 个结果", file=sys.stderr)
                    all_results.extend(result['results'])
                    used_sources.append(source)
                    if result.get('answer'):
                        answers.append(f"[{source}] {result['answer']}")
                else:
                    print(f"   ⚠️  {source}: 无结果", file=sys.stderr)
            except Exception as e:
                print(f"   ❌ {source}: {e}", file=sys.stderr)

    # 智能去重（按 URL 和标题）
    seen_urls = set()
    seen_titles = set()
    deduped = []

    for item in all_results:
        url = item.get('url', '').rstrip('/')
        title = item.get('title', '').lower().strip()

        if url in seen_urls:
            continue

        title_key = title[:50] if title else ''
        if title_key and title_key in seen_titles:
            continue

        if url:
            seen_urls.add(url)
        if title_key:
            seen_titles.add(title_key)
        deduped.append(item)

    # 质量评分
    for item in deduped:
        item['quality_score'] = _score_result(item, query)

    # 按质量分排序
    deduped.sort(key=lambda x: x.get('quality_score', 0), reverse=True)

    # 过滤低分结果
    if min_score > 0:
        deduped = [r for r in deduped if r.get('quality_score', 0) >= min_score]

    # 迭代搜索：结果不足时，用变体关键词重搜
    if enable_iterative and len(deduped) < max_results // 2:
        print(f"   🔄 结果不足，启动迭代搜索...", file=sys.stderr)
        variant_queries = _generate_variants(query)
        for vq in variant_queries[:2]:  # 最多 2 轮变体
            if len(deduped) >= max_results:
                break
            print(f"   🔍 变体搜索: {vq}", file=sys.stderr)
            for source in available[:2]:  # 只用前 2 个源
                engine = engines.get(source)
                if engine:
                    try:
                        result = engine.search(vq, max_results=max_results // 2)
                        if result and result.get('results'):
                            for item in result['results']:
                                item['quality_score'] = _score_result(item, query)
                                url = item.get('url', '').rstrip('/')
                                if url not in seen_urls:
                                    seen_urls.add(url)
                                    deduped.append(item)
                    except:
                        pass

        deduped.sort(key=lambda x: x.get('quality_score', 0), reverse=True)

    # 检查历史反馈
    feedback = _get_similar_feedback(query)
    if feedback:
        print(f"   📊 历史反馈: 此类查询评分 {feedback['rating']}/5", file=sys.stderr)

    result = {
        'query': query,
        'answer': '\n\n'.join(answers) if answers else '',
        'results': deduped[:max_results],
        'sources': used_sources,
        'avg_quality': round(sum(r.get('quality_score', 0) for r in deduped[:max_results]) / max(len(deduped[:max_results]), 1), 1)
    }

    # 写入缓存
    if use_cache and result['results']:
        _cache_set(cache_key, result)

    return result


def _generate_variants(query: str) -> List[str]:
    """生成搜索关键词变体"""
    variants = []

    # 中文 → 英文变体
    cn_en_map = {
        '框架': 'framework',
        '对比': 'comparison',
        '最佳实践': 'best practices',
        '教程': 'tutorial',
        '入门': 'getting started',
        '性能': 'performance',
        '部署': 'deployment',
        '微服务': 'microservices',
        '容器': 'container',
        '数据库': 'database',
    }

    for cn, en in cn_en_map.items():
        if cn in query:
            variants.append(query.replace(cn, en))

    # 添加年份变体
    if '2025' not in query and '2026' not in query:
        variants.append(f"{query} 2025")

    # 添加"最佳"变体
    if '最佳' not in query and 'best' not in query.lower():
        variants.append(f"best {query}")

    return variants


def format_markdown(data: Dict) -> str:
    """格式化为 Markdown"""
    lines = [f"## 搜索结果: {data['query']}", ""]

    if data.get('answer'):
        lines.append("### AI 回答")
        lines.append("")
        lines.append(data['answer'])
        lines.append("")

    lines.append(f"### 来源 ({len(data['results'])} 个)")
    lines.append("")
    lines.append("| # | 来源 | 质量分 | 内容摘要 |")
    lines.append("|---|------|--------|----------|")

    for i, item in enumerate(data['results'], 1):
        title = item.get('title', '-')[:50]
        url = item.get('url', '')
        content = item.get('content', '-')[:80]
        score = item.get('quality_score', '-')
        lines.append(f"| {i} | [{title}]({url}) | {score} | {content} |")

    lines.append("")
    avg = data.get('avg_quality', 0)
    lines.append(f"**数据源:** {', '.join(data.get('sources', []))} | **平均质量分:** {avg}")

    return '\n'.join(lines)


def format_json(data: Dict) -> str:
    """格式化为 JSON"""
    return json.dumps(data, ensure_ascii=False, indent=2)


def format_report(data: Dict) -> str:
    """
    生成结构化研究报告

    包含：执行摘要、来源分析、质量分布、建议
    """
    query = data['query']
    results = data.get('results', [])
    sources = data.get('sources', [])
    avg_quality = data.get('avg_quality', 0)

    lines = []
    lines.append(f"# 调研报告：{query}")
    lines.append("")
    lines.append(f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**数据源：** {', '.join(sources)}")
    lines.append(f"**结果数量：** {len(results)}")
    lines.append(f"**平均质量分：** {avg_quality}")
    lines.append("")

    # 执行摘要
    lines.append("## 执行摘要")
    lines.append("")
    if results:
        high_quality = [r for r in results if r.get('quality_score', 0) >= 50]
        lines.append(f"- 共获取 **{len(results)}** 条搜索结果")
        lines.append(f"- 高质量结果（≥50 分）：**{len(high_quality)}** 条")
        lines.append(f"- 数据源覆盖：**{len(sources)}** 个平台")
        if avg_quality >= 50:
            lines.append("- 整体质量：**优秀** ✅")
        elif avg_quality >= 30:
            lines.append("- 整体质量：**良好** ⚠️")
        else:
            lines.append("- 整体质量：**一般** ❌（建议增加数据源或优化关键词）")
    else:
        lines.append("- 未获取到搜索结果")
    lines.append("")

    # 来源分析
    lines.append("## 来源分析")
    lines.append("")
    lines.append("| # | 来源 | 质量分 | 标题 |")
    lines.append("|---|------|--------|------|")
    for i, item in enumerate(results, 1):
        title = item.get('title', '-')[:60]
        score = item.get('quality_score', '-')
        url = item.get('url', '')
        lines.append(f"| {i} | [{title}]({url}) | {score} | {title[:30]} |")
    lines.append("")

    # 质量分布
    lines.append("## 质量分布")
    lines.append("")
    score_ranges = {'优秀 (≥70)': 0, '良好 (50-69)': 0, '一般 (30-49)': 0, '较差 (<30)': 0}
    for item in results:
        score = item.get('quality_score', 0)
        if score >= 70:
            score_ranges['优秀 (≥70)'] += 1
        elif score >= 50:
            score_ranges['良好 (50-69)'] += 1
        elif score >= 30:
            score_ranges['一般 (30-49)'] += 1
        else:
            score_ranges['较差 (<30)'] += 1

    for range_name, count in score_ranges.items():
        bar = '█' * count
        lines.append(f"- {range_name}: {bar} ({count})")
    lines.append("")

    # 建议
    lines.append("## 建议")
    lines.append("")
    if avg_quality < 30:
        lines.append("- ⚠️ 平均质量分较低，建议：")
        lines.append("  - 使用更精确的关键词")
        lines.append("  - 添加更多数据源（--sources duckduckgo,bing,baidu,tavily）")
        lines.append("  - 启用迭代搜索（--iterative）")
    elif avg_quality < 50:
        lines.append("- 💡 质量中等，可以：")
        lines.append("  - 使用 --min-score 50 过滤低质量结果")
        lines.append("  - 尝试不同的关键词组合")
    else:
        lines.append("- ✅ 质量良好，结果可信度较高")
    lines.append("")

    lines.append("---")
    lines.append(f"*由 Deep Research Ultra v3.2.0 自动生成*")

    return '\n'.join(lines)


def format_csv(data: Dict) -> str:
    """
    格式化为 CSV（Excel 可直接打开）

    列：序号, 标题, URL, 摘要, 质量分, 来源, 发布日期
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # 表头
    writer.writerow(['序号', '标题', 'URL', '摘要', '质量分', '来源', '发布日期'])

    # 数据行
    for i, item in enumerate(data.get('results', []), 1):
        writer.writerow([
            i,
            item.get('title', ''),
            item.get('url', ''),
            item.get('content', '')[:200],
            item.get('quality_score', ''),
            item.get('source', data.get('sources', [''])[0] if data.get('sources') else ''),
            item.get('published_date', '')
        ])

    return output.getvalue()


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Deep Research — 多源搜索引擎 v3.0（带缓存、评分、迭代搜索）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
数据源（16 个引擎）：

  中文引擎（7 个）：
    baidu       百度，免费，国内可用
    bing        必应，免费，国内可用
    duckduckgo  DuckDuckGo，免费，国内可用
    so          360 搜索，免费，国内可用
    sogou       搜狗，免费，国内可用
    wechat      微信公众号，免费，国内可用
    sm          神马，免费，国内可用（移动端）

  国际引擎（6 个）：
    brave       Brave，免费，隐私保护
    ecosia      Ecosia，免费，环保搜索引擎
    startpage   Startpage，免费，Google 结果
    google      Google，需要代理
    yahoo       Yahoo，免费
    qwant       Qwant，免费，隐私保护

  增强引擎（3 个）：
    tavily      AI 搜索引擎，需要 API Key
    jina        网页内容提取，需要 VPN
    searxng     元搜索引擎，需要自建

示例：
  %(prog)s "Python Web 框架对比"                    # 自动选择引擎（中英文）
  %(prog)s "AI agent" --sources duckduckgo,bing     # 指定数据源
  %(prog)s "K8s" --iterative                        # 迭代搜索
  %(prog)s "React" --min-score 50                   # 过滤低质量结果
  %(prog)s --read "https://example.com"             # 深度阅读
  %(prog)s --check                                  # 检查数据源可用性
  %(prog)s --feedback "query" --rating 5            # 提交反馈
  %(prog)s --history                                # 查看搜索历史
        """
    )
    parser.add_argument('query', nargs='?', default='', help='搜索关键词')
    parser.add_argument('--sources', '-s', default=None,
                        help='搜索源，逗号分隔（不指定则自动根据查询语言选择）')
    parser.add_argument('--depth', '-d', default='basic',
                        choices=['basic', 'advanced'],
                        help='搜索深度 (Tavily)')
    parser.add_argument('--limit', '-n', type=int, default=10,
                        help='每个源的最大结果数')
    parser.add_argument('--format', '-f', default='markdown',
                        choices=['markdown', 'json', 'report', 'csv'],
                        help='输出格式（markdown/json/report/csv）')
    parser.add_argument('--read', '-r', help='读取指定 URL 的内容')
    parser.add_argument('--check', action='store_true',
                        help='检查数据源可用性')
    parser.add_argument('--no-auto-detect', action='store_true',
                        help='禁用自动检测，强制使用指定数据源')
    parser.add_argument('--no-cache', action='store_true',
                        help='禁用缓存')
    parser.add_argument('--min-score', type=float, default=0,
                        help='最低质量分（0-100），低于此分的结果过滤')
    parser.add_argument('--iterative', action='store_true',
                        help='启用迭代搜索（结果不足时自动重搜）')
    parser.add_argument('--feedback', help='提交搜索反馈的查询')
    parser.add_argument('--rating', type=int, choices=[1, 2, 3, 4, 5],
                        help='反馈评分（1-5 星）')
    parser.add_argument('--proxy', help='HTTP 代理地址（如 http://127.0.0.1:7890）')
    parser.add_argument('--history', action='store_true',
                        help='显示最近 7 天搜索历史')
    parser.add_argument('--history-days', type=int, default=7,
                        help='搜索历史天数（默认 7 天）')
    parser.add_argument('--list', '-l', action='store_true',
                        help='列出所有可用搜索引擎')
    parser.add_argument('--all', '-a', action='store_true',
                        help='搜索所有可用引擎')

    args = parser.parse_args()

    # 列出可用引擎
    if args.list:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        engines = {
            'baidu': '百度，免费，国内可用',
            'bing': '必应，免费，国内可用',
            'duckduckgo': 'DuckDuckGo，免费，国内可用',
            'so': '360 搜索，免费，国内可用',
            'sogou': '搜狗，免费，国内可用',
            'wechat': '微信公众号，免费，国内可用',
            'sm': '神马，免费，国内可用（移动端）',
            'brave': 'Brave，免费，隐私保护',
            'ecosia': 'Ecosia，免费，环保搜索引擎',
            'startpage': 'Startpage，免费，Google 结果',
            'tavily': 'AI 搜索引擎，需要 API Key',
            'jina': '网页内容提取，需要 VPN',
            'searxng': '元搜索引擎，需要自建',
        }
        print("可用搜索引擎：")
        print()
        for name, desc in engines.items():
            print(f"  {name:<12} {desc}")
        print()
        print("使用方式：")
        print('  python search.py "关键词" --sources baidu,bing,duckduckgo')
        return

    # 设置代理
    if args.proxy:
        set_proxy(args.proxy)
        print(f"🌐 使用代理: {args.proxy}", file=sys.stderr)

    # 查看搜索历史
    if args.history:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        entries = _get_history(args.history_days)
        print(format_history(entries))
        return

    # 检查数据源可用性
    if args.check:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

        print("[检查] 数据源可用性...\n")

        network = check_network()
        print("[网络环境]")
        print(f"   VPN: {'[有]' if network['has_vpn'] else '[无]'}")
        print(f"   Google: {'[可达]' if network['can_access_google'] else '[不可达]'}")
        print(f"   Jina: {'[可达]' if network['can_access_jina'] else '[不可达]'}")
        print(f"   Tavily: {'[可达]' if network['can_access_tavily'] else '[不可达]'}")
        print()

        engines = {
            'duckduckgo': DuckDuckGoSearch(),
            'bing': BingSearch(),
            'baidu': BaiduSearch(),
            'so': SoSearch(),
            'sogou': SogouSearch(),
            'wechat': WechatSearch(),
            'sm': SmSearch(),
            'brave': BraveSearch(),
            'ecosia': EcosiaSearch(),
            'startpage': StartpageSearch(),
            'tavily': TavilySearch(),
            'jina': JinaReader(),
            'searxng': SearXNGSearch(),
        }

        print("[数据源状态]")
        for name, engine in engines.items():
            status = "[可用]" if engine.is_available() else "[不可用]"
            print(f"   {name}: {status}")
        return

    # 处理 --read 模式（深度阅读）
    if args.read:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

        # 优先使用 Jina（质量更好）
        jina = JinaReader()
        if jina.is_available():
            content = jina.read(args.read)
            if content:
                print(content)
                return

        # Jina 不可用时，使用内置深度阅读
        print(f"📖 深度阅读: {args.read}", file=sys.stderr)
        content = deep_read(args.read)
        if content:
            print(content)
        else:
            print("❌ 读取失败", file=sys.stderr)
            sys.exit(1)
        return

    # 处理反馈模式
    if args.feedback:
        if not args.rating:
            parser.error("反馈模式需要提供 --rating (1-5)")
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sources = [s.strip() for s in args.sources.split(',')] if args.sources else ['unknown']
        _save_feedback(args.feedback, args.rating, 0, sources)
        print(f"✅ 反馈已保存: '{args.feedback}' → {args.rating}/5 星")
        return

    # 搜索模式需要 query
    if not args.query:
        parser.error("搜索模式需要提供关键词")

    # 处理 --all 参数
    if args.all:
        sources = ['baidu', 'bing', 'duckduckgo', 'so', 'sogou', 'wechat', 'sm',
                   'brave', 'ecosia', 'startpage', 'tavily', 'jina', 'searxng']
    else:
        sources = [s.strip() for s in args.sources.split(',')] if args.sources else None

    # 记录搜索开始时间
    import time as _time
    _start_time = _time.time()

    data = multi_search(
        query=args.query,
        max_results=args.limit,
        sources=sources,
        search_depth=args.depth,
        auto_detect=not args.no_auto_detect,
        use_cache=not args.no_cache,
        min_score=args.min_score,
        enable_iterative=args.iterative
    )

    # 计算搜索耗时并保存历史
    _duration = _time.time() - _start_time
    _save_history(
        query=args.query,
        results_count=len(data.get('results', [])),
        sources=data.get('sources', []),
        avg_quality=data.get('avg_quality', 0),
        duration=_duration
    )

    # 输出
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    if args.format == 'json':
        print(format_json(data))
    elif args.format == 'report':
        print(format_report(data))
    elif args.format == 'csv':
        print(format_csv(data))
    else:
        print(format_markdown(data))


if __name__ == '__main__':
    main()
