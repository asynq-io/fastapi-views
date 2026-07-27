from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.jsonpatch import AsyncGenericJsonPatchAPIView

if TYPE_CHECKING:
    from uuid import UUID

# --- Schemas ---


class ItemId(BaseModel):
    id: UUID


class Item(ItemId):
    name: str
    tags: list[str] = []


# --- Repository ---


class ItemRepository:
    def __init__(self) -> None:
        self._data: dict[UUID, dict[str, Any]] = {}

    async def get(self, **kwargs: Any) -> dict[str, Any] | None:
        return self._data.get(kwargs["id"])

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


# --- View ---


class ItemJsonPatchView(AsyncGenericJsonPatchAPIView):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    partial_update_schema = Item
    repository = ItemRepository()  # type: ignore[assignment]


router = ViewRouter(prefix="/items")
router.register_view(ItemJsonPatchView)

app = FastAPI(title="JSON Patch Example")
app.include_router(router)
configure_app(app)
