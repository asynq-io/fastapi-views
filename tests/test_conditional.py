from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import TYPE_CHECKING, Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_304_NOT_MODIFIED,
)

from fastapi_views import ViewRouter
from fastapi_views.cache.backends.memory import InMemoryCache
from fastapi_views.cache.middleware import CacheMiddleware
from fastapi_views.cache.view import ConditionalCachedAPIView, use_cache
from fastapi_views.models import BaseSchema
from fastapi_views.views.api import AsyncCreateAPIView, AsyncRetrieveAPIView
from fastapi_views.views.mixins import ConditionalHeaders, ConditionalMixin

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi_views.views.api import View

LAST_MODIFIED = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
NAIVE_LAST_MODIFIED = datetime(2024, 1, 1, 12, 0, 0, 500000)  # noqa: DTZ001
LAST_MODIFIED_HTTP_DATE = format_datetime(LAST_MODIFIED, usegmt=True)
LATER_HTTP_DATE = format_datetime(LAST_MODIFIED + timedelta(days=1), usegmt=True)
EARLIER_HTTP_DATE = format_datetime(LAST_MODIFIED - timedelta(days=1), usegmt=True)


class Item(BaseSchema):
    name: str


def build_app(view: type[View], prefix: str = "/test") -> FastAPI:
    app = FastAPI()
    router = ViewRouter()
    router.register_view(view, prefix=prefix)
    app.include_router(router)
    return app


@asynccontextmanager
async def view_client(
    view: type[View],
    prefix: str = "/test",
    *,
    cache: InMemoryCache | None = None,
) -> AsyncGenerator[AsyncClient, None]:
    app = build_app(view, prefix)
    if cache is not None:
        app.add_middleware(CacheMiddleware, backend=cache)
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


