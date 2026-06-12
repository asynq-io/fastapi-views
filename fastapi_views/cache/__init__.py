from typing import Any, Literal

from .abc import Cache
from .serializers import DefaultSerializer, Serializer


def get_cache(backend: Literal["memory", "redis"], **options: Any) -> Cache:
    if backend == "memory":
        from .memory import InMemoryCache

        return InMemoryCache(**options)
    if backend == "redis":
        from .redis import RedisCache

        return RedisCache(**options)
    msg = f"Unknown backend {backend}"
    raise ValueError(msg)


__all__ = [
    "Cache",
    "DefaultSerializer",
    "Serializer",
    "get_cache",
]
