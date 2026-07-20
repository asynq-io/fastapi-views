from __future__ import annotations

import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.status import HTTP_200_OK, HTTP_202_ACCEPTED

from fastapi_views import ViewRouter
from fastapi_views.models import ResponseHeaders
from fastapi_views.views.functools import action
from fastapi_views.views.viewsets import AsyncReadOnlyAPIViewSet

from .utils import view_client


class Item(BaseModel):
    id: int
    name: str


class Stats(BaseModel):
    count: int


class LocationHeaders(ResponseHeaders):
    location: str


def build_app(view: type) -> FastAPI:
    app = FastAPI()
    router = ViewRouter(prefix="/items")
    router.register_view(view)
    app.include_router(router)
    return app


def success_content(app: FastAPI, path: str, method: str, status: int = HTTP_200_OK):
    operation = app.openapi()["paths"][path][method]
    return operation["responses"][str(status)]


@pytest.mark.anyio
async def test_collection_action_defaults_to_hyphenated_method_name():
    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="x")

        @action(methods=["GET"])
        async def pending_count(self) -> Stats:
            return Stats(count=3)

    async with view_client(ItemViewSet, prefix="/items") as client:
        response = await client.get("/items/pending-count")
        assert response.status_code == HTTP_200_OK
        assert response.json() == {"count": 3}


@pytest.mark.anyio
async def test_collection_action_custom_path():
    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="x")

        @action(methods=["GET"], path="/summary")
        async def stats(self) -> Stats:
            return Stats(count=1)

    async with view_client(ItemViewSet, prefix="/items") as client:
        assert (await client.get("/items/summary")).status_code == HTTP_200_OK


@pytest.mark.anyio
async def test_detail_action_nests_under_detail_route():
    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="x")

        @action(methods=["POST"], detail=True)
        async def publish(self, id: int) -> Item:
            return Item(id=id, name="published")

    async with view_client(ItemViewSet, prefix="/items") as client:
        response = await client.post("/items/7/publish")
        assert response.status_code == HTTP_200_OK
        assert response.json() == {"id": 7, "name": "published"}


@pytest.mark.anyio
async def test_action_status_code_override():
    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="x")

        @action(methods=["POST"], status_code=HTTP_202_ACCEPTED)
        async def enqueue(self) -> Stats:
            return Stats(count=1)

    async with view_client(ItemViewSet, prefix="/items") as client:
        assert (await client.post("/items/enqueue")).status_code == HTTP_202_ACCEPTED


@pytest.mark.anyio
async def test_collection_action_not_shadowed_by_retrieve():
    """A static collection action and ``/{id}`` retrieve must both resolve."""

    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="retrieved")

        @action(methods=["GET"])
        async def stats(self) -> Stats:
            return Stats(count=9)

    async with view_client(ItemViewSet, prefix="/items") as client:
        assert (await client.get("/items/stats")).json() == {"count": 9}
        assert (await client.get("/items/5")).json() == {"id": 5, "name": "retrieved"}


def test_action_falls_back_to_response_schema():
    """Without an explicit ``response_model`` the view's schema is documented."""

    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="x")

        @action(methods=["GET"])
        async def stats(self) -> Stats:
            return Stats(count=1)

    app = build_app(ItemViewSet)
    content = success_content(app, "/items/stats", "get")["content"]
    assert content["application/json"]["schema"]["$ref"].endswith("/Item")


def test_action_explicit_response_model():
    """An explicit ``response_model`` is documented as-is."""

    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="x")

        @action(methods=["GET"], response_model=Stats)
        async def stats(self) -> Stats:
            return Stats(count=1)

    app = build_app(ItemViewSet)
    content = success_content(app, "/items/stats", "get")["content"]
    assert content["application/json"]["schema"]["$ref"].endswith("/Stats")


def test_action_documents_response_headers():
    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="x")

        @action(
            methods=["POST"],
            detail=True,
            status_code=HTTP_200_OK,
            response_headers=LocationHeaders,
        )
        async def publish(self, id: int) -> Item:
            return Item(id=id, name="p")

    app = build_app(ItemViewSet)
    response = success_content(app, "/items/{id}/publish", "post")
    assert "location" in response.get("headers", {})


def test_detail_action_respects_custom_detail_route():
    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        detail_route = "/{uuid}"
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, uuid: str) -> Item:
            return Item(id=1, name=uuid)

        @action(methods=["POST"], detail=True)
        async def publish(self, uuid: str) -> Item:
            return Item(id=1, name=uuid)

    app = build_app(ItemViewSet)
    assert "/items/{uuid}/publish" in app.openapi()["paths"]


def test_action_extras_not_leaked_to_route():
    """``detail`` / ``response_headers`` must not reach ``add_api_route``."""

    class ItemViewSet(AsyncReadOnlyAPIViewSet):
        response_schema = Item

        async def list(self) -> list[Item]:
            return []

        async def retrieve(self, id: int) -> Item:
            return Item(id=id, name="x")

        @action(methods=["POST"], detail=True, response_headers=LocationHeaders)
        async def publish(self, id: int) -> Item:
            return Item(id=id, name="p")

    # register_view would raise TypeError if extras were passed to add_api_route
    app = build_app(ItemViewSet)
    assert "/items/{id}/publish" in app.openapi()["paths"]
