from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeAlias, TypeVar, get_type_hints, overload

_KEY_PATTERN = re.compile(r"\{(\w+)\}")

P = ParamSpec("P")
T = TypeVar("T")

Fn: TypeAlias = Callable[P, Awaitable[T]]
AsyncDecorator: TypeAlias = Callable[[Fn[P, T]], Fn[P, T]]


def _resolve_return_type(func: Callable[..., Any]) -> Any:
    """Best-effort resolution of an async function's awaited return type."""
    try:
        return get_type_hints(func).get("return")
    except Exception:  # noqa: BLE001
        return None


class Cache(ABC):
    @overload
    async def get(self, key: str, type_: type[T]) -> T | None: ...

    @overload
    async def get(self, key: str, type_: Any = None) -> Any: ...

    @abstractmethod
    async def get(self, key: str, type_: Any = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        raise NotImplementedError

    @overload
    async def pop(self, key: str, type_: type[T]) -> T | None: ...

    @overload
    async def pop(self, key: str, type_: Any = None) -> Any: ...

    @abstractmethod
    async def pop(self, key: str, type_: Any = None) -> Any:
        raise NotImplementedError

    def _format_key(
        self, key: Callable[P, str] | str, *args: P.args, **kwargs: P.kwargs
    ) -> str:
        if callable(key):
            return key(*args, **kwargs)
        if re.match(_KEY_PATTERN, key):
            return key.format(*args, **kwargs)
        return key

    def __call__(
        self, key: str | Callable[P, str], ttl: int | None = None
    ) -> AsyncDecorator[P, T]:
        def decorator(func: Fn[P, T]) -> Fn[P, T]:
            return_type = _resolve_return_type(func)

            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                cache_key = self._format_key(key, *args, **kwargs)
                result = await self.get(cache_key, return_type)
                if result is None:
                    result = await func(*args, **kwargs)
                    await self.set(cache_key, result, ttl=ttl)
                return result

            return wrapper

        return decorator