class EtagView(ConditionalMixin, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    etag = True

    async def retrieve(self) -> Any:
        return Item(name="test")


class LastModifiedView(ConditionalMixin, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    last_modified = True

    async def retrieve(self) -> Any:
        return Item(name="test")

    def get_last_modified(self) -> datetime | None:
        return LAST_MODIFIED


class BothValidatorsView(ConditionalMixin, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    etag = True
    last_modified = True

    async def retrieve(self) -> Any:
        return Item(name="test")

    def get_last_modified(self) -> datetime | None:
        return LAST_MODIFIED


class ManualEtagView(ConditionalMixin, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    conditional_requests = True

    async def retrieve(self) -> Any:
        return self.check_etag("v1") or Item(name="test")


class ManualLastModifiedView(ConditionalMixin, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    conditional_requests = True

    async def retrieve(self) -> Any:
        return (
            self.not_modified(last_modified=LAST_MODIFIED)
            if self.not_modified_since(LAST_MODIFIED)
            else Item(name="test")
        )


class CheckLastModifiedView(ConditionalMixin, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    conditional_requests = True

    async def retrieve(self) -> Any:
        return self.check_last_modified(NAIVE_LAST_MODIFIED) or Item(name="test")


class UnsetLastModifiedView(ConditionalMixin, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    last_modified = True

    async def retrieve(self) -> Any:
        return Item(name="test")


class NoValidatorView(ConditionalMixin, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item

    async def retrieve(self) -> Any:
        return Item(name="test")


class EtagCreateView(ConditionalMixin, AsyncCreateAPIView):
    response_schema = Item
    etag = True

    async def create(self) -> Any:
        return Item(name="test")


class CachedEtagView(ConditionalCachedAPIView, AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = Item
    etag = True

    @use_cache(ttl=60)
    async def retrieve(self) -> Any:
        return Item(name="test")


def test_conditional_headers_are_openapi_header_objects() -> None:
    headers = ConditionalHeaders.get_openapi_headers()
    assert set(headers) == {"ETag", "Last-Modified"}
    for header in headers.values():
        assert set(header) <= {"description", "required", "schema"}
        assert header["schema"]["type"] == "string"
        assert "properties" not in header
        assert "title" not in header


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        (EtagView, {"ETag"}),
        (LastModifiedView, {"Last-Modified"}),
        (BothValidatorsView, {"ETag", "Last-Modified"}),
        (ManualEtagView, {"ETag", "Last-Modified"}),
        (NoValidatorView, set()),
    ],
)
def test_conditional_response_headers_per_flag(view, expected) -> None:
    assert set(view._conditional_response_headers()) == expected


@pytest.mark.parametrize(
    ("view", "supported"),
    [
        (EtagView, True),
        (LastModifiedView, True),
        (ManualEtagView, True),
        (NoValidatorView, False),
    ],
)
def test_supports_conditional_requests(view, supported) -> None:
    assert view.supports_conditional_requests() is supported


@pytest.mark.anyio
async def test_etag_view_returns_quoted_etag() -> None:
    async with view_client(EtagView) as client:
        response = await client.get("/test")

    assert response.status_code == HTTP_200_OK
    etag = response.headers["etag"]
    assert etag.startswith('"')
    assert etag.endswith('"')
    assert response.json() == {"name": "test"}


@pytest.mark.anyio
async def test_etag_view_returns_304_on_matching_if_none_match() -> None:
    async with view_client(EtagView) as client:
        first = await client.get("/test")
        etag = first.headers["etag"]
        second = await client.get("/test", headers={"if-none-match": etag})

    assert second.status_code == HTTP_304_NOT_MODIFIED
    assert second.headers["etag"] == etag
    assert not second.content


@pytest.mark.anyio
async def test_etag_view_returns_200_on_stale_if_none_match() -> None:
    async with view_client(EtagView) as client:
        response = await client.get("/test", headers={"if-none-match": '"stale"'})

    assert response.status_code == HTTP_200_OK
    assert response.json() == {"name": "test"}


@pytest.mark.anyio
async def test_etag_view_returns_304_on_wildcard_if_none_match() -> None:
    async with view_client(EtagView) as client:
        response = await client.get("/test", headers={"if-none-match": "*"})

    assert response.status_code == HTTP_304_NOT_MODIFIED


@pytest.mark.anyio
async def test_etag_matches_when_client_sends_a_list() -> None:
    async with view_client(EtagView) as client:
        etag = (await client.get("/test")).headers["etag"]
        response = await client.get(
            "/test", headers={"if-none-match": f'"other", {etag}'}
        )

    assert response.status_code == HTTP_304_NOT_MODIFIED


@pytest.mark.anyio
async def test_weak_etag_matches_strong_validator() -> None:
    async with view_client(EtagView) as client:
        etag = (await client.get("/test")).headers["etag"]
        response = await client.get("/test", headers={"if-none-match": f"W/{etag}"})

    assert response.status_code == HTTP_304_NOT_MODIFIED


@pytest.mark.anyio
async def test_last_modified_view_sends_header() -> None:
    async with view_client(LastModifiedView) as client:
        response = await client.get("/test")

    assert response.status_code == HTTP_200_OK
    assert response.headers["last-modified"] == LAST_MODIFIED_HTTP_DATE
    assert "etag" not in response.headers


@pytest.mark.anyio
@pytest.mark.parametrize(
    "since",
    [LAST_MODIFIED_HTTP_DATE, LATER_HTTP_DATE, "Mon, 01 Jan 2024 12:00:00"],
)
async def test_last_modified_view_returns_304_when_client_is_current(since) -> None:
    async with view_client(LastModifiedView) as client:
        response = await client.get("/test", headers={"if-modified-since": since})

    assert response.status_code == HTTP_304_NOT_MODIFIED
    assert response.headers["last-modified"] == LAST_MODIFIED_HTTP_DATE
    assert not response.content


@pytest.mark.anyio
@pytest.mark.parametrize("since", [EARLIER_HTTP_DATE, "not-a-date"])
async def test_last_modified_view_returns_200_when_client_is_stale(since) -> None:
    async with view_client(LastModifiedView) as client:
        response = await client.get("/test", headers={"if-modified-since": since})

    assert response.status_code == HTTP_200_OK
    assert response.json() == {"name": "test"}


@pytest.mark.anyio
async def test_if_none_match_takes_precedence_over_if_modified_since() -> None:
    async with view_client(BothValidatorsView) as client:
        response = await client.get(
            "/test",
            headers={"if-none-match": '"stale"', "if-modified-since": LATER_HTTP_DATE},
        )

    assert response.status_code == HTTP_200_OK
    assert response.headers["last-modified"] == LAST_MODIFIED_HTTP_DATE


@pytest.mark.anyio
async def test_matching_if_none_match_wins_over_stale_if_modified_since() -> None:
    async with view_client(BothValidatorsView) as client:
        etag = (await client.get("/test")).headers["etag"]
        response = await client.get(
            "/test",
            headers={"if-none-match": etag, "if-modified-since": EARLIER_HTTP_DATE},
        )

    assert response.status_code == HTTP_304_NOT_MODIFIED
    assert response.headers["etag"] == etag
    assert response.headers["last-modified"] == LAST_MODIFIED_HTTP_DATE


@pytest.mark.anyio
async def test_manual_check_etag_sets_validator_and_short_circuits() -> None:
    async with view_client(ManualEtagView) as client:
        first = await client.get("/test")
        second = await client.get("/test", headers={"if-none-match": '"v1"'})

    assert first.status_code == HTTP_200_OK
    assert first.headers["etag"] == '"v1"'
    assert first.json() == {"name": "test"}
    assert second.status_code == HTTP_304_NOT_MODIFIED
    assert second.headers["etag"] == '"v1"'
    assert not second.content


@pytest.mark.anyio
async def test_manual_not_modified_response() -> None:
    async with view_client(ManualLastModifiedView) as client:
        first = await client.get("/test")
        second = await client.get(
            "/test", headers={"if-modified-since": LAST_MODIFIED_HTTP_DATE}
        )

    assert first.status_code == HTTP_200_OK
    assert first.json() == {"name": "test"}
    assert second.status_code == HTTP_304_NOT_MODIFIED
    assert second.headers["last-modified"] == LAST_MODIFIED_HTTP_DATE


@pytest.mark.anyio
async def test_manual_check_last_modified_normalizes_naive_datetimes() -> None:
    async with view_client(CheckLastModifiedView) as client:
        first = await client.get("/test")
        second = await client.get(
            "/test", headers={"if-modified-since": LAST_MODIFIED_HTTP_DATE}
        )

    assert first.status_code == HTTP_200_OK
    assert first.headers["last-modified"] == LAST_MODIFIED_HTTP_DATE
    assert first.json() == {"name": "test"}
    assert second.status_code == HTTP_304_NOT_MODIFIED
    assert second.headers["last-modified"] == LAST_MODIFIED_HTTP_DATE
    assert not second.content


@pytest.mark.anyio
async def test_last_modified_without_override_never_returns_304() -> None:
    async with view_client(UnsetLastModifiedView) as client:
        response = await client.get(
            "/test", headers={"if-modified-since": LATER_HTTP_DATE}
        )

    assert response.status_code == HTTP_200_OK
    assert "last-modified" not in response.headers


@pytest.mark.anyio
async def test_no_validator_view_sends_no_headers_and_never_304() -> None:
    async with view_client(NoValidatorView) as client:
        response = await client.get("/test", headers={"if-none-match": "*"})

    assert response.status_code == HTTP_200_OK
    assert "etag" not in response.headers
    assert "last-modified" not in response.headers


@pytest.mark.anyio
async def test_unsafe_method_sends_validator_but_never_304() -> None:
    async with view_client(EtagCreateView) as client:
        first = await client.post("/test")
        etag = first.headers["etag"]
        second = await client.post("/test", headers={"if-none-match": etag})

    assert first.status_code == HTTP_201_CREATED
    assert second.status_code == HTTP_201_CREATED
    assert second.json() == {"name": "test"}


def test_openapi_documents_etag_and_304_for_safe_methods() -> None:
    responses = build_app(EtagView).openapi()["paths"]["/test"]["get"]["responses"]

    assert set(responses["200"]["headers"]) == {"ETag"}
    assert responses["200"]["headers"]["ETag"]["schema"] == {"type": "string"}
    assert responses["304"]["description"] == "Not Modified"
    assert set(responses["304"]["headers"]) == {"ETag"}


def test_openapi_documents_last_modified() -> None:
    path = build_app(LastModifiedView).openapi()["paths"]["/test"]
    responses = path["get"]["responses"]

    assert set(responses["200"]["headers"]) == {"Last-Modified"}
    assert responses["200"]["headers"]["Last-Modified"]["schema"] == {
        "type": "string",
        "format": "http-date",
    }
    assert "304" in responses


def test_openapi_documents_both_validators_for_manual_mode() -> None:
    responses = build_app(ManualEtagView).openapi()["paths"]["/test"]["get"][
        "responses"
    ]

    assert set(responses["200"]["headers"]) == {"ETag", "Last-Modified"}
    assert set(responses["304"]["headers"]) == {"ETag", "Last-Modified"}


def test_openapi_documents_nothing_without_validators() -> None:
    responses = build_app(NoValidatorView).openapi()["paths"]["/test"]["get"][
        "responses"
    ]

    assert "304" not in responses
    assert "headers" not in responses["200"]


def test_openapi_omits_304_for_unsafe_methods() -> None:
    responses = build_app(EtagCreateView).openapi()["paths"]["/test"]["post"][
        "responses"
    ]

    assert "304" not in responses
    assert set(responses["201"]["headers"]) == {"ETag"}


def test_conditional_cached_view_documents_cache_and_validator_headers() -> None:
    responses = build_app(CachedEtagView).openapi()["paths"]["/test"]["get"][
        "responses"
    ]

    assert {"X-Cache", "ETag"} <= set(responses["200"]["headers"])
    assert set(responses["304"]["headers"]) == {"ETag"}


@pytest.mark.anyio
async def test_conditional_cached_view_revalidates_cache_hit() -> None:
    cache = InMemoryCache()
    async with view_client(CachedEtagView, cache=cache) as client:
        miss = await client.get("/test")
        hit = await client.get("/test")
        not_modified = await client.get(
            "/test", headers={"if-none-match": miss.headers["etag"]}
        )

    assert miss.status_code == HTTP_200_OK
    assert miss.headers["x-cache"] == "MISS"
    assert hit.status_code == HTTP_200_OK
    assert hit.headers["x-cache"] == "HIT"
    assert hit.headers["etag"] == miss.headers["etag"]
    assert not_modified.status_code == HTTP_304_NOT_MODIFIED
    assert not_modified.headers["etag"] == miss.headers["etag"]
    assert not not_modified.content
