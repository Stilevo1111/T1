#!/usr/bin/env python3
"""
Unified Cache Service - consolidates all caching in the codebase.

Provides a single interface for:
- User data cache (with dirty tracking)
- API response cache (TTL-based)
- Negative cache (404s)
- Image/icon cache (LRU eviction)
- Config cache
- Top lists cache
- Rate limiting (token bucket)
- Retry decorator
- Circuit breaker
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from typing import Any, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    ttl: int = 300
    max_size: int = 1000
    enable_lru: bool = True


@dataclass
class RateLimitConfig:
    requests_per_second: float = 15.0
    burst: int = 30
    window_seconds: int = 60


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: int = 60
    expected_exception: tuple = (Exception,)


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple = (Exception,)


def retry(config: RetryConfig = None):
    """
    Decorator for retrying async functions with exponential backoff.
    
    Usage:
        @retry(RetryConfig(max_attempts=3, base_delay=1.0))
        async def fetch_data(url):
            ...
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e
                    if attempt < config.max_attempts - 1:
                        delay = min(
                            config.base_delay * (config.exponential_base ** attempt),
                            config.max_delay
                        )
                        logger.debug(f"Retry {attempt + 1}/{config.max_attempts} for {func.__name__} after {delay}s: {e}")
                        await asyncio.sleep(delay)
                    else:
                        logger.warning(f"All {config.max_attempts} retries failed for {func.__name__}: {e}")
            raise last_exception
        return wrapper
    return decorator


class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(self, config: CircuitBreakerConfig = None):
        self._config = config or CircuitBreakerConfig()
        self._state = "CLOSED"
        self._failure_count = 0
        self._last_failure_time = 0
        self._lock = threading.Lock()
    
    @property
    def state(self) -> str:
        with self._lock:
            return self._state
    
    def can_execute(self) -> bool:
        with self._lock:
            if self._state == "CLOSED":
                return True
            if self._state == "OPEN":
                if time.time() - self._last_failure_time >= self._config.recovery_timeout:
                    self._state = "HALF_OPEN"
                    return True
                return False
            if self._state == "HALF_OPEN":
                return True
            return False
    
    def record_success(self) -> None:
        with self._lock:
            if self._state == "HALF_OPEN":
                self._state = "CLOSED"
            self._failure_count = 0
    
    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._state == "CLOSED" and self._failure_count >= self._config.failure_threshold:
                self._state = "OPEN"
                self._last_failure_time = time.time()
            elif self._state == "HALF_OPEN":
                self._state = "OPEN"
                self._last_failure_time = time.time()
    
    def reset(self) -> None:
        with self._lock:
            self._state = "CLOSED"
            self._failure_count = 0
            self._last_failure_time = 0


