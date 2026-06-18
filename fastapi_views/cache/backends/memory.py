import time
from typing import NamedTuple

from .abc import Cache, EncodableT, KeyT


class ExpiringItem(NamedTuple):
    value: EncodableT
    expires_at: float | None


class InMemoryCache(Cache):
    def __init__(self, default_ttl: int | None = None) -> None:
        self._default_ttl = default_ttl
        self._data: dict[KeyT, ExpiringItem] = {}

    async def get(self, key: KeyT) -> EncodableT | None:
        item = self._data.get(key)
        if item is None:
            return None
        if item.expires_at and time.monotonic() > item.expires_at:
            self._data.pop(key, None)
            return None
        return item.value

    async def set(self, key: KeyT, value: EncodableT, ttl: int | None = None) -> None:
        ttl = ttl or self._default_ttl
        expires_at = (time.monotonic() + ttl) if ttl else None
        self._data[key] = ExpiringItem(value, expires_at)

    async def delete(self, key: KeyT) -> None:
        self._data.pop(key, None)

    async def pop(self, key: KeyT) -> EncodableT | None:
        item = self._data.pop(key, None)
        if item is None:
            return None
        if item.expires_at and time.monotonic() > item.expires_at:
            return None
        return item.value
