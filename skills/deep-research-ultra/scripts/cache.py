"""
Deep Research Ultra v4.0 — LRU 缓存系统

特性：
- TTL（Time-To-Live）：默认 1 小时过期
- Maxsize：默认 100MB，超出后按 LRU 策略淘汰
- 线程安全（适用于多线程并发搜索）
- 持久化到磁盘（~/.cache/deep-research/）
- 缓存键包含：query + sources + language + region + 时间范围
- 缓存统计：命中率、大小、条目数

修复 v3.2.0 的问题：
- v3 只有 TTL 没有 maxsize → v4 增加 maxsize 限制
- v3 缓存键不含语言/区域参数 → v4 包含完整参数
- v3 没有缓存统计 → v4 提供 stats() 方法
"""

import hashlib
import json
import os
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# 缓存配置
# ============================================================

CACHE_DIR = Path.home() / '.cache' / 'deep-research'
DEFAULT_TTL = timedelta(hours=1)
DEFAULT_MAX_SIZE_MB = 100  # 默认 100MB
DEFAULT_MAX_ENTRIES = 1000  # 默认最多 1000 条


# ============================================================
# LRU 缓存实现
# ============================================================

class LRUCache:
    """
    磁盘 LRU 缓存

    - 每个缓存项存储为单独的 JSON 文件
    - 文件名 = MD5(缓存键)
    - 元数据（last_access、size）存在文件内部
    - 淘汰策略：TTL 过期 + LRU 最近最少使用 + Maxsize 限制
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        ttl: timedelta = DEFAULT_TTL,
        max_size_mb: int = DEFAULT_MAX_SIZE_MB,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ):
        """
        Args:
            cache_dir: 缓存目录（默认 ~/.cache/deep-research/）
            ttl: 缓存生存时间
            max_size_mb: 最大缓存大小（MB）
            max_entries: 最大缓存条目数
        """
        self.cache_dir = cache_dir or CACHE_DIR
        self.ttl = ttl
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_entries = max_entries
        self._lock = threading.Lock()
        # 内存中的访问记录（用于 LRU 决策）
        self._access_record: Dict[str, float] = {}
        # 统计
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evicted_ttl': 0,
            'evicted_lru': 0,
            'evicted_size': 0,
        }

    # ------------------------------------------------------------
    # 缓存键
    # ------------------------------------------------------------

    @staticmethod
    def make_key(
        query: str,
        sources: Optional[List[str]] = None,
        language: str = '',
        region: str = '',
        **kwargs,
    ) -> str:
        """
        生成缓存键

        修复 v3 问题：v3 缓存键不含语言/区域参数，导致跨区域调研结果错误

        Args:
            query: 搜索关键词
            sources: 引擎列表（排序后参与哈希）
            language: 语言（zh/en）
            region: 区域（cn/global）
            **kwargs: 其他影响结果的参数

        Returns:
            MD5 哈希字符串
        """
        parts = [query.strip().lower()]
        if sources:
            parts.append(','.join(sorted(sources)))
        if language:
            parts.append(f'lang={language}')
        if region:
            parts.append(f'region={region}')
        # 其他参数按 key 排序
        for k in sorted(kwargs.keys()):
            v = kwargs[k]
            if v is not None and v != '':
                parts.append(f'{k}={v}')
        return hashlib.md5('|'.join(parts).encode('utf-8')).hexdigest()

    # ------------------------------------------------------------
    # 读写操作
    # ------------------------------------------------------------

    def get(self, key: str) -> Optional[Dict]:
        """
        读取缓存

        Returns:
            缓存数据，未命中或已过期返回 None
        """
        cache_file = self.cache_dir / f'{key}.json'
        with self._lock:
            if not cache_file.exists():
                self._stats['misses'] += 1
                return None
            try:
                data = json.loads(cache_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                # 损坏的缓存文件，删除
                try:
                    cache_file.unlink()
                except OSError:
                    pass
                self._stats['misses'] += 1
                return None

            # TTL 检查
            cached_at_str = data.get('_cached_at', '')
            try:
                cached_at = datetime.fromisoformat(cached_at_str)
                if datetime.now() - cached_at > self.ttl:
                    # 已过期，删除
                    try:
                        cache_file.unlink()
                    except OSError:
                        pass
                    self._stats['evicted_ttl'] += 1
                    self._stats['misses'] += 1
                    return None
            except ValueError:
                # 时间格式错误，视为过期
                try:
                    cache_file.unlink()
                except OSError:
                    pass
                self._stats['evicted_ttl'] += 1
                self._stats['misses'] += 1
                return None

            # 更新访问时间
            current_time = time.time()
            self._access_record[key] = current_time
            # 更新文件中的访问时间（不影响 _cached_at）
            data['_last_access'] = datetime.now().isoformat()
            try:
                cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            except OSError:
                pass

            self._stats['hits'] += 1
            # 返回时移除内部字段
            result = {k: v for k, v in data.items() if not k.startswith('_')}
            return result

    def set(self, key: str, data: Dict) -> None:
        """
        写入缓存

        会触发清理：
        - 超过 max_entries 时按 LRU 淘汰
        - 超过 max_size_bytes 时按 LRU 淘汰
        """
        with self._lock:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            # 写入新缓存
            cache_file = self.cache_dir / f'{key}.json'
            data_to_write = dict(data)
            data_to_write['_cached_at'] = datetime.now().isoformat()
            data_to_write['_last_access'] = datetime.now().isoformat()
            try:
                cache_file.write_text(
                    json.dumps(data_to_write, ensure_ascii=False),
                    encoding='utf-8'
                )
            except OSError:
                return

            # 更新访问记录
            self._access_record[key] = time.time()

            # 触发清理
            self._evict_if_needed()

    def invalidate(self, key: str) -> bool:
        """使特定缓存项失效"""
        cache_file = self.cache_dir / f'{key}.json'
        with self._lock:
            if cache_file.exists():
                try:
                    cache_file.unlink()
                    self._access_record.pop(key, None)
                    return True
                except OSError:
                    return False
            return False

    def clear(self) -> int:
        """清空所有缓存，返回删除的条目数"""
        count = 0
        with self._lock:
            if self.cache_dir.exists():
                for cache_file in self.cache_dir.glob('*.json'):
                    try:
                        cache_file.unlink()
                        count += 1
                    except OSError:
                        continue
            self._access_record.clear()
            # 重置统计
            self._stats = {
                'hits': 0, 'misses': 0,
                'evicted_ttl': 0, 'evicted_lru': 0, 'evicted_size': 0,
            }
        return count

    # ------------------------------------------------------------
    # 清理策略
    # ------------------------------------------------------------

    def _evict_if_needed(self) -> None:
        """按需淘汰缓存（在锁内调用）"""
        # 获取所有缓存项及其元数据
        entries = []
        total_size = 0
        for cache_file in self.cache_dir.glob('*.json'):
            try:
                stat = cache_file.stat()
                key = cache_file.stem
                # 优先使用内存访问记录，回退到文件修改时间
                last_access = self._access_record.get(key, stat.st_mtime)
                entries.append((key, cache_file, last_access, stat.st_size))
                total_size += stat.st_size
            except OSError:
                continue

        # 按最后访问时间升序排序（最旧的在前）
        entries.sort(key=lambda x: x[2])

        # 检查是否需要淘汰
        need_evict_by_count = len(entries) > self.max_entries
        need_evict_by_size = total_size > self.max_size_bytes

        if not (need_evict_by_count or need_evict_by_size):
            return

        # 淘汰最旧的项目，直到满足限制
        evicted = 0
        for key, cache_file, _, size in entries:
            if not (need_evict_by_count or need_evict_by_size):
                break
            try:
                cache_file.unlink()
                self._access_record.pop(key, None)
                total_size -= size
                evicted += 1
                if need_evict_by_count and len(entries) - evicted <= self.max_entries:
                    need_evict_by_count = False
                if need_evict_by_size and total_size <= self.max_size_bytes:
                    need_evict_by_size = False
                if need_evict_by_count:
                    self._stats['evicted_lru'] += 1
                else:
                    self._stats['evicted_size'] += 1
            except OSError:
                continue

    # ------------------------------------------------------------
    # 统计与维护
    # ------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """返回缓存统计"""
        with self._lock:
            total = self._stats['hits'] + self._stats['misses']
            hit_rate = (self._stats['hits'] / total * 100) if total > 0 else 0.0
            # 计算当前大小
            current_size = 0
            entry_count = 0
            if self.cache_dir.exists():
                for cache_file in self.cache_dir.glob('*.json'):
                    try:
                        current_size += cache_file.stat().st_size
                        entry_count += 1
                    except OSError:
                        continue
            return {
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'hit_rate': round(hit_rate, 2),
                'entries': entry_count,
                'size_mb': round(current_size / (1024 * 1024), 2),
                'max_size_mb': self.max_size_bytes / (1024 * 1024),
                'max_entries': self.max_entries,
                'evicted_ttl': self._stats['evicted_ttl'],
                'evicted_lru': self._stats['evicted_lru'],
                'evicted_size': self._stats['evicted_size'],
                'cache_dir': str(self.cache_dir),
            }

    def cleanup_expired(self) -> int:
        """清理所有过期缓存，返回清理数量"""
        count = 0
        with self._lock:
            if not self.cache_dir.exists():
                return 0
            now = datetime.now()
            for cache_file in self.cache_dir.glob('*.json'):
                try:
                    data = json.loads(cache_file.read_text(encoding='utf-8'))
                    cached_at_str = data.get('_cached_at', '')
                    cached_at = datetime.fromisoformat(cached_at_str)
                    if now - cached_at > self.ttl:
                        cache_file.unlink()
                        self._access_record.pop(cache_file.stem, None)
                        count += 1
                        self._stats['evicted_ttl'] += 1
                except (json.JSONDecodeError, ValueError, OSError):
                    # 损坏的文件也清理
                    try:
                        cache_file.unlink()
                        count += 1
                    except OSError:
                        continue
        return count


# ============================================================
# 全局缓存实例
# ============================================================

_global_cache: Optional[LRUCache] = None


def get_cache() -> LRUCache:
    """获取全局缓存实例（单例）"""
    global _global_cache
    if _global_cache is None:
        _global_cache = LRUCache()
    return _global_cache


def set_cache_config(
    ttl_hours: float = 1.0,
    max_size_mb: int = 100,
    max_entries: int = 1000,
) -> None:
    """配置全局缓存"""
    global _global_cache
    _global_cache = LRUCache(
        ttl=timedelta(hours=ttl_hours),
        max_size_mb=max_size_mb,
        max_entries=max_entries,
    )
