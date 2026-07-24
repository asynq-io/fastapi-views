from __future__ import annotations

import functools
import re
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    ParamSpec,
    TypeAlias,
    TypeVar,
    get_type_hints,
)

from pydantic import TypeAdapter

if TYPE_CHECKING:
    from .backends import CacheBackend, EncodableT, KeyT

_KEY_PATTERN = re.compile(r"\{(\w+)\}")

P = ParamSpec("P")
T = TypeVar("T")
VT = TypeVar("VT")

Fn: TypeAlias = Callable[P, Awaitable[T]]
AsyncDecorator: TypeAlias = Callable[[Fn[P, T]], Fn[P, T]]


def _resolve_return_type(func: Callable[..., Any]) -> Any:
    """Best-effort resolution of an async function's awaited return type."""
    try:
        return get_type_hints(func).get("return")
    except Exception:  # noqa: BLE001
        return Any


@functools.cache
def _get_type_adapter(type_: T) -> TypeAdapter[T]:
    return TypeAdapter(type_)


class Cache:
    def __init__(self, backend: CacheBackend | None = None) -> None:
        self._backend: CacheBackend | None = backend

    @property
    def backend(self) -> CacheBackend:
        if self._backend is None:
            raise ValueError("Cache backend not set")
        return self._backend

    def init_backend(self, backend: CacheBackend) -> None:
        self._backend = backend

    async def get(self, key: KeyT) -> EncodableT | None:
        return await self.backend.get(key)

    async def set(self, key: KeyT, value: EncodableT, ttl: int | None = None) -> None:
        return await self.backend.set(key, value, ttl=ttl)

    async def delete(self, key: KeyT) -> None:
        await self.backend.delete(key)

    async def pop(self, key: KeyT) -> EncodableT | None:
        return await self.backend.pop(key)

    def _format_key(
        self, key: Callable[P, KeyT] | KeyT, *args: P.args, **kwargs: P.kwargs
    ) -> KeyT:
        if callable(key):
            return key(*args, **kwargs)
        if isinstance(key, str) and re.match(_KEY_PATTERN, key):
            return key.format(*args, **kwargs)
        return key

    def __call__(
        self,
        key: KeyT | Callable[P, KeyT],
        ttl: int | None = None,
    ) -> AsyncDecorator[P, T] | AsyncDecorator[P, VT]:

        def decorator(func: Fn[P, T]) -> Fn[P, T]:
            return_type = _resolve_return_type(func)
            adapter = _get_type_adapter(return_type)

            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                cache_key = self._format_key(key, *args, **kwargs)
                raw = await self.get(cache_key)
                if raw is None:
                    result = await func(*args, **kwargs)
                    await self.set(cache_key, adapter.dump_json(result), ttl=ttl)
                    return result
                return adapter.validate_json(raw)

            return wrapper

        return decorator


cache = Cache()
