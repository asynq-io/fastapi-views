import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views import ServerSentEventsAPIView, sse_route


class APIModel(BaseModel):
    id: int
    name: str


class SSEView(ServerSentEventsAPIView):
    """Automatic server side event view based on `events` method"""

    response_schema = APIModel

    async def events(self) -> AsyncIterator[Any]:
        yield {"event": "data", "data": {"id": 1, "name": "test"}}
        await asyncio.sleep(2)
        yield {"event": "data", "data": {"id": 2, "name": "test2"}}

    @sse_route("/custom-function", response_model=APIModel)
    async def function_sse_route(self) -> AsyncIterator[Any]:
        yield {"event": "data", "data": {"id": 1, "name": "test"}}
        await asyncio.sleep(2)
        yield {"event": "data", "data": {"id": 2, "name": "test2"}}


router = ViewRouter()

router.register_view(SSEView, prefix="/sse")

app = FastAPI(title="Example API")
app.include_router(router)

configure_app(app)
