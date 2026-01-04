import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views import ServerSideEventsAPIView, sse_route

## APIView


class APIModel(BaseModel):
    id: int
    name: str


class SSEView(ServerSideEventsAPIView):
    """
    API view that populates
    """

    response_schema = APIModel

    async def events(self) -> AsyncIterator[tuple[str, Any]]:
        yield "data.received", {"id": 1, "name": "test"}
        await asyncio.sleep(2)
        yield "data.received", {"id": 2, "name": "test2"}

    @sse_route("/v1")
    async def function_sse_route(self):
        yield "1", "data.received", {"id": 1, "name": "test"}
        await asyncio.sleep(2)
        yield "2", "data.received", {"id": 2, "name": "test2"}


router = ViewRouter()

router.register_view(SSEView, prefix="/sse")

app = FastAPI(title="Example API")
app.include_router(router)

configure_app(app)
