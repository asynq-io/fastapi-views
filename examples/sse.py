import asyncio
from collections.abc import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.models.streaming import (
    ResponseEvent,
    ResponseFinished,
    ResponseResult,
    ResultData,
)
from fastapi_views.views import ServerSentEventsAPIView, sse_route


class Item(BaseModel):
    id: int
    name: str


CustomResult = ResponseResult[Item]
CustomResultData = ResultData[Item]
CustomResponseEvent = ResponseEvent[Item]


def page(index: int, *items: Item) -> CustomResult:
    return CustomResult(
        data=CustomResultData(items=list(items), index=index, total_results=4),
    )


class SSEView(ServerSentEventsAPIView):
    """Automatic server side event view based on `events` method"""

    response_schema = CustomResponseEvent

    async def events(self) -> AsyncIterator[CustomResponseEvent]:
        yield page(1, Item(id=1, name="test"), Item(id=2, name="test"))
        await asyncio.sleep(2)
        yield page(2, Item(id=3, name="test"), Item(id=4, name="test"))
        await asyncio.sleep(1)
        yield ResponseFinished.new(duration_s=3)

    @sse_route(
        "/custom-function",
        response_model=CustomResponseEvent,
        serializer_options={"by_alias": True, "exclude_none": True},
    )
    async def function_sse_route(self) -> AsyncIterator[CustomResponseEvent]:
        yield page(1, Item(id=1, name="test"), Item(id=2, name="test"))
        await asyncio.sleep(2)
        yield page(2, Item(id=3, name="test"), Item(id=4, name="test"))
        await asyncio.sleep(1)
        yield ResponseFinished.new(duration_s=3)


router = ViewRouter()

router.register_view(SSEView, prefix="/sse")

app = FastAPI(title="Example API")
app.include_router(router)

configure_app(app)
