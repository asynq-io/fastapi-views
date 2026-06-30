from __future__ import annotations

import functools
import hashlib
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Any, ClassVar, Literal
from urllib.parse import parse_qsl, urlencode

from fastapi import Response
from pydantic import Field

from fastapi_views.models import ResponseHeaders
from fastapi_views.views.api import APIView
from fastapi_views.views.mixins import ConditionalMixin

from .cache import Cache, cache
from .middleware import _CacheContext

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from fastapi_views.types import Action


__all__ = [
    "CacheControl",
    "CacheHeaders",
    "CachedAPIView",
    "ConditionalCachedAPIView",
    "use_cache",
]


@dataclass(frozen=True)
class CacheControl:
    """Builder for a ``Cache-Control`` response header value.

    Pass to :func:`use_cache` instead of a raw string to compose directives
    safely. ``private`` keeps a per-user/per-tenant response out of shared
    caches; ``s_maxage`` sets a separate freshness lifetime for them.

    Boolean fields render as bare directives (``no-store``); int fields render
    as ``name=value`` (``max-age=30``); ``None`` / ``False`` are omitted. Field
    names map to directives by replacing ``_`` with ``-``.
    """

    no_store: bool = False
    no_cache: bool = False
    public: bool = False
    private: bool = False
    max_age: int | None = None
    s_maxage: int | None = None
    must_revalidate: bool = False
    immutable: bool = False
    stale_while_revalidate: int | None = None
    stale_if_error: int | None = None

    def render(self) -> str:
        """Render the directives into a header value, in declaration order."""
        directives: list[str] = []
        for field in fields(self):
            value = getattr(self, field.name)
            if value is None or value is False:
                continue
            name = field.name.replace("_", "-")
            directives.append(name if value is True else f"{name}={value}")
        return ", ".join(directives)


class CacheHeaders(ResponseHeaders):
    """Cache-specific response headers documented for cached endpoints.

    The ``ETag`` / ``Last-Modified`` validators are not declared here; they are
    contributed dynamically by :class:`~fastapi_views.views.mixins.ConditionalMixin`
    only when the view actually emits them.
    """

    x_cache: Literal["HIT", "MISS"] = Field(
        alias="X-Cache", description="Whether the response was served from cache"
    )
    cache_control: str | None = Field(
        default=None, alias="Cache-Control", description="Cache-control directive"
    )
    vary: str | None = Field(
        default=None,
        alias="Vary",
        description="Request headers the cached response varies on",
    )


class CachedAPIView(APIView):
    """``APIView`` whose endpoints can cache their serialised responses.

    Override :meth:`build_key` to control the cache key, then decorate the
    relevant endpoint with :func:`use_cache`. The cache backend is supplied at
    the application level via :class:`~fastapi_views.cache.middleware.CacheMiddleware`::

        app.add_middleware(CacheMiddleware, backend=RedisCache(...))

        class ItemView(CachedAPIView, AsyncRetrieveAPIView):
            cache_key_headers = ["X-Tenant-Id"]

            @use_cache(ttl=60)
            async def retrieve(self, id: UUID) -> Item: ...

    This view caches only; it does not handle conditional requests. Use
    :class:`ConditionalCachedAPIView` to also revalidate with ``ETag`` /
    ``Last-Modified`` and answer ``304 Not Modified``.
    """

    cache_key_headers: ClassVar[Sequence[str]] = ()
    vary: ClassVar[Sequence[str]] = ()

    @classmethod
    def get_response_headers(
        cls, action: Action | None = None
    ) -> type[ResponseHeaders] | None:
        if action in ("retrieve", "list"):
            return CacheHeaders
        return None

    @property
    def cache(self) -> Cache:
        return cache

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

    def get_vary_headers(self) -> list[str]:
        """Request header names the cached response varies on.

        Combines :attr:`cache_key_headers` (which key the server-side cache) with
        :attr:`vary`, so downstream caches key on at least the same headers and
        cannot serve one client's response to another. Names are de-duplicated
        case-insensitively, preserving declaration order.
        """
        seen: set[str] = set()
        names: list[str] = []
        for name in (*self.cache_key_headers, *self.vary):
            lowered = name.lower()
            if lowered not in seen:
                seen.add(lowered)
                names.append(name)
        return names

    def get_cache_headers(
        self,
        *,
        hit: bool,
        ttl: int | None,
        cache_control: str | CacheControl | None,
    ) -> dict[str, str]:
        """Build the cache-related response headers (``X-Cache`` / ``Cache-Control`` / ``Vary``)."""
        cache_headers: dict[str, str] = {"X-Cache": "HIT" if hit else "MISS"}

        if isinstance(cache_control, CacheControl):
            # ``ttl`` provides the default freshness when not set explicitly.
            if cache_control.max_age is None and ttl is not None:
                cache_control = replace(cache_control, max_age=ttl)
            directive = cache_control.render()
        elif cache_control is not None:
            directive = cache_control
        elif ttl is not None:
            directive = f"max-age={ttl}"
        else:
            directive = None
        if directive:
            cache_headers["cache-control"] = directive

        vary = self.get_vary_headers()
        if vary:
            cache_headers["Vary"] = ", ".join(vary)
        return cache_headers


class ConditionalCachedAPIView(ConditionalMixin, CachedAPIView):
    """:class:`CachedAPIView` that also handles conditional requests.

    Combines server-side caching with ``ETag`` / ``Last-Modified`` revalidation:
    a cache hit can be downgraded to ``304 Not Modified`` when the client is
    current. Opt into validators exactly as on
    :class:`~fastapi_views.views.mixins.ConditionalMixin` (``etag = True``,
    ``last_modified = True``, or the manual ``check_*`` / ``not_modified``
    helpers)::

        class ItemView(ConditionalCachedAPIView, AsyncRetrieveAPIView):
            etag = True

            @use_cache(ttl=60)
            async def retrieve(self, id: UUID) -> Item: ...
    """


def use_cache(
    ttl: int | None = None,
    *,
    cache_control: str | CacheControl | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Cache a :class:`CachedAPIView` endpoint's serialised response.

    On a hit the cached body is returned immediately. On a miss the response is
    produced normally and a cache context is stored on the ASGI ``scope`` so
    :class:`~fastapi_views.cache.middleware.CacheMiddleware` can inject the cache
    headers and persist the body.
    """

    def decorator(
        func: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Any]:

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
                        hit=True, ttl=ttl, cache_control=cache_control
                    ),
                )

            result = await func(self, *args, **kwargs)
            if result is None:
                return None

            self.request.scope["_fastapi_views_cache"] = _CacheContext(
                key=key,
                ttl=ttl,
                headers=self.get_cache_headers(
                    hit=False, ttl=ttl, cache_control=cache_control
                ),
            )
            return result

        return wrapper

    return decorator
