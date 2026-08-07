from __future__ import annotations

import hashlib
import time
import warnings
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from pydantic._internal._model_construction import ModelMetaclass
from starlette.status import HTTP_200_OK, HTTP_404_NOT_FOUND

from fastapi_views import ViewRouter
from fastapi_views.cache.backends import CacheBackend
from fastapi_views.cache.backends.memory import ExpiringItem, InMemoryCache
from fastapi_views.cache.backends.redis import RedisCache
from fastapi_views.cache.cache import Cache, _get_type_adapter, _resolve_return_type
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


class _UnhashableMeta(ModelMetaclass):
    __hash__ = None  # type: ignore[assignment]


class ExoticItem(BaseSchema, metaclass=_UnhashableMeta):
    """A model whose *class* is unhashable, so it cannot be a cache key."""

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


def test_cache_backend_unset_raises() -> None:
    with pytest.raises(ValueError, match="Cache backend not set"):
        _ = Cache().backend


def test_cache_init_backend() -> None:
    backend = InMemoryCache()
    cache_ = Cache()
    cache_.init_backend(backend)
    assert cache_.backend is backend


@pytest.mark.anyio
async def test_cache_passthrough_methods() -> None:
    backend = AsyncMock(spec=CacheBackend)
    backend.get.return_value = b"got"
    backend.pop.return_value = b"popped"
    cache_ = Cache(backend)

    assert await cache_.get("k") == b"got"
    backend.get.assert_awaited_once_with("k")

    await cache_.set("k", b"v", ttl=30)
    backend.set.assert_awaited_once_with("k", b"v", ttl=30)

    await cache_.delete("k")
    backend.delete.assert_awaited_once_with("k")

    assert await cache_.pop("k") == b"popped"
    backend.pop.assert_awaited_once_with("k")


@pytest.mark.parametrize(
    ("key", "args", "kwargs", "expected"),
    [
        ("static-key", (), {}, "static-key"),
        (b"bytes-key", (), {}, b"bytes-key"),
        ("{name}", (), {"name": "widget"}, "widget"),
        ("{0}:{1}", ("a", "b"), {}, "a:b"),
        ("prefix:{name}", (), {"name": "x"}, "prefix:{name}"),  # pattern not at start
        (lambda item_id: f"item:{item_id}", (7,), {}, "item:7"),
    ],
)
def test_format_key(key, args, kwargs, expected) -> None:
    assert Cache()._format_key(key, *args, **kwargs) == expected


@pytest.mark.anyio
async def test_cache_decorator_miss_calls_function_and_stores() -> None:
    backend = InMemoryCache()
    cache_ = Cache(backend)
    call_count = 0

    @cache_("{name}")
    async def get_item(name: str) -> Item:
        nonlocal call_count
        call_count += 1
        return Item(name=name)

    result = await get_item(name="widget")

    assert result == Item(name="widget")
    assert call_count == 1
    assert await backend.get("widget") == b'{"name":"widget"}'


@pytest.mark.anyio
async def test_cache_decorator_hit_skips_function() -> None:
    backend = InMemoryCache()
    cache_ = Cache(backend)
    call_count = 0

    @cache_("{name}")
    async def get_item(name: str) -> Item:
        nonlocal call_count
        call_count += 1
        return Item(name=name)

    first = await get_item(name="widget")
    second = await get_item(name="widget")

    assert call_count == 1
    assert first == second == Item(name="widget")
    assert isinstance(second, Item)  # validated back from JSON


@pytest.mark.anyio
async def test_cache_decorator_passes_ttl_to_backend() -> None:
    backend = AsyncMock(spec=CacheBackend)
    backend.get.return_value = None
    cache_ = Cache(backend)

    @cache_("static", ttl=30)
    async def get_item() -> Item:
        return Item(name="x")

    await get_item()

    backend.set.assert_awaited_once_with("static", b'{"name":"x"}', ttl=30)


@pytest.mark.anyio
async def test_cache_decorator_callable_key() -> None:
    backend = InMemoryCache()
    cache_ = Cache(backend)

    @cache_(lambda item_id: f"item:{item_id}")
    async def get_item(item_id: int) -> Item:
        return Item(name=str(item_id))

    await get_item(7)

    assert await backend.get("item:7") is not None


@pytest.mark.anyio
async def test_cache_decorator_missing_return_annotation_round_trips() -> None:
    backend = InMemoryCache()
    cache_ = Cache(backend)
    call_count = 0

    @cache_("{name}")
    async def get_payload(name: str):
        nonlocal call_count
        call_count += 1
        return {"name": name, "count": [1, 2]}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        first = await get_payload(name="widget")
        second = await get_payload(name="widget")

    assert call_count == 1
    assert first == second == {"name": "widget", "count": [1, 2]}


def test_resolve_return_type_missing_annotation_is_any() -> None:
    async def fn(value: int):
        return value

    assert _resolve_return_type(fn) is Any


def test_resolve_return_type_none_annotation_is_none_type() -> None:
    async def fn() -> None:
        return None

    assert _resolve_return_type(fn) is type(None)


