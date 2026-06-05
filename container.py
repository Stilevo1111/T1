"""Dependency Injection Container"""
from __future__ import annotations

from dependency_injector import containers, providers

from cache import RedisCache
from database import Database


class Container(containers.DeclarativeContainer):
    """Application dependency container"""

    # Configuration
    config = providers.Object(
        type('Config', (), {
            'cache_ttl': 300,
            'db_pool_min_size': 2,
            'db_pool_max_size': 10,
        })()
    )

    # Database provider
    database = providers.Singleton(
        Database,
    )

    # Cache provider
    cache = providers.Singleton(
        RedisCache,
        url="redis://localhost:6379"
    )

    # Repository providers
    user_repository = providers.Factory(
        lambda db=database, cache=cache: UserRepository(db, cache)
    )


class UserRepository:
    """User repository with cache support"""

    def __init__(self, db: Database, cache: RedisCache):
        self.db = db
        self.cache = cache

    async def get(self, telegram_id: int):
        # Try cache first
        user = await self.cache.get(f"user:{telegram_id}")
        if user:
            return user

        # Fallback to database
        user = await self.db.get_user(telegram_id)
        if user:
            await self.cache.set(f"user:{telegram_id}", user, ttl=1800)
        return user


# Global container instance
container = Container()
