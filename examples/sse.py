import asyncio
from collections.abc import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.models.streaming import (
    ResponseEvent,
    ResponseFinished,
    ResponseResult,
)
from fastapi_views.views import ServerSentEventsAPIView, sse_route


class Item(BaseModel):
    id: int
    name: str


CustomResult = ResponseResult[Item]
CustomResponseEvent = ResponseEvent[Item]


class SSEView(ServerSentEventsAPIView):
    """Automatic server side event view based on `events` method"""

    response_schema = CustomResponseEvent

    async def events(self) -> AsyncIterator[CustomResponseEvent]:
        yield CustomResult.new(
            items=[Item(id=1, name="test"), Item(id=2, name="test")],
            index=1,
            total_results=2,
        )
        await asyncio.sleep(2)
        yield CustomResult.new(
            items=[Item(id=3, name="test"), Item(id=4, name="test")],
            index=2,
            total_results=2,
        )
        await asyncio.sleep(1)
        yield ResponseFinished.new()

    @sse_route("/custom-function", response_model=CustomResponseEvent)
    async def function_sse_route(self) -> AsyncIterator[CustomResponseEvent]:
        yield CustomResult.new(
            items=[Item(id=1, name="test"), Item(id=2, name="test")],
            index=1,
            total_results=2,
        )
        await asyncio.sleep(2)
        yield CustomResult.new(
            items=[Item(id=3, name="test"), Item(id=4, name="test")],
            index=2,
            total_results=2,
        )
        await asyncio.sleep(1)
        yield ResponseFinished.new()


router = ViewRouter()

router.register_view(SSEView, prefix="/sse")

app = FastAPI(title="Example API")
app.include_router(router)

configure_app(app)