class UnifiedRateLimiter:
    """Thread-safe token bucket rate limiter."""
    
    def __init__(self, config: RateLimitConfig = None):
        self._config = config or RateLimitConfig()
        self._tokens = float(self._config.burst)
        self._last_update = time.monotonic()
        self._lock = threading.Lock()
    
    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_update
        self._tokens = min(
            self._config.burst,
            self._tokens + elapsed * self._config.requests_per_second
        )
        self._last_update = now
    
    def try_acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens without waiting."""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    def get_available(self) -> float:
        """Get current available tokens."""
        with self._lock:
            self._refill()
            return self._tokens
    
    def wait_time(self, tokens: int = 1) -> float:
        """Get time to wait for tokens (seconds)."""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                return 0.0
            needed = tokens - self._tokens
            return needed / self._config.requests_per_second


class UnifiedCache:
    """Thread-safe cache with TTL and LRU eviction."""
    
    def __init__(self, config: CacheConfig = None):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._config = config or CacheConfig()
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None
            return value
    
    def set(self, key: str, value: Any, ttl: int = None) -> None:
        ttl = ttl or self._config.ttl
        with self._lock:
            if self._config.enable_lru and len(self._cache) >= self._config.max_size:
                self._evict_lru()
            self._cache[key] = (value, time.time() + ttl)
    
    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
    
    def _evict_lru(self) -> None:
        if not self._cache:
            return
        oldest_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k][1]
        )[:self._config.max_size // 5]
        for k in oldest_keys:
            del self._cache[k]
    
    def size(self) -> int:
        with self._lock:
            return len(self._cache)


class UserCache:
    """Cache for user data with dirty tracking for batch updates."""
    
    MAX_CACHE_SIZE = 3000
    DIRTY_DIR_SIZE = 100
    
    def __init__(self):
        self._cache: dict[int, dict] = {}
        self._dirty: dict[int, bool] = {}
        self._lock = threading.Lock()
    
    def get(self, telegram_id: int) -> Optional[dict]:
        with self._lock:
            return self._cache.get(telegram_id)
    
    def set(self, telegram_id: int, user: dict) -> None:
        with self._lock:
            self._cache[telegram_id] = user
            self._dirty[telegram_id] = False
    
    def mark_dirty(self, telegram_id: int) -> None:
        with self._lock:
            self._dirty[telegram_id] = True
    
    def get_all_dirty(self) -> list[int]:
        with self._lock:
            return [tid for tid, dirty in self._dirty.items() if dirty]
    
    def get_all_users(self) -> list[int]:
        with self._lock:
            return list(self._cache.keys())
    
    def remove(self, telegram_id: int) -> None:
        with self._lock:
            self._cache.pop(telegram_id, None)
            self._dirty.pop(telegram_id, None)
    
    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._dirty.clear()
    
    def _evict_lru(self) -> None:
        with self._lock:
            keys_to_remove = list(self._cache.keys())[:self._cache.__len__() // 2]
            for key in keys_to_remove:
                self._cache.pop(key, None)
                self._dirty.pop(key, None)
    
    def enforce_limit(self) -> None:
        with self._lock:
            if len(self._cache) > self.MAX_CACHE_SIZE:
                self._evict_lru()


class NegativeCache:
    """Cache for negative results (404s, not found, etc.)."""
    
    def __init__(self, ttl: int = 3600):
        self._cache: dict[str, float] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
    
    def get(self, key: str) -> bool:
        with self._lock:
            if key not in self._cache:
                return False
            expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return False
            return True
    
    def set(self, key: str) -> None:
        with self._lock:
            self._cache[key] = time.time() + self._ttl
    
    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)


class ImageCache:
    """LRU cache for images (PIL Image objects or file paths)."""
    
    def __init__(self, max_size: int = 150):
        self._cache: dict[str, Any] = {}
        self._access_order: list[str] = []
        self._lock = threading.Lock()
        self._max_size = max_size
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
    
    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._cache:
                self._access_order.remove(key)
            elif len(self._cache) >= self._max_size:
                oldest = self._access_order.pop(0)
                del self._cache[oldest]
            self._cache[key] = value
            self._access_order.append(key)
    
    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._access_order.clear()


# Global cache instances
user_cache = UserCache()
api_cache = UnifiedCache(CacheConfig(ttl=300, max_size=100))
top_cache = UnifiedCache(CacheConfig(ttl=1800, max_size=100))
config_cache = UnifiedCache(CacheConfig(ttl=300, max_size=50))
negative_cache = NegativeCache(ttl=3600)
image_cache = ImageCache(max_size=150)
hero_cache = UnifiedCache(CacheConfig(ttl=86400, max_size=200))

# Global rate limiter instances
opendota_rate_limiter = UnifiedRateLimiter(RateLimitConfig(requests_per_second=0.25, burst=5, window_seconds=60))
telegram_rate_limiter = UnifiedRateLimiter(RateLimitConfig(requests_per_second=10.0, burst=20))

# Global circuit breaker instances
opendota_circuit_breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=30, recovery_timeout=30))
explorer_circuit_breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, recovery_timeout=300))


def invalidate_top_cache() -> None:
    """Invalidate all top-related cache entries."""
    top_cache.clear()
    api_cache.clear()


def flush_user_cache() -> int:
    """Flush dirty users to DB (placeholder - actual DB logic in database.py)."""
    dirty = user_cache.get_all_dirty()
    user_cache.clear()
    return len(dirty)


__all__ = [
    'UnifiedCache', 'UserCache', 'NegativeCache', 'ImageCache', 'UnifiedRateLimiter', 'CircuitBreaker',
    'CacheConfig', 'RateLimitConfig', 'CircuitBreakerConfig', 'RetryConfig',
    'retry',
    'user_cache', 'api_cache', 'top_cache', 'config_cache',
    'negative_cache', 'image_cache', 'hero_cache',
    'opendota_rate_limiter', 'telegram_rate_limiter',
    'opendota_circuit_breaker', 'explorer_circuit_breaker',
    'invalidate_top_cache', 'flush_user_cache'
]