## View

from fastapi import Depends, Request, Response
from pydantic import BaseModel

from fastapi_views import ViewRouter
from fastapi_views.views import (
    APIView,
    AsyncListAPIView,
    AsyncRetrieveAPIView,
    View,
    get,
    post,
)


class BasicView(View):
    """
    Low level view, that handles responses exactly like FastAPI
    """

    @get("")
    async def get_method(self):
        return Response()

    @post("")
    async def post_method(self):
        return Response()


## APIView


class APIModel(BaseModel):
    id: int
    name: str


class BasicAPIView(APIView):
    """
    API view that populates
    """

    response_schema = APIModel

    @get("")
    async def get_item(self):
        # automatically converted to APIModel
        return {"id": 1, "name": "example"}


## Shared dependency


class Database:
    def list_items(self):
        return [{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}]


def get_db() -> Database:
    return Database()


class ReadAPIView(AsyncListAPIView, AsyncRetrieveAPIView):
    response_schema = APIModel

    def __init__(
        self, request: Request, response: Response, db: Database = Depends(get_db)
    ) -> None:
        super().__init__(request, response)
        self.db = db

    async def list(self):
        # response model automatically converted to list[APIModel]
        return self.db.list_items()

    async def retrieve(self, id: int):
        for item in self.db.list_items():
            if item["id"] == id:
                return item
        return None  # raises NotFound


## Registering views

router = ViewRouter()

router.register_view(BasicView, prefix="/view")
router.register_view(BasicAPIView, prefix="/apiview")
