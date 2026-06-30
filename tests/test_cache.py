from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from starlette.status import HTTP_200_OK, HTTP_404_NOT_FOUND

from fastapi_views import ViewRouter
from fastapi_views.cache.backends.memory import InMemoryCache
from fastapi_views.cache.middleware import CacheMiddleware
from fastapi_views.cache.view import CacheControl, CachedAPIView, use_cache
from fastapi_views.handlers import add_error_handlers
from fastapi_views.models import BaseSchema
from fastapi_views.views.api import AsyncListAPIView, AsyncRetrieveAPIView

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _md5(s: str) -> str:
    return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()


def _mock_request(
    path: str = "/items", query: str = "", headers: dict | None = None
) -> Request:
    mock = MagicMock(spec=Request)
    mock.url.path = path
    mock.url.query = query
    mock.headers = headers or {}
    return mock


class Item(BaseSchema):
    name: str


@asynccontextmanager
async def cached_view_client(
    view: type,
    mem_cache: InMemoryCache,
    prefix: str = "/test",
    *,
    error_handlers: bool = False,
) -> AsyncGenerator[AsyncClient, None]:
    app = FastAPI()
    app.add_middleware(CacheMiddleware, backend=mem_cache)
    if error_handlers:
        add_error_handlers(app)
    router = ViewRouter()
    router.register_view(view, prefix=prefix)
    app.include_router(router)
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


# ---------------------------------------------------------------------------
# build_key
# ---------------------------------------------------------------------------


class _BaseKeyView(CachedAPIView, AsyncListAPIView):
    response_schema = Item

    async def list(self):
        return []


@pytest.mark.parametrize(
    ("path", "query", "expected_parts"),
    [
        ("/items", "", ["/items"]),
        ("/items", "b=2&a=1", [f"/items?{urlencode([('a', '1'), ('b', '2')])}"]),
        ("/items", "a=1&b=2", [f"/items?{urlencode([('a', '1'), ('b', '2')])}"]),
    ],
)
def test_build_key_path_and_query(
    path: str, query: str, expected_parts: list[str]
) -> None:
    view = _BaseKeyView(
        request=_mock_request(path, query), response=MagicMock(spec=Response)
    )
    assert view.build_key() == _md5("|".join(expected_parts))


def test_build_key_query_order_is_stable() -> None:
    def _view(query: str) -> _BaseKeyView:
        return _BaseKeyView(
            request=_mock_request("/items", query), response=MagicMock(spec=Response)
        )

    assert _view("b=2&a=1").build_key() == _view("a=1&b=2").build_key()


def test_build_key_includes_configured_headers() -> None:
    class TenantView(_BaseKeyView):
        cache_key_headers = ("X-Tenant-Id",)

    def _view(tenant: str | None) -> TenantView:
        hdrs = {"x-tenant-id": tenant} if tenant else {}
        return TenantView(
            request=_mock_request("/items", "", hdrs), response=MagicMock(spec=Response)
        )

    assert _view("acme").build_key() != _view(None).build_key()
    assert _view("acme").build_key() != _view("other").build_key()
    assert _view(None).build_key() == _md5("/items")


def test_build_key_missing_header_excluded() -> None:
    class HeaderView(_BaseKeyView):
        cache_key_headers = ("X-Tenant-Id",)

    view_with = HeaderView(
        request=_mock_request("/items", "", {"x-tenant-id": "abc"}),
        response=MagicMock(spec=Response),
    )
    view_without = HeaderView(
        request=_mock_request("/items", ""),
        response=MagicMock(spec=Response),
    )
    assert view_with.build_key() != view_without.build_key()
    assert view_without.build_key() == _md5("/items")


# ---------------------------------------------------------------------------
# get_cache_headers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hit", "ttl", "cache_control", "expected"),
    [
        (True, None, None, {"X-Cache": "HIT"}),
        (False, None, None, {"X-Cache": "MISS"}),
        (False, 60, None, {"X-Cache": "MISS", "cache-control": "max-age=60"}),
        (False, 60, "no-store", {"X-Cache": "MISS", "cache-control": "no-store"}),
    ],
)
def test_get_cache_headers(
    hit: bool,
    ttl: int | None,
    cache_control: str | None,
    expected: dict,
) -> None:
    view = _BaseKeyView(request=_mock_request(), response=MagicMock(spec=Response))
    headers = view.get_cache_headers(hit=hit, ttl=ttl, cache_control=cache_control)
    for k, v in expected.items():
        assert headers[k] == v


