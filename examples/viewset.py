from typing import ClassVar, Optional
from uuid import UUID

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.viewsets import AsyncAPIViewSet


class UpdateItemSchema(BaseModel):
    name: str
    price: int


class ItemSchema(BaseModel):
    id: UUID
    name: str
    price: int


class MyViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    items: ClassVar[dict[UUID, ItemSchema]] = {}

    async def list(self) -> list[ItemSchema]:
        return list(self.items.values())

    async def create(self, item: ItemSchema) -> ItemSchema:
        self.items[item.id] = item
        return item

    async def retrieve(self, id: UUID) -> Optional[ItemSchema]:
        return self.items.get(id)

    async def update(self, id: UUID, item: UpdateItemSchema) -> ItemSchema:
        self.items[id] = ItemSchema(id=id, name=item.name, price=item.price)
        return self.items[id]

    async def destroy(self, id: UUID) -> None:
        self.items.pop(id, None)


router = ViewRouter(prefix="/items")
router.register_view(MyViewSet)

app = FastAPI(title="My API")
app.include_router(router)

configure_app(app)
