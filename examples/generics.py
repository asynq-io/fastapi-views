from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.generics import AsyncGenericViewSet, Page

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_views.filters.models import PaginationFilter


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

    async def get_filtered_page(self, filter: PaginationFilter) -> Page[dict[str, Any]]:
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


class ItemGenericViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    partial_update_schema = CreateItem
    filter = None
    repository = ItemRepository()


router = ViewRouter(prefix="/items")
router.register_view(ItemGenericViewSet)

app = FastAPI(title="Example API")
app.include_router(router)

configure_app(app)
