from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from fastapi_views.exceptions import NotFound
from fastapi_views.views.generics import AsyncGenericViewSet, Page

from .utils import view_as_fixture

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_views.filters.models import BasePaginationFilter


class ItemId(BaseModel):
    id: UUID


class Item(ItemId):
    name: str


class CreateItem(BaseModel):
    name: str


class ItemRepository:
    def __init__(self) -> None:
        self._data: dict[UUID, dict[str, Any]] = {}

    async def create(self, **kwargs: Any) -> dict[str, Any] | None:
        item_id = uuid4()
        if item_id in self._data:
            return None
        kwargs["id"] = item_id
        self._data[item_id] = kwargs
        return kwargs

    async def get(self, **kwargs: Any) -> dict[str, Any] | None:
        return self._data.get(kwargs["id"])

    async def get_filtered_page(
        self,
        filter: BasePaginationFilter,
    ) -> Page[dict[str, Any]]:
        raise NotImplementedError

    async def list(self) -> Sequence[dict[str, Any]]:
        return list(self._data.values())

    async def delete(self, **kwargs: Any) -> None:
        item_id = kwargs["id"]
        self._data.pop(item_id, None)

    async def update_one(
        self,
        values: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        item = self._data.get(kwargs["id"])
        if item is None:
            return None

        item.update(values)
        return item


@view_as_fixture("items_generic", prefix="/items")
class ItemGenericViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    partial_update_schema = CreateItem
    filter = None
    repository = ItemRepository()


@pytest.mark.usefixtures("items_generic")
@pytest.mark.anyio
async def test_list_generic(client):
    response = await client.get("/items")
    assert response.status_code == HTTP_200_OK


@pytest.mark.usefixtures("items_generic")
@pytest.mark.anyio
async def test_create_generic(client):
    response = await client.post("/items", json={"name": "test"})
    assert response.status_code == HTTP_201_CREATED


@pytest.mark.usefixtures("items_generic")
@pytest.mark.anyio
async def test_retrieve_not_found_generic(client):
    with pytest.raises(NotFound):
        await client.get(f"/items/{uuid4()}")


@pytest.mark.usefixtures("items_generic")
@pytest.mark.anyio
async def test_destroy_generic(client):
    response = await client.delete(f"/items/{uuid4()}")
    assert response.status_code == HTTP_204_NO_CONTENT


@pytest.mark.usefixtures("items_generic")
@pytest.mark.anyio
async def test_update_generic(client):
    response = await client.post("/items", json={"name": "test"})
    assert response.status_code == HTTP_201_CREATED
    data = response.json()
    item_id = data["id"]
    response2 = await client.put(f"/items/{item_id}", json={"name": "test2"})
    assert response2.status_code == HTTP_200_OK
    data2 = response2.json()
    assert data2["id"] == item_id
    assert data2["name"] == "test2"


@pytest.mark.usefixtures("items_generic")
@pytest.mark.anyio
async def test_partial_update_generic(client):
    response = await client.post("/items", json={"name": "test"})
    assert response.status_code == HTTP_201_CREATED
    data = response.json()
    item_id = data["id"]
    response2 = await client.patch(f"/items/{item_id}", json={"name": "test2"})
    assert response2.status_code == HTTP_200_OK
    data2 = response2.json()
    assert data2["id"] == item_id
    assert data2["name"] == "test2"


# ---- get_response_schema with PaginationFilter / TokenPaginationFilter ----


def test_generic_list_view_response_schema_pagination_filter():
    from fastapi_views.filters.models import PaginationFilter
    from fastapi_views.pagination import NumberedPage
    from fastapi_views.views.generics import BaseGenericListAPIView

    class MySchema(BaseModel):
        name: str

    class PaginatedView(BaseGenericListAPIView):
        response_schema = MySchema
        filter = PaginationFilter

        def list(self, _filter):
            return []

    schema = BaseGenericListAPIView.__dict__["get_response_schema"].__func__(
        PaginatedView, "list"
    )
    assert schema == NumberedPage[MySchema]


def test_generic_list_view_response_schema_token_filter():
    from fastapi_views.filters.models import TokenPaginationFilter
    from fastapi_views.pagination import TokenPage
    from fastapi_views.views.generics import BaseGenericListAPIView

    class MySchema(BaseModel):
        name: str

    class TokenPaginatedView(BaseGenericListAPIView):
        response_schema = MySchema
        filter = TokenPaginationFilter

        def list(self, _filter):
            return []

    schema = BaseGenericListAPIView.__dict__["get_response_schema"].__func__(
        TokenPaginatedView, "list"
    )
    assert schema == TokenPage[MySchema]


def test_generic_list_view_response_schema_non_list_action():
    from fastapi_views.filters.models import PaginationFilter
    from fastapi_views.views.generics import BaseGenericListAPIView

    class MySchema(BaseModel):
        name: str

    class PaginatedView(BaseGenericListAPIView):
        response_schema = MySchema
        filter = PaginationFilter

        def list(self, _filter):
            return []

    assert PaginatedView.get_response_schema("retrieve") is MySchema
    assert PaginatedView.get_response_schema() is MySchema


# ---- _apply_fields_filter ----


def test_apply_fields_filter_sets_serializer_options():
    from fastapi_views.filters.models import FieldsFilter
    from fastapi_views.views.generics import AsyncGenericListAPIView

    class FieldsFilterView(AsyncGenericListAPIView):
        response_schema = dict
        filter = None

        async def list(self, _filter):
            return []

    view = FieldsFilterView.__new__(FieldsFilterView)
    view.serializer_options = {}
    view._apply_fields_filter(FieldsFilter(fields={"name", "age"}))
    assert "include" in view.serializer_options


def test_apply_fields_filter_no_fields():
    from fastapi_views.filters.models import FieldsFilter
    from fastapi_views.views.generics import AsyncGenericListAPIView

    class FieldsFilterView(AsyncGenericListAPIView):
        response_schema = dict
        filter = None

        async def list(self, _filter):
            return []

    view = FieldsFilterView.__new__(FieldsFilterView)
    view.serializer_options = {}
    view._apply_fields_filter(FieldsFilter(fields=None))
    assert "include" not in view.serializer_options


# ---- async/sync list with BasePaginationFilter ----


@pytest.mark.anyio
async def test_async_generic_list_with_pagination_filter():
    from asgi_lifespan import LifespanManager
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from fastapi_views.filters.models import PaginationFilter
    from fastapi_views.router import ViewRouter
    from fastapi_views.views.generics import AsyncGenericListAPIView

    class MockRepo:
        async def get_filtered_page(self, _filter):
            return []

        async def list(self, **_kwargs):
            return []

    class PaginatedListView(AsyncGenericListAPIView):
        response_schema = dict
        filter = PaginationFilter
        repository = MockRepo()

    app = FastAPI()
    router = ViewRouter()
    router.register_view(PaginatedListView, prefix="/test")
    app.include_router(router)

    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        response = await c.get("/test")
        assert response.status_code == HTTP_200_OK


def test_sync_generic_list_with_pagination_filter():
    from unittest.mock import MagicMock

    from fastapi_views.filters.models import PaginationFilter
    from fastapi_views.views.generics import GenericListAPIView

    class MockRepo:
        def get_filtered_page(self, _filter):
            return []

    view = MagicMock()
    view.repository = MockRepo()
    view._apply_fields_filter = MagicMock()

    f = PaginationFilter(page=1, page_size=10)
    result = GenericListAPIView.list(view, f)
    assert result == []


# ---- async/sync create raises Conflict ----


@pytest.mark.anyio
async def test_async_generic_create_raises_conflict():
    from asgi_lifespan import LifespanManager
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from fastapi_views.handlers import add_error_handlers
    from fastapi_views.router import ViewRouter
    from fastapi_views.views.generics import AsyncGenericCreateAPIView

    class ItemCreate(BaseModel):
        name: str

    class MockRepo:
        async def create(self, **_kwargs):
            return None

    class ConflictCreateView(AsyncGenericCreateAPIView):
        response_schema = dict
        create_schema = ItemCreate
        repository = MockRepo()

    app = FastAPI()
    add_error_handlers(app)
    router = ViewRouter()
    router.register_view(ConflictCreateView, prefix="/test")
    app.include_router(router)

    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        response = await c.post("/test", json={"name": "existing"})
        assert response.status_code == HTTP_409_CONFLICT


@pytest.mark.anyio
async def test_sync_generic_create_raises_conflict():
    from asgi_lifespan import LifespanManager
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from fastapi_views.handlers import add_error_handlers
    from fastapi_views.router import ViewRouter
    from fastapi_views.views.generics import GenericCreateAPIView

    class ItemCreate(BaseModel):
        name: str

    class MockRepo:
        def create(self, **_kwargs):
            return None

    class ConflictCreateView(GenericCreateAPIView):
        response_schema = dict
        create_schema = ItemCreate
        repository = MockRepo()

    app = FastAPI()
    add_error_handlers(app)
    router = ViewRouter()
    router.register_view(ConflictCreateView, prefix="/test")
    app.include_router(router)

    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        response = await c.post("/test", json={"name": "existing"})
        assert response.status_code == HTTP_409_CONFLICT


# ---- async update/partial_update raises NotFound ----


@pytest.mark.anyio
async def test_async_generic_update_raises_not_found():
    from asgi_lifespan import LifespanManager
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from fastapi_views.handlers import add_error_handlers
    from fastapi_views.router import ViewRouter
    from fastapi_views.views.generics import AsyncGenericUpdateAPIView

    class ItemUpdate(BaseModel):
        name: str

    class IntId(BaseModel):
        id: int

    class MockRepo:
        async def update_one(self, _values, **_kwargs):
            return None

    class NotFoundUpdateView(AsyncGenericUpdateAPIView):
        response_schema = dict
        update_schema = ItemUpdate
        primary_key = IntId
        repository = MockRepo()

    app = FastAPI()
    add_error_handlers(app)
    router = ViewRouter()
    router.register_view(NotFoundUpdateView, prefix="/test")
    app.include_router(router)

    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        response = await c.put("/test/1", json={"name": "new"})
        assert response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_async_generic_partial_update_raises_not_found():
    from asgi_lifespan import LifespanManager
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from fastapi_views.handlers import add_error_handlers
    from fastapi_views.router import ViewRouter
    from fastapi_views.views.generics import AsyncGenericPartialUpdateAPIView

    class ItemPartialUpdate(BaseModel):
        name: str | None = None

    class IntId(BaseModel):
        id: int

    class MockRepo:
        async def update_one(self, _values, **_kwargs):
            return None

    class NotFoundPartialView(AsyncGenericPartialUpdateAPIView):
        response_schema = dict
        partial_update_schema = ItemPartialUpdate
        primary_key = IntId
        repository = MockRepo()

    app = FastAPI()
    add_error_handlers(app)
    router = ViewRouter()
    router.register_view(NotFoundPartialView, prefix="/test")
    app.include_router(router)

    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        response = await c.patch("/test/1", json={})
        assert response.status_code == HTTP_404_NOT_FOUND