def test_get_cache_headers_no_cache_control_when_no_ttl() -> None:
    view = _BaseKeyView(request=_mock_request(), response=MagicMock(spec=Response))
    headers = view.get_cache_headers(hit=False, ttl=None, cache_control=None)
    assert "cache-control" not in headers


# ---------------------------------------------------------------------------
# CacheControl
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cache_control", "expected"),
    [
        (CacheControl(), ""),
        (CacheControl(no_store=True), "no-store"),
        (CacheControl(max_age=0), "max-age=0"),
        (CacheControl(private=True, max_age=30), "private, max-age=30"),
        (CacheControl(public=True, s_maxage=60), "public, s-maxage=60"),
        (
            CacheControl(stale_while_revalidate=10, stale_if_error=5),
            "stale-while-revalidate=10, stale-if-error=5",
        ),
    ],
)
def test_cache_control_render(cache_control: CacheControl, expected: str) -> None:
    assert cache_control.render() == expected


def test_get_cache_headers_cache_control_object_injects_ttl_as_max_age() -> None:
    view = _BaseKeyView(request=_mock_request(), response=MagicMock(spec=Response))
    headers = view.get_cache_headers(
        hit=False, ttl=300, cache_control=CacheControl(private=True)
    )
    assert headers["cache-control"] == "private, max-age=300"


def test_get_cache_headers_cache_control_object_keeps_explicit_max_age() -> None:
    view = _BaseKeyView(request=_mock_request(), response=MagicMock(spec=Response))
    headers = view.get_cache_headers(
        hit=False, ttl=300, cache_control=CacheControl(max_age=30)
    )
    assert headers["cache-control"] == "max-age=30"


# ---------------------------------------------------------------------------
# Vary
# ---------------------------------------------------------------------------


def test_get_vary_headers_combines_key_headers_and_vary_and_dedupes() -> None:
    class VaryView(_BaseKeyView):
        cache_key_headers = ("X-Tenant-Id",)
        vary = ("Accept-Encoding", "x-tenant-id")  # last is a case-insensitive dup

    view = VaryView(request=_mock_request(), response=MagicMock(spec=Response))
    assert view.get_vary_headers() == ["X-Tenant-Id", "Accept-Encoding"]


def test_get_cache_headers_emits_vary_from_cache_key_headers() -> None:
    class VaryView(_BaseKeyView):
        cache_key_headers = ("X-Tenant-Id",)

    view = VaryView(request=_mock_request(), response=MagicMock(spec=Response))
    headers = view.get_cache_headers(hit=True, ttl=None, cache_control=None)
    assert headers["Vary"] == "X-Tenant-Id"


def test_get_cache_headers_no_vary_when_unconfigured() -> None:
    view = _BaseKeyView(request=_mock_request(), response=MagicMock(spec=Response))
    headers = view.get_cache_headers(hit=True, ttl=None, cache_control=None)
    assert "Vary" not in headers


# ---------------------------------------------------------------------------
# @use_cache decorator + CacheMiddleware integration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cached_miss_populates_cache_and_returns_miss_header() -> None:
    mem_cache = InMemoryCache()
    call_count = 0

    class MissView(CachedAPIView, AsyncListAPIView):
        response_schema = Item

        @use_cache(ttl=60)
        async def list(self):
            nonlocal call_count
            call_count += 1
            return [Item(name="widget")]

    async with cached_view_client(MissView, mem_cache) as client:
        response = await client.get("/test")

    assert response.status_code == HTTP_200_OK
    assert response.json() == [{"name": "widget"}]
    assert response.headers["x-cache"] == "MISS"
    assert response.headers["cache-control"] == "max-age=60"
    assert call_count == 1
    assert len(mem_cache._data) == 1


@pytest.mark.anyio
async def test_cached_hit_returns_cached_body_and_skips_endpoint() -> None:
    mem_cache = InMemoryCache()
    call_count = 0

    class HitView(CachedAPIView, AsyncListAPIView):
        response_schema = Item

        @use_cache(ttl=60)
        async def list(self):
            nonlocal call_count
            call_count += 1
            return [Item(name="widget")]

    async with cached_view_client(HitView, mem_cache) as client:
        first = await client.get("/test")
        second = await client.get("/test")

    assert first.headers["x-cache"] == "MISS"
    assert second.status_code == HTTP_200_OK
    assert second.json() == [{"name": "widget"}]
    assert second.headers["x-cache"] == "HIT"
    assert call_count == 1  # endpoint called only on first request