@pytest.mark.anyio
async def test_cache_decorator_annotated_model_is_rebuilt_as_model() -> None:
    backend = InMemoryCache()
    cache_ = Cache(backend)

    @cache_("{name}")
    async def get_item(name: str) -> Item:
        return Item(name=name)

    await get_item(name="widget")
    cached = await get_item(name="widget")

    assert isinstance(cached, Item)
    assert cached == Item(name="widget")


def test_get_type_adapter_caches_hashable_types() -> None:
    assert _get_type_adapter(Item) is _get_type_adapter(Item)


def test_get_type_adapter_handles_unhashable_annotation() -> None:
    unhashable = Annotated[int, {"exotic": True}]
    with pytest.raises(TypeError, match="unhashable"):
        hash(unhashable)

    adapter = _get_type_adapter(unhashable)

    assert adapter.dump_json(5) == b"5"
    assert adapter.validate_json(b"5") == 5


@pytest.mark.anyio
async def test_cache_decorator_unhashable_return_annotation_round_trips() -> None:
    with pytest.raises(TypeError, match="unhashable"):
        hash(ExoticItem)

    backend = InMemoryCache()
    cache_ = Cache(backend)
    call_count = 0

    @cache_("{name}")
    async def get_exotic(name: str) -> ExoticItem:
        nonlocal call_count
        call_count += 1
        return ExoticItem(name=name)  # type: ignore[call-arg]

    first = await get_exotic(name="widget")
    second = await get_exotic(name="widget")

    assert call_count == 1
    assert isinstance(second, ExoticItem)
    assert first == second


def test_resolve_return_type_falls_back_to_any() -> None:
    async def fn(value: int):
        return {"v": value}

    fn.__annotations__["return"] = "NotARealType"

    assert _resolve_return_type(fn) is Any


@pytest.mark.anyio
async def test_cache_decorator_unresolvable_annotation_uses_any() -> None:
    backend = InMemoryCache()
    cache_ = Cache(backend)
    call_count = 0

    async def fn(value: int):
        nonlocal call_count
        call_count += 1
        return {"v": value}

    fn.__annotations__["return"] = "NotARealType"
    wrapped = cache_("{value}")(fn)

    first = await wrapped(value=1)
    second = await wrapped(value=1)

    assert call_count == 1
    assert first == second == {"v": 1}


@pytest.mark.anyio
async def test_memory_get_missing_returns_none() -> None:
    assert await InMemoryCache().get("missing") is None


@pytest.mark.anyio
async def test_memory_set_get_roundtrip_without_ttl() -> None:
    backend = InMemoryCache()
    await backend.set("k", b"v")
    assert await backend.get("k") == b"v"
    assert backend._data["k"].expires_at is None


@pytest.mark.anyio
async def test_memory_set_uses_default_ttl() -> None:
    backend = InMemoryCache(default_ttl=60)
    await backend.set("k", b"v")
    assert backend._data["k"].expires_at is not None


@pytest.mark.anyio
async def test_memory_get_expired_removes_key() -> None:
    backend = InMemoryCache()
    backend._data["k"] = ExpiringItem(b"v", time.monotonic() - 1)
    assert await backend.get("k") is None
    assert "k" not in backend._data


@pytest.mark.anyio
async def test_memory_delete() -> None:
    backend = InMemoryCache()
    await backend.set("k", b"v")
    await backend.delete("k")
    assert await backend.get("k") is None


@pytest.mark.anyio
async def test_memory_delete_missing_key_is_noop() -> None:
    await InMemoryCache().delete("missing")


@pytest.mark.anyio
async def test_memory_pop_returns_value_and_removes() -> None:
    backend = InMemoryCache()
    await backend.set("k", b"v")
    assert await backend.pop("k") == b"v"
    assert "k" not in backend._data


@pytest.mark.anyio
async def test_memory_pop_missing_returns_none() -> None:
    assert await InMemoryCache().pop("missing") is None


@pytest.mark.anyio
async def test_memory_pop_expired_returns_none() -> None:
    backend = InMemoryCache()
    backend._data["k"] = ExpiringItem(b"v", time.monotonic() - 1)
    assert await backend.pop("k") is None
    assert "k" not in backend._data


@pytest.mark.anyio
async def test_redis_get() -> None:
    client = AsyncMock()
    client.get.return_value = b"v"
    backend = RedisCache(client)
    assert await backend.get("k") == b"v"
    client.get.assert_awaited_once_with("k")


@pytest.mark.anyio
async def test_redis_set_passes_ttl_as_ex() -> None:
    client = AsyncMock()
    backend = RedisCache(client)
    await backend.set("k", b"v", ttl=30)
    client.set.assert_awaited_once_with("k", b"v", ex=30)


@pytest.mark.anyio
async def test_redis_delete() -> None:
    client = AsyncMock()
    backend = RedisCache(client)
    await backend.delete("k")
    client.delete.assert_awaited_once_with("k")


@pytest.mark.anyio
async def test_redis_pop_uses_getdel() -> None:
    client = AsyncMock()
    client.getdel.return_value = b"v"
    backend = RedisCache(client)
    assert await backend.pop("k") == b"v"
    client.getdel.assert_awaited_once_with("k")
