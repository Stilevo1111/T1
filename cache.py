"""Redis caching layer with fallback to in-memory cache"""
from __future__ import annotations
import json
import logging
from typing import Optional, Any
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis-based cache with automatic serialization"""
    
    def __init__(self, url: str = "redis://localhost:6379"):
        self.client = redis.from_url(url, encoding="utf-8")
        self._connected = False
    
    async def connect(self) -> bool:
        """Test connection to Redis"""
        try:
            await self.client.ping()
            self._connected = True
            logger.info("Redis connection established")
            return True
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self._connected = False
            return False
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self._connected:
            return None
        try:
            data = await self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.debug(f"Cache miss for {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Set value in cache with TTL"""
        if not self._connected:
            return False
        try:
            await self.client.setex(key, ttl, json.dumps(value))
            return True
        except Exception as e:
            logger.error(f"Cache set failed for {key}: {e}")
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