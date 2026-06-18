from __future__ import annotations

import functools
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeAlias, TypeVar, get_type_hints

from pydantic import TypeAdapter

_KEY_PATTERN = re.compile(r"\{(\w+)\}")

P = ParamSpec("P")
T = TypeVar("T")
VT = TypeVar("VT")

KeyT = str | bytes
EncodableT = str | bytes
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


class Cache(ABC):
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
