from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.datastructures import MutableHeaders, State

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from .backends import Cache

__all__ = ["CacheMiddleware"]

_STATUS_CACHEABLE_MAX = 300


@dataclass
class _CacheContext:
    key: str
    ttl: int | None
    headers: dict[str, str]


_cache_context: ContextVar[_CacheContext | None] = ContextVar(
    "fastapi_views_cache_context", default=None
)


class CacheMiddleware:
    """ASGI middleware that writes cache entries and injects cache headers.

    Sets ``request.state.cache`` so :class:`~fastapi_views.cache.view.CachedAPIView`
    can access the backend without a class-level attribute. Also reads the
    :data:`_cache_context` variable set by the
    :func:`~fastapi_views.cache.view.cached` decorator: injects cache headers
    into the outgoing response and, after the full body is sent, persists it to
    the backend::

        app.add_middleware(CacheMiddleware, cache=get_cache("redis", client=redis))
    """

    def __init__(self, app: ASGIApp, cache: Cache) -> None:
        self.app = app
        self.cache = cache

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if "state" not in scope:
            scope["state"] = State()
        scope["state"].cache = self.cache

        token = _cache_context.set(None)
        status_code = 0
        body_chunks: list[bytes] = []

        async def send_wrapper(message: Any) -> None:
            nonlocal status_code

            ctx = _cache_context.get()

            if message["type"] == "http.response.start":
                status_code = message["status"]
                if ctx is not None:
                    headers = MutableHeaders(scope=message)
                    for k, v in ctx.headers.items():
                        headers[k] = v

            elif message["type"] == "http.response.body" and ctx is not None:
                chunk = message.get("body", b"")
                if chunk:
                    body_chunks.append(chunk)

            await send(message)

            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
                and ctx is not None
                and body_chunks
                and status_code < _STATUS_CACHEABLE_MAX
            ):
                await self.cache.set(ctx.key, b"".join(body_chunks), ttl=ctx.ttl)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _cache_context.reset(token)
