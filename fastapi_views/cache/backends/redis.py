from __future__ import annotations

from typing import TYPE_CHECKING

from .abc import CacheBackend, EncodableT, KeyT

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisCache(CacheBackend):
    def __init__(self, client: Redis) -> None:
        self.redis = client

    async def get(self, key: KeyT) -> EncodableT | None:
        return await self.redis.get(key)

    async def set(self, key: KeyT, value: EncodableT, ttl: int | None = None) -> None:
        await self.redis.set(key, value, ex=ttl)

    async def delete(self, key: KeyT) -> None:
        await self.redis.delete(key)

    async def pop(self, key: KeyT) -> EncodableT | None:
        return await self.redis.getdel(key)
