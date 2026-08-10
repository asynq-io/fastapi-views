from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_202_ACCEPTED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
)

from fastapi_views import ViewRouter
from fastapi_views.exceptions import BadRequest, Conflict, NotFound
from fastapi_views.handlers import add_error_handlers
from fastapi_views.models import BaseSchema
from fastapi_views.models.sse import AnyServerSentEvent
from fastapi_views.views.api import APIView, ListAPIView, View
from fastapi_views.views.functools import (
    catch,
    catch_defined,
    delete,
    errors,
    get,
    patch,
    post,
    put,
    serialize_sse,
    sse_route,
    throws,
)

from .utils import view_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class DummySchema(BaseSchema):
    x: str


class DummyEvent(AnyServerSentEvent):
    data: DummySchema


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


def test_errors_multiple_exceptions_different_statuses():
    result = errors(NotFound, BadRequest)
    assert 404 in result
    assert 400 in result


def test_errors_documents_problem_json_content():
    result = errors(NotFound)
    assert set(result) == {404}
    response = result[404]
    assert "description" in response
    content = response["content"]
    assert set(content) == {"application/problem+json"}
    schema = content["application/problem+json"]["schema"]
    assert "properties" in schema
    assert "anyOf" not in schema


def test_errors_same_status_uses_anyof_schema():
    class WidgetMissing(NotFound):
        """Widget is missing."""

    class GadgetMissing(NotFound):
        """Gadget is missing."""

    result = errors(WidgetMissing, GadgetMissing)
    response = result[404]
    assert "description" not in response
    schema = response["content"]["application/problem+json"]["schema"]
    assert len(schema["anyOf"]) == 2


def test_errors_empty():
    result = errors()
    assert result == {}


def test_throws_creates_route_decorator():
    decorator = throws(NotFound, BadRequest)
    assert callable(decorator)


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
    assert response.headers["Content-Type"] == "application/problem+json"
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


@pytest.mark.anyio
async def test_catch_defined_async(error_app, error_client):
    class CatchDefinedView(APIView):
        response_schema = DummySchema
        raises: ClassVar[dict[type[Exception], str | dict[str, Any]]] = {
            ValueError: "defined error message"
        }

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
    assert response.headers["Content-Type"] == "application/problem+json"
    assert data["detail"] == "defined error message"


