# WebSockets

FastAPI Views provides `WebSocketAPIView` — a class-based view for WebSocket endpoints with built-in Pydantic validation, connection tracking, broadcast helpers, and clean disconnect handling.

---

## `WebSocketAPIView`

Subclass `WebSocketAPIView` and implement the `handler` async method. The view automatically accepts the connection, deserializes incoming binary frames using the `message_schema`, and closes the connection on disconnect.

```python
from pydantic import BaseModel
from fastapi import FastAPI

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.websockets import WebSocketAPIView


class ChatMessage(BaseModel):
    user: str
    text: str


class ChatReply(BaseModel):
    text: str


class ChatView(WebSocketAPIView):
    name = "chat"
    message_schema = ChatMessage

    async def handler(self) -> None:
        async for message in self.messages:
            reply = ChatReply(text=f"[{message.user}] {message.text}")
            await self.send(reply)


router = ViewRouter()
router.register_websocket_view(ChatView, prefix="/ws/chat")

app = FastAPI()
app.include_router(router)
configure_app(app)
```

### Type parameters

`WebSocketAPIView` is generic over three type variables:

| Variable | Description |
|---|---|
| `P` | `ParamSpec` for the `handler` method's extra dependencies |
| `S` | The *send* schema — the type passed to `send` / `broadcast` |
| `R` | The *receive* schema — the type yielded by `self.messages` |

For most cases you can leave the generics implicit and rely on `message_schema`.

---

## Sending and broadcasting

| Method | Description |
|---|---|
| `await self.send(message)` | Serialize and send to the current connection |
| `await self.broadcast(message)` | Serialize and send to **all** active connections of this view class |

Both methods use a cached Pydantic `TypeAdapter` keyed on the return type of `get_serializer("send")`. Disconnected clients are silently skipped during broadcast.

---

## Receiving messages

`self.messages` is an `AsyncIterable` that yields validated, deserialized messages:

```python
async def handler(self) -> None:
    async for message in self.messages:
        # message is already a validated `message_schema` instance
        await self.broadcast(message)
```

Incoming bytes are validated with `message_schema` (or the schema returned by `get_message_schema("receive")`). A `ValidationError` or `WebSocketDisconnect` cancels the receive loop and triggers cleanup.

---

## Connection lifecycle hooks

Override `on_connect` and `on_disconnect` to run logic when a client connects or disconnects:

```python
class RoomView(WebSocketAPIView):
    message_schema = ChatMessage

    async def on_connect(self) -> None:
        print(f"New connection, total: {len(self._connections)}")

    async def on_disconnect(self) -> None:
        print("Client left")

    async def handler(self) -> None:
        async for message in self.messages:
            await self.broadcast(message)
```

`on_connect` is called before the internal receive loop starts. `on_disconnect` is called after the connection is removed from `_connections` and the socket is closed, with a configurable timeout (default 30 s) to allow graceful cleanup.

---

## Per-class connection tracking

`_connections` is a class-level list of all active `WebSocket` objects for that view class. Use it to inspect or act on connected clients:

```python
class StatsView(WebSocketAPIView):
    ...

    async def handler(self) -> None:
        async for _ in self.messages:
            count = len(self._connections)
            await self.send(StatusMessage(online=count))
```

---

## FastAPI dependency injection

Path and query parameters, as well as `Depends(...)` dependencies, are supported through the `handler` signature:

```python
from fastapi import Depends

async def get_current_user(token: str) -> str:
    return token  # simplified

class AuthenticatedView(WebSocketAPIView):
    message_schema = ChatMessage

    async def handler(self, user: str = Depends(get_current_user)) -> None:
        async for message in self.messages:
            if message.user == user:
                await self.send(ChatReply(text=message.text))
```

---

## Customising serialization

Override `get_message_schema` to use different schemas for send and receive, or to vary them based on the action:

```python
class TypedView(WebSocketAPIView):
    @classmethod
    def get_message_schema(cls, action):
        if action == "receive":
            return IncomingMessage
        return OutgoingMessage

    async def handler(self) -> None:
        async for msg in self.messages:
            await self.send(OutgoingMessage(result=msg.value * 2))
```

---

## Disconnect timeout

`disconnect_timeout` (default `30`) is the number of seconds the cleanup block in `on_disconnect` is allowed to run before being cancelled. Increase it if your disconnect logic involves slow I/O:

```python
class SlowCleanupView(WebSocketAPIView):
    disconnect_timeout = 60

    async def on_disconnect(self) -> None:
        await flush_session_to_db(self.websocket)

    async def handler(self) -> None:
        async for message in self.messages:
            await self.send(message)
```

---

## Connecting from a browser

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/chat");

ws.onopen = () => {
    ws.send(JSON.stringify({ user: "alice", text: "hello" }));
};

ws.onmessage = (event) => {
    const reply = JSON.parse(event.data);
    console.log(reply.text);
};

ws.onclose = () => console.log("disconnected");
```

Messages are sent and received as **binary frames** (UTF-8 encoded JSON bytes).

---

## Complete example

```python
--8<-- "examples/websockets.py"
```
