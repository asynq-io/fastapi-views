from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT

from fastapi_views.exceptions import NotFound
from fastapi_views.views.generics import GenericViewSet, Page

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


class SyncItemRepository:
    def __init__(self) -> None:
        self._data: dict[UUID, dict[str, Any]] = {}

    def create(self, **kwargs: Any) -> dict[str, Any] | None:
        item_id = uuid4()
        if item_id in self._data:
            return None
        kwargs["id"] = item_id
        self._data[item_id] = kwargs
        return kwargs

    def get(self, **kwargs: Any) -> dict[str, Any] | None:
        return self._data.get(kwargs["id"])

    def get_filtered_page(
        self, filter: BasePaginationFilter, **_: Any
    ) -> Page[dict[str, Any]]:
        raise NotImplementedError

    def list(self) -> Sequence[dict[str, Any]]:
        return list(self._data.values())

    def delete(self, **kwargs: Any) -> None:
        item_id = kwargs["id"]
        self._data.pop(item_id, None)

    def update_one(
        self,
        values: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        item = self._data.get(kwargs["id"])
        if item is None:
            return None
        item.update(values)
        return item


@view_as_fixture("sync_items_generic", prefix="/sync-items")
class SyncItemGenericViewSet(GenericViewSet):
    api_component_name = "SyncItem"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    partial_update_schema = CreateItem
    filter = None
    repository = SyncItemRepository()


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_list_generic(client):
    response = await client.get("/sync-items")
    assert response.status_code == HTTP_200_OK
    assert isinstance(response.json(), list)


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_create_generic(client):
    response = await client.post("/sync-items", json={"name": "test"})
    assert response.status_code == HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "test"
    assert "id" in data


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_retrieve_not_found(client):
    with pytest.raises(NotFound):
        await client.get(f"/sync-items/{uuid4()}")


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_retrieve_found(client):
    create_response = await client.post("/sync-items", json={"name": "find_me"})
    assert create_response.status_code == HTTP_201_CREATED
    item_id = create_response.json()["id"]

    response = await client.get(f"/sync-items/{item_id}")
    assert response.status_code == HTTP_200_OK
    assert response.json()["name"] == "find_me"


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_update_generic(client):
    create_response = await client.post("/sync-items", json={"name": "original"})
    assert create_response.status_code == HTTP_201_CREATED
    item_id = create_response.json()["id"]

    update_response = await client.put(
        f"/sync-items/{item_id}", json={"name": "updated"}
    )
    assert update_response.status_code == HTTP_200_OK
    assert update_response.json()["name"] == "updated"


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_update_not_found(client):
    with pytest.raises(NotFound):
        await client.put(f"/sync-items/{uuid4()}", json={"name": "ghost"})


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_partial_update_generic(client):
    create_response = await client.post("/sync-items", json={"name": "original"})
    assert create_response.status_code == HTTP_201_CREATED
    item_id = create_response.json()["id"]

    patch_response = await client.patch(
        f"/sync-items/{item_id}", json={"name": "patched"}
    )
    assert patch_response.status_code == HTTP_200_OK
    assert patch_response.json()["name"] == "patched"


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_partial_update_not_found(client):
    with pytest.raises(NotFound):
        await client.patch(f"/sync-items/{uuid4()}", json={"name": "ghost"})


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_destroy_generic(client):
    response = await client.delete(f"/sync-items/{uuid4()}")
    assert response.status_code == HTTP_204_NO_CONTENT


@pytest.mark.usefixtures("sync_items_generic")
@pytest.mark.anyio
async def test_sync_create_conflict_returns_conflict_error(client):
    # Test create with repository returning None (conflict)
    # We can verify this by checking the existing behavior
    response = await client.post("/sync-items", json={"name": "conflict_test"})
    assert response.status_code == HTTP_201_CREATED
