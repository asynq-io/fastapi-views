from __future__ import annotations

import functools
import re
from functools import wraps
from typing import TYPE_CHECKING, Any, ParamSpec, Protocol, TypeVar, get_type_hints

from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .backends import CacheBackend, EncodableT, KeyT

_KEY_PATTERN = re.compile(r"\{(\w+)\}")
_ADAPTER_CACHE_SIZE = 512

P = ParamSpec("P")
T = TypeVar("T")


class AsyncDecorator(Protocol):
    def __call__(
        self, func: Callable[P, Awaitable[T]], /
    ) -> Callable[P, Awaitable[T]]: ...


def _resolve_return_type(func: Callable[..., Any]) -> Any:
    try:
        return get_type_hints(func).get("return", Any)
    except Exception:  # noqa: BLE001
        return Any


@functools.lru_cache(maxsize=_ADAPTER_CACHE_SIZE)
def _build_type_adapter(type_: Any) -> TypeAdapter[Any]:
    return TypeAdapter(type_)


def _get_type_adapter(type_: Any) -> TypeAdapter[Any]:
    try:
        return _build_type_adapter(type_)
    except TypeError:
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
        self, key: Callable[..., KeyT] | KeyT, *args: Any, **kwargs: Any
    ) -> KeyT:
        if callable(key):
            return key(*args, **kwargs)
        if isinstance(key, str) and re.match(_KEY_PATTERN, key):
            return key.format(*args, **kwargs)
        return key

    def __call__(
        self,
        key: KeyT | Callable[..., KeyT],
        ttl: int | None = None,
    ) -> AsyncDecorator:

        def decorator(
            func: Callable[P, Awaitable[T]],
        ) -> Callable[P, Awaitable[T]]:
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
