import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.models.sse_response import ResponseEvent
from fastapi_views.views import ServerSentEventsAPIView, sse_route


class Item(BaseModel):
    id: int
    name: str


class CustomResponseEvent(ResponseEvent[Item]):
    pass


class SSEView(ServerSentEventsAPIView):
    """Automatic server side event view based on `events` method"""

    response_schema = CustomResponseEvent

    async def events(self) -> AsyncIterator[Any]:
        yield CustomResponseEvent.page(
            items=[Item(id=1, name="test"), Item(id=2, name="test")],
            page=1,
            total_pages=2,
        )
        await asyncio.sleep(2)
        yield CustomResponseEvent.page(
            items=[Item(id=3, name="test"), Item(id=4, name="test")],
            page=2,
            total_pages=2,
        )

    @sse_route("/custom-function", response_model=CustomResponseEvent)
    async def function_sse_route(self) -> AsyncIterator[CustomResponseEvent]:
        yield CustomResponseEvent.page(
            items=[Item(id=1, name="test"), Item(id=2, name="test")],
            page=1,
            total_pages=2,
        )
        await asyncio.sleep(2)
        yield CustomResponseEvent.page(
            items=[Item(id=3, name="test"), Item(id=4, name="test")],
            page=2,
            total_pages=2,
        )


router = ViewRouter()

router.register_view(SSEView, prefix="/sse")

app = FastAPI(title="Example API")
app.include_router(router)

configure_app(app)
