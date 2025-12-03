from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.filters import Filter
from fastapi_views.views.generics import AsyncGenericViewSet, Id


class Item(Id):
    name: str


class CreateItem(BaseModel):
    name: str


class FakeRepo:
    pass


class MyGenericViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    primary_key = Id
    filter = Filter

    def __init__(
        self, request: Request, response: Response, repository=Depends(FakeRepo)
    ) -> None:
        super().__init__(request, response)
        self.repository = repository


router = ViewRouter(prefix="/items")
router.register_view(MyGenericViewSet)

app = FastAPI(title="My API")
app.include_router(router)

configure_app(app)
