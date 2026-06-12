import time
from typing import Any, NamedTuple

from .abc import Cache


class ExpiringItem(NamedTuple):
    value: Any
    expires_at: float | None


class InMemoryCache(Cache):
    def __init__(self, default_ttl: int | None = None) -> None:
        self._default_ttl = default_ttl
        self._data: dict[str, ExpiringItem] = {}

    async def get(self, key: str, type_: Any = None) -> Any:  # noqa: ARG002
        item = self._data.get(key)
        if item is None:
            return None
        if item.expires_at and time.monotonic() > item.expires_at:
            self._data.pop(key, None)
            return None
        return item.value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl or self._default_ttl
        expires_at = (time.monotonic() + ttl) if ttl else None
        self._data[key] = ExpiringItem(value, expires_at)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def pop(self, key: str, type_: Any = None) -> Any:  # noqa: ARG002
        item = self._data.pop(key, None)
        if item is None:
            return None
        if item.expires_at and time.monotonic() > item.expires_at:
            return None
        return item.value
