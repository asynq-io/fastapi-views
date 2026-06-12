from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from fastapi import BackgroundTasks, Request, Response
from starlette.status import HTTP_200_OK

from .api import APIView
from .mixins import ConditionalMixin

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi_views.cache.abc import Cache

__all__ = ["CachedAPIView", "cached"]

JSON_MEDIA_TYPE = "application/json"


class CachedAPIView(ConditionalMixin, APIView):
    """``APIView`` whose endpoints can cache their serialized responses.

    Override :meth:`build_key` to control the cache key, then decorate the
    relevant endpoint with :func:`cached`::

        class ItemView(CachedAPIView, AsyncRetrieveAPIView):
            cache = get_cache("redis", client=redis)

            def build_key(self) -> str:
                return f"item:{self.request.path_params['id']}"

            @cached(ttl=60)
            async def retrieve(self, id: UUID) -> Item: ...
    """

    cache: Cache

    def __init__(
        self,
        request: Request,
        response: Response,
        background: BackgroundTasks,
    ) -> None:
        super().__init__(request, response)
        self.background = background
        self._cache_headers: dict[str, str] = {}

    def build_key(self) -> str:
        """Cache key for the current request. Override for custom schemes."""
        request = self.request
        if request.url.query:
            return f"{request.url.path}?{request.url.query}"
        return request.url.path

    def get_cache_headers(
        self,
        *,
        hit: bool,
        ttl: int | None,
        cache_control: str | None,
        extra: dict[str, str],
    ) -> dict[str, str]:
        headers = {"x-cache": "HIT" if hit else "MISS", **extra}
        if cache_control is None and ttl is not None:
            cache_control = f"max-age={ttl}"
        if cache_control:
            headers["cache-control"] = cache_control
        return headers

    def get_response(
        self,
        content: Any,
        *,
        status_code: int = HTTP_200_OK,
        schema: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        # Feed cache headers through the ``headers`` param so they make it into
        # ``init_headers`` (setting them on ``self.response`` directly is wiped).
        if self._cache_headers:
            headers = {**(headers or {}), **self._cache_headers}
        response = super().get_response(
            content, status_code=status_code, schema=schema, headers=headers
        )
        # Attach ETag/Last-Modified and short-circuit to 304 when appropriate.
        return self.make_conditional(response)

    async def _update_cache(self, key: str, ttl: int | None) -> None:
        # Runs after the response is sent; ``self.response.body`` is serialized.
        if self.response.body and self.response.status_code < 300:  # noqa: PLR2004
            await self.cache.set(key, self.response.body, ttl=ttl)


def cached(
    ttl: int | None = None,
    *,
    cache_control: str | None = None,
    **headers: str,
) -> Callable[[Callable[..., Any]], Callable[..., Awaitable[Any]]]:
    """Cache a :class:`CachedAPIView` endpoint's serialized response.

    On a hit the cached body is returned straight away; on a miss the response
    is produced normally and stored in the background. ``ttl`` also drives the
    default ``Cache-Control: max-age=<ttl>`` header (override with
    ``cache_control``); any extra ``**headers`` are added verbatim.
    """

    def decorator(
        func: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def wrapper(self: CachedAPIView, *args: Any, **kwargs: Any) -> Any:
            key = self.build_key()
            cached_body = await self.cache.get(key, bytes)
            if cached_body is not None:
                return Response(
                    content=cached_body,
                    # Same status the endpoint applies on a miss — this view
                    # architecture sets it statically per action/route.
                    status_code=self.get_status_code(func.__name__),
                    media_type=JSON_MEDIA_TYPE,
                    headers=self.get_cache_headers(
                        hit=True, ttl=ttl, cache_control=cache_control, extra=headers
                    ),
                )

            result = await func(self, *args, **kwargs)
            if result is None:
                return None  # let the view handle it (e.g. retrieve -> 404)

            self._cache_headers = self.get_cache_headers(
                hit=False, ttl=ttl, cache_control=cache_control, extra=headers
            )
            self.background.add_task(self._update_cache, key, ttl)
            return result

        return wrapper

    return decorator
