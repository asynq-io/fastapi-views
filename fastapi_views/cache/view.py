from __future__ import annotations

import functools
import hashlib
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import parse_qsl, urlencode

from fastapi import Response
from starlette.status import HTTP_200_OK

from fastapi_views.views.api import APIView
from fastapi_views.views.mixins import ConditionalMixin

from .middleware import _cache_context, _CacheContext

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, MutableMapping, Sequence

    from .backends import Cache

__all__ = ["CachedAPIView", "cached"]


class CachedAPIView(ConditionalMixin, APIView):
    """``APIView`` whose endpoints can cache their serialised responses.

    Override :meth:`build_key` to control the cache key, then decorate the
    relevant endpoint with :func:`cached`. The cache backend is supplied at
    the application level via :class:`~fastapi_views.cache.middleware.CacheMiddleware`
    and accessed through ``request.state``::

        app.add_middleware(CacheMiddleware, cache=get_cache("redis", client=redis))

        class ItemView(CachedAPIView, AsyncRetrieveAPIView):
            cache_key_headers = ["X-Tenant-Id"]

            @cached(ttl=60)
            async def retrieve(self, id: UUID) -> Item: ...
    """

    cache_key_headers: ClassVar[Sequence[str]] = []

    @property
    def cache(self) -> Cache:
        """Cache backend injected by :class:`~fastapi_views.cache.middleware.CacheMiddleware`."""
        return self.request.state.cache

    def build_key(self) -> str:
        """Cache key for the current request.

        Query parameters are sorted for a stable key regardless of ordering.
        Headers listed in :attr:`cache_key_headers` are appended to the key.
        Override for custom schemes.
        """
        request = self.request
        path = request.url.path

        query = urlencode(sorted(parse_qsl(request.url.query)))
        parts = [f"{path}?{query}" if query else path]

        parts.extend(
            f"{name}={value}"
            for name in self.cache_key_headers
            if (value := request.headers.get(name.lower()))
        )

        return hashlib.md5("|".join(parts).encode(), usedforsecurity=False).hexdigest()

    def get_cache_headers(
        self,
        *,
        hit: bool,
        ttl: int | None,
        cache_control: str | None,
        extra: MutableMapping[str, str],
    ) -> dict[str, str]:
        """Build the cache-related response headers."""
        cache_headers: dict[str, str] = {"x-cache": "HIT" if hit else "MISS", **extra}
        if cache_control is None and ttl is not None:
            cache_control = f"max-age={ttl}"
        if cache_control:
            cache_headers["cache-control"] = cache_control
        return cache_headers

    def get_response(
        self,
        content: Any,
        *,
        status_code: int = HTTP_200_OK,
        schema: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        response = super().get_response(
            content, status_code=status_code, schema=schema, headers=headers
        )
        return self.make_conditional(response)


def cached(
    ttl: int | None = None,
    *,
    cache_control: str | None = None,
    headers: MutableMapping[str, str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Awaitable[Any]]]:
    """Cache a :class:`CachedAPIView` endpoint's serialised response.

    On a hit the cached body is returned immediately. On a miss the response
    is produced normally and a :data:`_cache_context` context variable is set
    so :class:`~fastapi_views.cache.middleware.CacheMiddleware` can inject
    cache headers and persist the body.
    """
    extra: MutableMapping[str, str] = headers or {}

    def decorator(
        func: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def wrapper(self: CachedAPIView, *args: Any, **kwargs: Any) -> Any:
            key = self.build_key()
            cached_body = await self.cache.get(key)
            if cached_body is not None:
                return Response(
                    content=cached_body,
                    status_code=self.get_status_code(func.__name__),
                    media_type="application/json",
                    headers=self.get_cache_headers(
                        hit=True, ttl=ttl, cache_control=cache_control, extra=extra
                    ),
                )

            result = await func(self, *args, **kwargs)
            if result is None:
                return None

            _cache_context.set(
                _CacheContext(
                    key=key,
                    ttl=ttl,
                    headers=self.get_cache_headers(
                        hit=False, ttl=ttl, cache_control=cache_control, extra=extra
                    ),
                )
            )
            return result

        return wrapper

    return decorator
