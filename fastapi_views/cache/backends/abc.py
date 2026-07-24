from __future__ import annotations

from abc import ABC, abstractmethod

KeyT = str | bytes
EncodableT = str | bytes


class CacheBackend(ABC):
    @abstractmethod
    async def get(self, key: KeyT) -> EncodableT | None:
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: KeyT, value: EncodableT, ttl: int | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: KeyT) -> None:
        raise NotImplementedError

    @abstractmethod
    async def pop(self, key: KeyT) -> EncodableT | None:
        raise NotImplementedError
