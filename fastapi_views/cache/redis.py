from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .abc import Cache
from .serializers import DefaultSerializer, Serializer

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisCache(Cache):
    def __init__(
        self, client: Redis, serializer: Serializer = DefaultSerializer()
    ) -> None:
        self.redis = client
        self.serializer = serializer

    async def get(self, key: str, type_: Any = None) -> Any:
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return self.serializer.decode(raw, type_)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self.redis.set(key, self.serializer.encode(value), ex=ttl)

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def pop(self, key: str, type_: Any = None) -> Any:
        raw = await self.redis.getdel(key)
        if raw is None:
            return None
        return self.serializer.decode(raw, type_)