@pytest.mark.anyio
async def test_catch_defined_sync(error_app, error_client):
    class SyncCatchDefinedView(ListAPIView):
        response_schema = DummySchema
        raises: ClassVar[dict[type[Exception], str | dict[str, Any]]] = {
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
    assert response.headers["Content-Type"] == "application/problem+json"
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


@pytest.mark.anyio
async def test_sse_route_sync_generator(error_app, error_client):
    class SseView(APIView):
        @sse_route(path="")
        def stream(self):
            yield AnyServerSentEvent(id="1", event="data", data={"x": "hello"})
            yield AnyServerSentEvent(id="2", event="data", data={"x": "world"})

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
        @sse_route(path="", response_model=DummyEvent)
        async def stream(self):
            yield DummyEvent(id="1", event="update", data=DummySchema(x="async"))

    router = ViewRouter()
    router.register_view(AsyncSseView, prefix="/sse-async")
    error_app.include_router(router)

    response = await error_client.get("/sse-async")
    assert response.status_code == HTTP_200_OK
    assert "text/event-stream" in response.headers["content-type"]
    assert "x" in response.text

    operation = error_app.openapi()["paths"]["/sse-async"]["get"]
    assert "text/event-stream" in operation["responses"]["200"]["content"]


@pytest.mark.anyio
async def test_sse_route_with_retry(error_app, error_client):
    class SseRetryView(APIView):
        @sse_route(path="", response_model=DummyEvent)
        def stream(self):
            yield DummyEvent(id="1", event="tick", data=DummySchema(x="a"), retry=1000)

    router = ViewRouter()
    router.register_view(SseRetryView, prefix="/sse-retry")
    error_app.include_router(router)

    response = await error_client.get("/sse-retry")
    assert response.status_code == HTTP_200_OK
    assert "retry: 1000" in response.text


@pytest.mark.anyio
async def test_sse_route_status_code_is_returned(error_app, error_client):
    class SseStatusView(APIView):
        @sse_route(path="", status_code=HTTP_202_ACCEPTED, response_model=DummyEvent)
        async def stream(self):
            yield DummyEvent(id="1", event="update", data=DummySchema(x="accepted"))

    router = ViewRouter()
    router.register_view(SseStatusView, prefix="/sse-status")
    error_app.include_router(router)

    response = await error_client.get("/sse-status")
    assert response.status_code == HTTP_202_ACCEPTED
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: update" in response.text
    assert "accepted" in response.text

    operation = error_app.openapi()["paths"]["/sse-status"]["get"]
    assert "text/event-stream" in operation["responses"]["202"]["content"]


@pytest.mark.anyio
async def test_route_decorator_on_top_of_throws_keeps_both(error_app, error_client):
    class OuterRouteView(APIView):
        @get("/{id}")
        @throws(NotFound)
        async def get_item(self, id: int) -> DummySchema:
            return DummySchema(x=str(id))

    router = ViewRouter()
    router.register_view(OuterRouteView, prefix="/outer-route")
    error_app.include_router(router)

    paths = error_app.openapi()["paths"]
    assert "/outer-route/{id}" in paths
    operation = paths["/outer-route/{id}"]["get"]
    assert "404" in operation["responses"]
    content = operation["responses"]["404"]["content"]
    assert "application/problem+json" in content

    response = await error_client.get("/outer-route/1")
    assert response.status_code == HTTP_200_OK
    assert response.json()["x"] == "1"


@pytest.mark.anyio
async def test_throws_on_top_of_route_decorator_keeps_both(error_app, error_client):
    class OuterThrowsView(APIView):
        @throws(NotFound)
        @get("/{id}")
        async def get_item(self, id: int) -> DummySchema:
            return DummySchema(x=str(id))

    router = ViewRouter()
    router.register_view(OuterThrowsView, prefix="/outer-throws")
    error_app.include_router(router)

    paths = error_app.openapi()["paths"]
    assert "/outer-throws/{id}" in paths
    assert "/outer-throws" not in paths
    operation = paths["/outer-throws/{id}"]["get"]
    assert set(paths["/outer-throws/{id}"]) == {"get"}
    assert "404" in operation["responses"]

    response = await error_client.get("/outer-throws/2")
    assert response.status_code == HTTP_200_OK
    assert response.json()["x"] == "2"


def test_stacked_responses_are_merged(error_app):
    class MergedResponsesView(APIView):
        @get("/merged", responses=errors(Conflict))
        @throws(NotFound)
        async def get_item(self) -> DummySchema:
            return DummySchema(x="merged")

    router = ViewRouter()
    router.register_view(MergedResponsesView, prefix="/merged-responses")
    error_app.include_router(router)

    operation = error_app.openapi()["paths"]["/merged-responses/merged"]["get"]
    assert {"404", "409"} <= set(operation["responses"])
    for status in ("404", "409"):
        assert "application/problem+json" in operation["responses"][status]["content"]


def test_shared_decorator_does_not_leak_between_methods(error_app):
    not_found = throws(NotFound)

    class SharedDecoratorView(APIView):
        @get("/first")
        @not_found
        async def first(self) -> DummySchema:
            return DummySchema(x="first")

        @post("/second")
        @not_found
        async def second(self) -> DummySchema:
            return DummySchema(x="second")

    assert SharedDecoratorView.first.kwargs["path"] == "/first"
    assert SharedDecoratorView.second.kwargs["path"] == "/second"
    assert (
        SharedDecoratorView.first.kwargs["responses"]
        is not SharedDecoratorView.second.kwargs["responses"]
    )

    router = ViewRouter()
    router.register_view(SharedDecoratorView, prefix="/shared")
    error_app.include_router(router)

    paths = error_app.openapi()["paths"]
    assert set(paths["/shared/first"]) == {"get"}
    assert set(paths["/shared/second"]) == {"post"}
    assert "404" in paths["/shared/first"]["get"]["responses"]
    assert "404" in paths["/shared/second"]["post"]["responses"]


@pytest.mark.anyio
async def test_http_method_decorators():
    class MultiMethodView(View):
        @get(path="/items")
        async def list_items(self) -> list[Any]:
            return [1, 2, 3]

        @post(path="/items")
        async def create_item(self) -> dict[str, Any]:
            return {"created": True}

        @put(path="/items/{item_id}")
        async def update_item(self, item_id: int) -> dict[str, Any]:
            return {"updated": item_id}

        @patch(path="/items/{item_id}")
        async def partial_update_item(self, item_id: int) -> dict[str, Any]:
            return {"patched": item_id}

        @delete(path="/items/{item_id}")
        async def delete_item(self, item_id: int) -> None:
            return None

    async with view_client(MultiMethodView) as client:
        assert (await client.get("/test/items")).status_code == HTTP_200_OK
        assert (await client.post("/test/items")).status_code == HTTP_201_CREATED
        assert (await client.put("/test/items/1")).status_code == HTTP_200_OK
        assert (await client.patch("/test/items/1")).status_code == HTTP_200_OK
        assert (await client.delete("/test/items/1")).status_code == HTTP_204_NO_CONTENT