@pytest.mark.anyio
async def test_cached_none_result_is_not_stored() -> None:
    mem_cache = InMemoryCache()

    class NullView(CachedAPIView, AsyncRetrieveAPIView):
        response_schema = Item
        raise_on_none = False
        detail_route = ""

        @use_cache(ttl=60)
        async def retrieve(self):
            return None

    async with cached_view_client(NullView, mem_cache) as client:
        response = await client.get("/test")

    assert response.status_code == HTTP_200_OK
    assert len(mem_cache._data) == 0


@pytest.mark.anyio
async def test_cached_custom_cache_control() -> None:
    mem_cache = InMemoryCache()

    class CustomCCView(CachedAPIView, AsyncListAPIView):
        response_schema = Item

        @use_cache(ttl=60, cache_control="no-store")
        async def list(self):
            return [Item(name="x")]

    async with cached_view_client(CustomCCView, mem_cache) as client:
        response = await client.get("/test")

    assert response.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# CacheMiddleware — non-HTTP scope passthrough
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_middleware_passthrough_non_http_scope() -> None:
    received: list[dict] = []

    async def dummy_app(scope: Any, _receive: Any, _send: Any) -> None:
        received.append(scope)

    async def receive_noop() -> Any:
        return {}

    async def send_noop(_: Any) -> None:
        pass

    middleware = CacheMiddleware(dummy_app, backend=InMemoryCache())
    await middleware({"type": "lifespan"}, receive_noop, send_noop)
    assert received == [{"type": "lifespan"}]


# ---------------------------------------------------------------------------
# Error response is not cached
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_error_response_not_cached() -> None:
    mem_cache = InMemoryCache()

    class NotFoundView(CachedAPIView, AsyncRetrieveAPIView):
        response_schema = Item
        detail_route = ""

        @use_cache(ttl=60)
        async def retrieve(self):
            return None

    async with cached_view_client(
        NotFoundView, mem_cache, error_handlers=True
    ) as client:
        response = await client.get("/test")

    assert response.status_code == HTTP_404_NOT_FOUND
    assert len(mem_cache._data) == 0


# ---------------------------------------------------------------------------
# Cache context does not bleed between requests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cache_context_does_not_bleed_between_requests() -> None:
    """A MISS's cache context is per-request, so the next request is a clean HIT."""
    mem_cache = InMemoryCache()

    class ResetView(CachedAPIView, AsyncListAPIView):
        response_schema = Item

        @use_cache(ttl=60)
        async def list(self):
            return [Item(name="x")]

    async with cached_view_client(ResetView, mem_cache) as client:
        first = await client.get("/test")  # MISS, populates cache
        second = await client.get("/test")  # HIT, not a stale MISS

    assert first.headers["x-cache"] == "MISS"
    assert second.headers["x-cache"] == "HIT"


# ---------------------------------------------------------------------------
# cache_key_headers differentiate tenants end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cache_key_headers_isolate_tenants() -> None:
    mem_cache = InMemoryCache()
    call_log: list[str] = []

    class TenantView(CachedAPIView, AsyncListAPIView):
        response_schema = Item
        cache_key_headers = ("X-Tenant-Id",)

        @use_cache(ttl=60)
        async def list(self):
            tenant = self.request.headers.get("x-tenant-id", "unknown")
            call_log.append(tenant)
            return [Item(name=tenant)]

    async with cached_view_client(TenantView, mem_cache) as client:
        r1 = await client.get("/test", headers={"X-Tenant-Id": "alpha"})
        r2 = await client.get("/test", headers={"X-Tenant-Id": "beta"})
        r3 = await client.get("/test", headers={"X-Tenant-Id": "alpha"})

    assert r1.json() == [{"name": "alpha"}]
    assert r2.json() == [{"name": "beta"}]
    assert r3.json() == [{"name": "alpha"}]
    assert r3.headers["x-cache"] == "HIT"
    assert call_log == ["alpha", "beta"]  # alpha served from cache on third request
    # The key header is advertised to downstream caches so they key on it too.
    assert r1.headers["vary"] == "X-Tenant-Id"
