from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.filters.models import BaseFilter
from fastapi_views.views.bulk import AsyncBulkAPIViewSet

# --- Schemas ---


class Item(BaseModel):
    id: UUID
    name: str


class CreateItem(BaseModel):
    name: str


class UpdateItem(BaseModel):
    id: UUID  # each bulk-update entry carries its own primary key
    name: str


class ItemValues(BaseModel):
    name: str  # values applied to every item selected by the filter


class ItemFilter(BaseFilter):
    name: str | None = None


# --- Repository ---


class ItemRepository:
    """In-memory repository implementing the bulk contract.

    A real implementation should run each method in a single transaction so the
    all-or-nothing guarantee holds.
    """

    def __init__(self) -> None:
        self._data: dict[UUID, Item] = {}

    async def create_many(
        self, items: Sequence[Mapping[str, Any]], **_options: Any
    ) -> list[Item]:
        created = [Item(id=uuid4(), **item) for item in items]
        for item in created:
            self._data[item.id] = item
        return created

    async def update_many(
        self, values: Mapping[str, Any], *_args: Any, **kwargs: Any
    ) -> list[Item]:
        updated = []
        for key, item in self._data.items():
            if self._matches(item, kwargs):
                item = item.model_copy(update=dict(values))
                self._data[key] = item
                updated.append(item)
        return updated

    async def bulk_update(
        self, items: Sequence[Mapping[str, Any]], **_options: Any
    ) -> None:
        for item in items:
            updated = Item(**item)
            self._data[updated.id] = updated

    async def delete_many(self, *_args: Any, **kwargs: Any) -> None:
        for key, item in list(self._data.items()):
            if self._matches(item, kwargs):
                del self._data[key]

    @staticmethod
    def _matches(item: Item, criteria: Mapping[str, Any]) -> bool:
        return all(getattr(item, key) == value for key, value in criteria.items())


# --- ViewSet ---


class ItemViewSet(AsyncBulkAPIViewSet):
    api_component_name = "Item"
    response_schema = Item
    create_schema = CreateItem
    bulk_update_schema = UpdateItem
    update_schema = ItemValues
    filter = ItemFilter  # selects rows for update-many and bulk-delete
    repository = ItemRepository()


router = ViewRouter(prefix="/items")
router.register_view(ItemViewSet)

app = FastAPI(title="Bulk Example")
app.include_router(router)
configure_app(app)
