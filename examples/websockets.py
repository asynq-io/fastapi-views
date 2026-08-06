from typing import Annotated

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.types import WebSocketAction
from fastapi_views.views.websockets import WebSocketAPIView


class ChatMessage(BaseModel):
    user: str
    text: str


class ChatReply(BaseModel):
    text: str
    echo: bool = False


async def get_room(room: Annotated[str, Query()] = "lobby") -> str:
    return room


class ChatView(WebSocketAPIView[ChatMessage, ChatReply]):
    """Simple echo chat — broadcasts every received message to all connections."""

    name = "chat"
    message_schema = ChatMessage

    @classmethod
    def get_message_schema(cls, action: WebSocketAction) -> type[BaseModel]:
        return ChatReply if action == "send" else ChatMessage

    async def on_connect(self) -> None:
        self.logger.info("Client connected, total=%d", len(self._connections))

    async def on_disconnect(self) -> None:
        self.logger.info("Client disconnected, total=%d", len(self._connections))

    async def handler(self, room: Annotated[str, Depends(get_room)]) -> None:
        async for message in self.messages:
            reply = ChatReply(
                text=f"[{room}] {message.user}: {message.text}", echo=True
            )
            await self.broadcast(reply)


router = ViewRouter()
router.register_websocket_view(ChatView, prefix="/ws/chat")

app = FastAPI(title="WebSocket Chat Example")
app.include_router(router)

configure_app(app)
