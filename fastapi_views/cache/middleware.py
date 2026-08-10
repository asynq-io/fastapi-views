from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.datastructures import MutableHeaders

from .cache import cache

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from fastapi_views.cache.backends.abc import CacheBackend


_STATUS_CACHEABLE_MAX = 300
_CACHE_SCOPE_KEY = "_fastapi_views_cache"


@dataclass
class _CacheContext:
    """What the view asks the middleware to write, carried on the ASGI scope.

    ``body`` is the serialised body recorded by the view before a conditional
    response may be downgraded to an empty ``304 Not Modified``. When set it is
    persisted in place of the bytes actually sent, so the cache is warmed with
    the full representation even though the client receives no body.
    """

    key: str
    ttl: int | None
    headers: dict[str, Any]
    body: bytes | None = None

    def resolve_body(self, chunks: list[bytes], *, cacheable: bool) -> bytes:
        """The bytes to persist: the recorded body, else what was sent."""
        if self.body is not None:
            return self.body
        return b"".join(chunks) if cacheable else b""


class CacheMiddleware:
    """ASGI middleware that writes cache entries and injects cache headers.

    On a cache miss the :func:`~fastapi_views.cache.view.use_cache` decorator
    stores a :class:`_CacheContext` on the shared ASGI ``scope``. This middleware
    reads it back to inject the cache headers into the outgoing response and,
    once the full body has been sent, persist it to the backend::

        app.add_middleware(CacheMiddleware, backend=InMemoryCache())

    This is the single place cache entries are written. What gets stored is the
    body the context carries if the view recorded one (see
    :class:`_CacheContext`), otherwise the successful response's outgoing body.
    """

    def __init__(self, app: ASGIApp, *, backend: CacheBackend | None = None) -> None:
        self.app = app
        if backend is not None:
            cache.init_backend(backend)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        body_chunks: list[bytes] = []
        cacheable = False

        async def send_wrapper(message: Any) -> None:
            nonlocal cacheable

            ctx: _CacheContext | None = scope.get(_CACHE_SCOPE_KEY)
            if ctx is None:
                await send(message)
                return

            if message["type"] == "http.response.start":
                cacheable = message["status"] < _STATUS_CACHEABLE_MAX
                headers = MutableHeaders(scope=message)
                for name, value in ctx.headers.items():
                    headers[name] = value
            elif message["type"] == "http.response.body" and (
                chunk := message.get("body", b"")
            ):
                body_chunks.append(chunk)

            await send(message)

            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                body = ctx.resolve_body(body_chunks, cacheable=cacheable)
                if body:
                    await cache.set(ctx.key, body, ttl=ctx.ttl)

        await self.app(scope, receive, send_wrapper)
