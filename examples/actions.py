from typing import ClassVar
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.models import ResponseHeaders
from fastapi_views.views.functools import action
from fastapi_views.views.viewsets import AsyncAPIViewSet


class ItemSchema(BaseModel):
    id: UUID
    name: str
    published: bool = False


class CreateItemSchema(BaseModel):
    name: str


class ItemStats(BaseModel):
    total: int
    published: int


class LocationHeaders(ResponseHeaders):
    location: str


class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    items: ClassVar[dict[UUID, ItemSchema]] = {}

    async def list(self) -> list[ItemSchema]:
        return list(self.items.values())

    async def create(self, item: CreateItemSchema) -> ItemSchema:
        obj = ItemSchema(id=uuid4(), name=item.name)
        self.items[obj.id] = obj
        return obj

    async def retrieve(self, id: UUID) -> ItemSchema | None:
        return self.items.get(id)

    async def update(self, id: UUID, item: CreateItemSchema) -> ItemSchema:
        self.items[id] = ItemSchema(id=id, name=item.name)
        return self.items[id]

    async def destroy(self, id: UUID) -> None:
        self.items.pop(id, None)

    # Collection action -> GET /items/stats
    # The path defaults to the (hyphenated) method name. Static routes are
    # registered before ``/items/{id}`` so retrieve does not shadow them.
    # ``response_model`` documents the OpenAPI schema (it is otherwise the view's
    # ``response_schema``).
    @action(methods=["GET"], response_model=ItemStats)
    async def stats(self) -> ItemStats:
        values = list(self.items.values())
        return ItemStats(
            total=len(values),
            published=sum(1 for item in values if item.published),
        )

    # Detail action -> POST /items/{id}/publish
    # ``detail=True`` nests under the detail route; ``response_headers`` documents
    # the Location header on the success response.
    @action(methods=["POST"], detail=True, response_headers=LocationHeaders)
    async def publish(self, id: UUID) -> ItemSchema:
        published = self.items[id].model_copy(update={"published": True})
        self.items[id] = published
        self.response.headers["location"] = f"/items/{id}"
        return published


router = ViewRouter(prefix="/items")
router.register_view(ItemViewSet)

app = FastAPI(title="Actions Example")
app.include_router(router)
configure_app(app)
