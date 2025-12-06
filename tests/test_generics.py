from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

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
        self, filter: BasePaginationFilter
    ) -> Page[dict[str, Any]]:
        raise NotImplementedError

    async def list(self) -> Sequence[dict[str, Any]]:
        return list(self._data.values())

    async def delete(self, **kwargs: Any) -> None:
        item_id = kwargs["id"]
        self._data.pop(item_id, None)

    async def update_one(
        self, values: dict[str, Any], **kwargs: Any
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
async def test_list_generic(client):
    response = await client.get("/items")
    assert response.status_code == 200


@pytest.mark.usefixtures("items_generic")
async def test_create_generic(client):
    response = await client.post("/items", json={"name": "test"})
    assert response.status_code == 201


@pytest.mark.usefixtures("items_generic")
async def test_retrieve_not_found_generic(client):
    with pytest.raises(NotFound):
        await client.get(f"/items/{uuid4()}")


@pytest.mark.usefixtures("items_generic")
async def test_destroy_generic(client):
    response = await client.delete(f"/items/{uuid4()}")
    assert response.status_code == 204


@pytest.mark.usefixtures("items_generic")
async def test_update_generic(client):
    response = await client.post("/items", json={"name": "test"})
    assert response.status_code == 201
    data = response.json()
    item_id = data["id"]
    response2 = await client.put(f"/items/{item_id}", json={"name": "test2"})
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["id"] == item_id
    assert data2["name"] == "test2"


@pytest.mark.usefixtures("items_generic")
async def test_partial_update_generic(client):
    response = await client.post("/items", json={"name": "test"})
    assert response.status_code == 201
    data = response.json()
    item_id = data["id"]
    response2 = await client.patch(f"/items/{item_id}", json={"name": "test2"})
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["id"] == item_id
    assert data2["name"] == "test2"
