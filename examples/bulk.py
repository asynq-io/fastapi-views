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


class ItemFilter(BaseFilter):
    name: str | None = None


# --- Repository ---


class ItemRepository:
    """In-memory repository implementing the bulk contract plus ``delete``.

    A real implementation should run each method in a single transaction so the
    all-or-nothing guarantee holds.
    """

    def __init__(self) -> None:
        self._data: dict[UUID, Item] = {}

    async def bulk_create(
        self, items: Sequence[Mapping[str, Any]], **_options: Any
    ) -> list[Item]:
        created = [Item(id=uuid4(), **item) for item in items]
        for item in created:
            self._data[item.id] = item
        return created

    async def bulk_update(
        self, items: Sequence[Mapping[str, Any]], **_options: Any
    ) -> list[Item]:
        updated = [Item(**item) for item in items]
        for item in updated:
            self._data[item.id] = item
        return updated

    async def delete(self, *_args: Any, **kwargs: Any) -> None:
        name = kwargs.get("name")
        for key, item in list(self._data.items()):
            if name is None or item.name == name:
                del self._data[key]


# --- ViewSet ---


class ItemViewSet(AsyncBulkAPIViewSet):
    api_component_name = "Item"
    response_schema = Item
    create_schema = CreateItem
    bulk_update_schema = UpdateItem
    filter = ItemFilter  # selects rows for bulk-delete (e.g. ?name=widget)
    repository = ItemRepository()


router = ViewRouter(prefix="/items")
router.register_view(ItemViewSet)

app = FastAPI(title="Bulk Example")
app.include_router(router)
configure_app(app)
