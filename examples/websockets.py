from typing import ClassVar

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.websockets import WebSocketAPIView


class ChatMessage(BaseModel):
    user: str
    text: str


class ChatReply(BaseModel):
    text: str
    echo: bool = False


class ChatView(WebSocketAPIView[ChatMessage, ChatReply]):
    """Simple echo chat — broadcasts every received message back to all connections."""

    name = "chat"
    message_schema = ChatMessage

    # Per-class state: map of username -> connection count (illustrative)
    online: ClassVar[dict[str, int]] = {}

    async def on_connect(self) -> None:
        self.logger.info("Client connected, total=%d", len(self._connections))

    async def on_disconnect(self) -> None:
        self.logger.info("Client disconnected, total=%d", len(self._connections))

    async def handler(self, api_key: str | None = Depends()) -> None:
        if api_key is None:
            return
        async for message in self.messages:
            reply = ChatReply(text=f"[{message.user}] {message.text}", echo=True)
            await self.broadcast(reply)


router = ViewRouter()
router.register_websocket_view(ChatView, prefix="/ws/chat")

app = FastAPI(title="WebSocket Chat Example")
app.include_router(router)

configure_app(app)
