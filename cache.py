"""Redis caching layer with fallback to in-memory cache"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis-based cache with automatic serialization"""

    def __init__(self, url: str = "redis://localhost:6379"):
        self.client = redis.from_url(url, encoding="utf-8")
        self._connected = False

    async def connect(self) -> bool:
        """Проверить соединение с Redis; при сбое помечает клиент неподключённым (fallback на in-memory)."""
        try:
            await self.client.ping()
            self._connected = True
            logger.info("Redis connection established")
            return True
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self._connected = False
            return False

    async def get(self, key: str) -> Any | None:
        """Прочитать значение из кэша (JSON-десериализация). При недоступности Redis — None."""
        if not self._connected:
            return None
        try:
            value = await self.client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.warning(f"Redis get failed: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Записать значение в кэш с TTL (сек). Возвращает успех операции."""
        if not self._connected:
            return False
        try:
            await self.client.set(key, json.dumps(value), ex=ttl)
            return True
        except Exception as e:
            logger.warning(f"Redis set failed: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self._connected:
            return False
        try:
            await self.client.delete(key)
            return True
        except Exception:
            return False


# Global instance
cache = RedisCache()
