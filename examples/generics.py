from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING, Any, TypeAlias
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.filters.models import ModelFilter, PaginationFilter
from fastapi_views.pagination import NumberedPage
from fastapi_views.views.generics import AsyncGenericViewSet

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_views.filters.models import BasePaginationFilter


class ItemId(BaseModel):
    id: UUID


class Item(ItemId):
    name: str


class CreateItem(BaseModel):
    name: str


class ItemFilter(PaginationFilter, ModelFilter):
    name: str | None = None


Rows: TypeAlias = "list[dict[str, Any]]"


def select_by_name(rows: Rows, name: str | None) -> Rows:
    if name is None:
        return rows
    return [row for row in rows if row["name"] == name]


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

    async def get(self, *_args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return self._data.get(kwargs["id"])

    async def list(self, *_args: Any, **kwargs: Any) -> Sequence[dict[str, Any]]:
        return select_by_name(self.rows, kwargs.get("name"))

    async def get_filtered_page(
        self,
        filter: BasePaginationFilter,
        **_kwargs: Any,
    ) -> NumberedPage[dict[str, Any]]:
        rows = select_by_name(self.rows, filter.as_kwargs().get("name"))
        pagination = filter.get_pagination()
        page, page_size = pagination["page"], pagination["page_size"]
        offset = (page - 1) * page_size
        return NumberedPage[dict[str, Any]](
            items=rows[offset : offset + page_size],
            current_page=page,
            page_size=page_size,
            total_items=len(rows),
            total_pages=ceil(len(rows) / page_size),
            has_more=offset + page_size < len(rows),
        )

    async def delete_one(self, *_args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return self._data.pop(kwargs["id"], None)

    async def update_one(
        self,
        values: dict[str, Any],
        *_args: Any,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        item = self._data.get(kwargs["id"])
        if item is None:
            return None
        item.update(values)
        return item

    @property
    def rows(self) -> Rows:
        return [*self._data.values()]


class ItemGenericViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    partial_update_schema = CreateItem
    filter = ItemFilter
    repository = ItemRepository()

    async def before_create(self, data: dict[str, Any]) -> None:
        data["name"] = data["name"].strip()


router = ViewRouter(prefix="/items")
router.register_view(ItemGenericViewSet)

app = FastAPI(title="Example API")
app.include_router(router)

configure_app(app)
