from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import TYPE_CHECKING, Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.status import HTTP_200_OK, HTTP_304_NOT_MODIFIED

from fastapi_views import ViewRouter
from fastapi_views.cache.backends.memory import InMemoryCache
from fastapi_views.cache.middleware import CacheMiddleware
from fastapi_views.cache.view import ConditionalCachedAPIView, use_cache
from fastapi_views.models import BaseSchema
from fastapi_views.views.api import AsyncRetrieveAPIView

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi_views.cache.backends import EncodableT, KeyT
    from fastapi_views.views.api import View

LAST_MODIFIED = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
LATER_HTTP_DATE = format_datetime(LAST_MODIFIED + timedelta(days=1), usegmt=True)
EARLIER_HTTP_DATE = format_datetime(LAST_MODIFIED - timedelta(days=1), usegmt=True)
BODY = b'{"name":"widget"}'


class Item(BaseSchema):
    name: str


class SpyCache(InMemoryCache):
    """``InMemoryCache`` recording every write, to detect double-writes."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[KeyT, EncodableT, int | None]] = []

    async def set(self, key: KeyT, value: EncodableT, ttl: int | None = None) -> None:
        self.writes.append((key, value, ttl))
        await super().set(key, value, ttl=ttl)


@asynccontextmanager
async def cached_client(
    view: type[View], backend: InMemoryCache, prefix: str = "/test"
) -> AsyncGenerator[AsyncClient, None]:
    app = FastAPI()
    app.add_middleware(CacheMiddleware, backend=backend)
    router = ViewRouter()
    router.register_view(view, prefix=prefix)
    app.include_router(router)
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


calls: list[str] = []


@pytest.fixture(autouse=True)
def _reset_calls() -> None:
    calls.clear()


class EtagCachedView(ConditionalCachedAPIView, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    etag = True

    @use_cache(ttl=60)
    async def retrieve(self) -> Any:
        calls.append("etag")
        return Item(name="widget")


class LastModifiedCachedView(ConditionalCachedAPIView, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    last_modified = True

    def get_last_modified(self) -> datetime:
        return LAST_MODIFIED

    @use_cache(ttl=60)
    async def retrieve(self) -> Any:
        calls.append("last-modified")
        return Item(name="widget")


async def discover_etag() -> str:
    """The ETag the view produces, learned from a throwaway app and cache.

    The probe request runs the view, so the call log is reset afterwards.
    """
    async with cached_client(EtagCachedView, InMemoryCache()) as client:
        response = await client.get("/test")
    calls.clear()
    return response.headers["etag"]


@pytest.mark.anyio
async def test_conditional_miss_downgraded_to_304_still_warms_cache() -> None:
    etag = await discover_etag()
    backend = SpyCache()

    async with cached_client(EtagCachedView, backend) as client:
        response = await client.get("/test", headers={"if-none-match": etag})

    assert response.status_code == HTTP_304_NOT_MODIFIED
    assert not response.content
    assert response.headers["etag"] == etag
    assert response.headers["x-cache"] == "MISS"
    assert response.headers["cache-control"] == "max-age=60"
    assert [value for _, value, _ in backend.writes] == [BODY]
    assert backend.writes[0][2] == 60


@pytest.mark.anyio
async def test_cache_warmed_by_304_serves_later_plain_request_as_hit() -> None:
    etag = await discover_etag()
    backend = SpyCache()

    async with cached_client(EtagCachedView, backend) as client:
        not_modified = await client.get("/test", headers={"if-none-match": etag})
        hit = await client.get("/test")

    assert not_modified.status_code == HTTP_304_NOT_MODIFIED
    assert hit.status_code == HTTP_200_OK
    assert hit.content == BODY
    assert hit.json() == {"name": "widget"}
    assert hit.headers["x-cache"] == "HIT"
    assert hit.headers["etag"] == etag
    assert calls == ["etag"]  # the view ran only for the 304


@pytest.mark.anyio
async def test_stale_validator_is_a_normal_miss_and_warms_cache() -> None:
    backend = SpyCache()

    async with cached_client(EtagCachedView, backend) as client:
        miss = await client.get("/test", headers={"if-none-match": '"stale"'})
        hit = await client.get("/test")

    assert miss.status_code == HTTP_200_OK
    assert miss.content == BODY
    assert miss.headers["x-cache"] == "MISS"
    assert hit.headers["x-cache"] == "HIT"
    assert len(backend.writes) == 1
    assert calls == ["etag"]


@pytest.mark.anyio
async def test_plain_miss_then_hit_cycle_is_unchanged() -> None:
    backend = SpyCache()

    async with cached_client(EtagCachedView, backend) as client:
        miss = await client.get("/test")
        hit = await client.get("/test")

    assert miss.status_code == hit.status_code == HTTP_200_OK
    assert miss.content == hit.content == BODY
    assert miss.headers["x-cache"] == "MISS"
    assert hit.headers["x-cache"] == "HIT"
    assert miss.headers["cache-control"] == hit.headers["cache-control"] == "max-age=60"
    assert miss.headers["etag"] == hit.headers["etag"]
    assert "vary" not in miss.headers
    assert calls == ["etag"]
    assert [value for _, value, _ in backend.writes] == [BODY]


@pytest.mark.anyio
@pytest.mark.parametrize("headers", [None, {"if-none-match": "*"}])
async def test_cache_is_written_exactly_once_per_miss(
    headers: dict[str, str] | None,
) -> None:
    backend = SpyCache()

    async with cached_client(EtagCachedView, backend) as client:
        await client.get("/test", headers=headers)
        assert len(backend.writes) == 1
        await client.get("/test")

    assert len(backend.writes) == 1  # a hit never re-writes the entry


@pytest.mark.anyio
async def test_last_modified_miss_downgraded_to_304_still_warms_cache() -> None:
    backend = SpyCache()

    async with cached_client(LastModifiedCachedView, backend) as client:
        not_modified = await client.get(
            "/test", headers={"if-modified-since": LATER_HTTP_DATE}
        )
        hit = await client.get("/test")

    assert not_modified.status_code == HTTP_304_NOT_MODIFIED
    assert not not_modified.content
    assert not_modified.headers["last-modified"] == format_datetime(
        LAST_MODIFIED, usegmt=True
    )
    assert not_modified.headers["x-cache"] == "MISS"
    assert hit.status_code == HTTP_200_OK
    assert hit.content == BODY
    assert hit.headers["x-cache"] == "HIT"
    assert hit.headers["last-modified"] == not_modified.headers["last-modified"]
    assert [value for _, value, _ in backend.writes] == [BODY]
    assert calls == ["last-modified"]


@pytest.mark.anyio
async def test_last_modified_stale_client_is_a_normal_miss() -> None:
    backend = SpyCache()

    async with cached_client(LastModifiedCachedView, backend) as client:
        miss = await client.get(
            "/test", headers={"if-modified-since": EARLIER_HTTP_DATE}
        )

    assert miss.status_code == HTTP_200_OK
    assert miss.content == BODY
    assert miss.headers["x-cache"] == "MISS"
    assert len(backend.writes) == 1
