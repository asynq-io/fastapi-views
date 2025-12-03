from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.filters import Filter
from fastapi_views.views.generics import AsyncGenericViewSet, Id


class Item(Id):
    name: str


class CreateItem(BaseModel):
    name: str


class FakeRepo:
    """
    Repository class, assuming all required methods like .get(), .create() are implemented
    """


class MyGenericViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    filter = Filter
    repository = FakeRepo()  # type: ignore[assignment]


router = ViewRouter(prefix="/items")
router.register_view(MyGenericViewSet)

app = FastAPI(title="My API")
app.include_router(router)

configure_app(app)
