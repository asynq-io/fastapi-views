from typing import Any, Literal

from .backends import Cache


def get_cache(backend: Literal["memory", "redis"], **options: Any) -> Cache:
    if backend == "memory":
        from .backends.memory import InMemoryCache

        return InMemoryCache(**options)
    if backend == "redis":
        from .backends.redis import RedisCache

        return RedisCache(**options)
    msg = f"Unknown backend {backend}"
    raise ValueError(msg)


__all__ = [
    "Cache",
    "get_cache",
]
