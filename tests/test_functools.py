from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
)

from fastapi_views import ViewRouter
from fastapi_views.exceptions import BadRequest, NotFound
from fastapi_views.handlers import add_error_handlers
from fastapi_views.models import BaseSchema, ServerSentEvent
from fastapi_views.views.api import APIView
from fastapi_views.views.functools import (
    catch,
    catch_defined,
    errors,
    get,
    serialize_sse,
    sse_route,
    throws,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class DummySchema(BaseSchema):
    x: str


@pytest.fixture
def error_app():
    app = FastAPI()
    add_error_handlers(app)
    return app


@pytest.fixture
async def error_client(error_app) -> AsyncGenerator[AsyncClient, None]:
    async with (
        LifespanManager(error_app, startup_timeout=30),
        AsyncClient(
            transport=ASGITransport(app=error_app),
            base_url="http://test",
        ) as client,
    ):
        yield client


# ---- serialize_sse ----


def test_serialize_sse_basic():
    result = serialize_sse("id1", "my_event", '{"x": "hello"}')
    assert "id: id1" in result
    assert "event: my_event" in result
    assert 'data: {"x": "hello"}' in result


def test_serialize_sse_with_retry():
    result = serialize_sse("id1", "event", "data", retry=3000)
    assert "retry: 3000" in result


def test_serialize_sse_no_retry():
    result = serialize_sse("id1", "event", "data", retry=None)
    assert "retry" not in result


# ---- errors() ----


def test_errors_single_exception():
    result = errors(NotFound)
    assert 404 in result
    assert "model" in result[404]


def test_errors_multiple_exceptions_same_status():
    class Error1(BadRequest):
        pass

    class Error2(BadRequest):
        pass

    result = errors(Error1, Error2)
    assert 400 in result
    # When multiple exceptions share a status, model should be a Union
    assert "model" in result[400]


def test_errors_multiple_exceptions_different_statuses():
    result = errors(NotFound, BadRequest)
    assert 404 in result
    assert 400 in result


def test_errors_empty():
    result = errors()
    assert result == {}


# ---- throws() ----


def test_throws_creates_route_decorator():
    decorator = throws(NotFound, BadRequest)
    assert callable(decorator)


# ---- catch() ----


@pytest.mark.anyio
async def test_catch_async_handles_exception(error_app, error_client):
    class CatchView(APIView):
        response_schema = DummySchema

        @get(path="")
        @catch(ValueError)
        async def get_data(self) -> DummySchema:
            msg = "caught error"
            raise ValueError(msg)

    router = ViewRouter()
    router.register_view(CatchView, prefix="/catch-async")
    error_app.include_router(router)

    response = await error_client.get("/catch-async")
    assert response.status_code == HTTP_400_BAD_REQUEST
    data = response.json()
    assert "caught error" in data["detail"]


@pytest.mark.anyio
async def test_catch_async_passes_through_when_no_exception(error_app, error_client):
    class OkView(APIView):
        response_schema = DummySchema

        @get(path="")
        @catch(ValueError)
        async def get_data(self) -> DummySchema:
            return DummySchema(x="ok")

    router = ViewRouter()
    router.register_view(OkView, prefix="/catch-ok")
    error_app.include_router(router)

    response = await error_client.get("/catch-ok")
    assert response.status_code == HTTP_200_OK
    assert response.json()["x"] == "ok"


@pytest.mark.anyio
async def test_catch_sync_handles_exception(error_app, error_client):
    from fastapi_views.views.api import ListAPIView

    class SyncCatchView(ListAPIView):
        response_schema = DummySchema

        @catch(ValueError)
        def list(self) -> Any:
            msg = "sync caught error"
            raise ValueError(msg)

    router = ViewRouter()
    router.register_view(SyncCatchView, prefix="/catch-sync")
    error_app.include_router(router)

    response = await error_client.get("/catch-sync")
    assert response.status_code == HTTP_400_BAD_REQUEST


@pytest.mark.anyio
async def test_catch_sync_passes_through(error_app, error_client):
    from fastapi_views.views.api import ListAPIView

    class SyncOkView(ListAPIView):
        response_schema = DummySchema

        @catch(ValueError)
        def list(self) -> Any:
            return [{"x": "ok"}]

    router = ViewRouter()
    router.register_view(SyncOkView, prefix="/catch-sync-ok")
    error_app.include_router(router)

    response = await error_client.get("/catch-sync-ok")
    assert response.status_code == HTTP_200_OK


# ---- catch_defined() ----


@pytest.mark.anyio
async def test_catch_defined_async(error_app, error_client):
    class CatchDefinedView(APIView):
        response_schema = DummySchema
        raises: ClassVar[dict] = {ValueError: "defined error message"}

        @get(path="")
        @catch_defined
        async def get_data(self) -> DummySchema:
            msg = "original"
            raise ValueError(msg)

    router = ViewRouter()
    router.register_view(CatchDefinedView, prefix="/catch-defined")
    error_app.include_router(router)

    response = await error_client.get("/catch-defined")
    assert response.status_code == HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["detail"] == "defined error message"


@pytest.mark.anyio
async def test_catch_defined_sync(error_app, error_client):
    from fastapi_views.views.api import ListAPIView

    class SyncCatchDefinedView(ListAPIView):
        response_schema = DummySchema
        raises: ClassVar[dict] = {
            ValueError: {"detail": "sync defined error", "status": 400}
        }

        @catch_defined
        def list(self) -> Any:
            msg = "original"
            raise ValueError(msg)

    router = ViewRouter()
    router.register_view(SyncCatchDefinedView, prefix="/catch-def-sync")
    error_app.include_router(router)

    response = await error_client.get("/catch-def-sync")
    assert response.status_code == HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["detail"] == "sync defined error"


@pytest.mark.anyio
async def test_catch_defined_no_raises_no_exception(error_app, error_client):
    class NoRaisesView(APIView):
        response_schema = DummySchema

        @get(path="")
        @catch_defined
        async def get_data(self) -> DummySchema:
            return DummySchema(x="fine")

    router = ViewRouter()
    router.register_view(NoRaisesView, prefix="/no-raises")
    error_app.include_router(router)

    response = await error_client.get("/no-raises")
    assert response.status_code == HTTP_200_OK


# ---- sse_route() ----


@pytest.mark.anyio
async def test_sse_route_sync_generator(error_app, error_client):
    class SseView(APIView):
        @sse_route(path="", response_model=DummySchema)
        def stream(self):
            yield {"event": "data", "data": {"x": "hello"}, "id": "1"}
            yield {"event": "data", "data": {"x": "world"}, "id": "2"}

    router = ViewRouter()
    router.register_view(SseView, prefix="/sse-sync")
    error_app.include_router(router)

    response = await error_client.get("/sse-sync")
    assert response.status_code == HTTP_200_OK
    assert "text/event-stream" in response.headers["content-type"]
    content = response.text
    assert "event: data" in content
    assert "x" in content


@pytest.mark.anyio
async def test_sse_route_async_generator(error_app, error_client):
    class AsyncSseView(APIView):
        @sse_route(path="", response_model=DummySchema)
        async def stream(self):
            yield {"event": "update", "data": {"x": "async"}, "id": "1"}

    router = ViewRouter()
    router.register_view(AsyncSseView, prefix="/sse-async")
    error_app.include_router(router)

    response = await error_client.get("/sse-async")
    assert response.status_code == HTTP_200_OK
    assert "text/event-stream" in response.headers["content-type"]


@pytest.mark.anyio
async def test_sse_route_with_retry(error_app, error_client):
    class SseRetryView(APIView):
        @sse_route(path="", response_model=DummySchema)
        def stream(self):
            yield ServerSentEvent(event="tick", data=DummySchema(x="a"), retry=1000)

    router = ViewRouter()
    router.register_view(SseRetryView, prefix="/sse-retry")
    error_app.include_router(router)

    response = await error_client.get("/sse-retry")
    assert response.status_code == HTTP_200_OK
    assert "retry: 1000" in response.text


# ---- HTTP method decorators: post / put / patch / delete ----


@pytest.mark.anyio
async def test_http_method_decorators():
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from fastapi_views.views.api import View
    from fastapi_views.views.functools import delete, patch, post, put

    class MultiMethodView(View):
        @get(path="/items")
        async def list_items(self) -> list:
            return [1, 2, 3]

        @post(path="/items")
        async def create_item(self) -> dict:
            return {"created": True}

        @put(path="/items/{item_id}")
        async def update_item(self, item_id: int) -> dict:
            return {"updated": item_id}

        @patch(path="/items/{item_id}")
        async def partial_update_item(self, item_id: int) -> dict:
            return {"patched": item_id}

        @delete(path="/items/{item_id}")
        async def delete_item(self, item_id: int) -> None:
            return None

    app = FastAPI()
    router = ViewRouter()
    router.register_view(MultiMethodView, prefix="/test")
    app.include_router(router)

    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert (await client.get("/test/items")).status_code == HTTP_200_OK
        assert (await client.post("/test/items")).status_code == HTTP_201_CREATED
        assert (await client.put("/test/items/1")).status_code == HTTP_200_OK
        assert (await client.patch("/test/items/1")).status_code == HTTP_200_OK
        assert (await client.delete("/test/items/1")).status_code == HTTP_204_NO_CONTENT
