# WebSockets

FastAPI Views provides `WebSocketAPIView` — a class-based view for WebSocket endpoints with built-in Pydantic validation, connection tracking, broadcast helpers, and clean disconnect handling.

Install the optional extra to get a WebSocket protocol implementation for uvicorn:

```shell
pip install fastapi-views[websockets]
```

---

## `WebSocketAPIView`

Subclass `WebSocketAPIView` and implement the `handler` async method. The view accepts the
connection, registers it in the per-class connection list, calls `on_connect`, then runs the
receive loop and your `handler` concurrently in an `anyio` task group. When either finishes,
the other is cancelled, the connection is removed, the socket is closed and `on_disconnect`
runs.

```python
from pydantic import BaseModel
from fastapi import FastAPI

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.websockets import WebSocketAPIView


class ChatMessage(BaseModel):
    user: str
    text: str


class ChatView(WebSocketAPIView[ChatMessage]):
    name = "chat"
    message_schema = ChatMessage

    async def handler(self) -> None:
        async for message in self.messages:
            await self.send(message)


router = ViewRouter()
router.register_websocket_view(ChatView, prefix="/ws/chat")

app = FastAPI()
app.include_router(router)
configure_app(app)
```

### Type parameters

`WebSocketAPIView` is generic over two type variables:

| Variable | Description |
|---|---|
| `RecvT` | The *receive* type — what `self.messages` yields |
| `SendT` | The *send* type — what `send` / `broadcast` accept. Defaults to `RecvT` |

So `WebSocketAPIView[ChatMessage]` is a symmetric view, and
`WebSocketAPIView[ChatMessage, ChatReply]` receives `ChatMessage` and sends `ChatReply`.
The generics are for typing only — runtime validation comes from `get_message_schema`.

### Class attributes

| Attribute | Default | Description |
|---|---|---|
| `name` | class name | Route name; also used for the logger name |
| `message_schema` | `None` | Schema used to validate **both** received and sent messages. `None` means "no validation" (an `Any` adapter) |
| `validate_on_send` | `True` | Validate outgoing messages against the send schema before dumping |
| `default_serializer_options` | `{"by_alias": True}` | Pydantic `dump_json` options; copied to `self.serializer_options` per connection |
| `disconnect_timeout` | `30` | Seconds allowed for the (shielded) disconnect cleanup block |
| `logger` | `logging.getLogger(f"{module}:{name}")` | Set automatically in `__init_subclass__` |
| `_connections` | `[]` | Per-subclass list of active `WebSocket` objects |
| `_serializers` | `{}` | Per-subclass `TypeAdapter` cache, keyed by schema |

Per-connection instance attributes set in `__init__`: `self.websocket`,
`self.serializer_options` (a mutable copy of the defaults) and `self.validation_context`
(passed to pydantic as the validation context when receiving; `None` by default).

`__init_subclass__` creates `_connections`, `_serializers` and `logger` for each subclass and
calls `super().__init_subclass__(**kwargs)`, so cooperative mixins that also define
`__init_subclass__` keep working.

---

## Sending and broadcasting

| Method | Description |
|---|---|
| `await self.send(message)` | Serialize and send to the current connection |
| `await self.broadcast(message)` | Serialize and send to **all** active connections of this view class, concurrently |

Both serialize through `get_serializer("send")` and send a **binary** frame. When
`validate_on_send` is `True` the message is validated against the send schema first;
otherwise it is dumped with `warnings=False`. `WebSocketDisconnect` and
`anyio.ClosedResourceError` are caught and logged as warnings, so a dead client never
breaks the broadcast.

---

## Receiving messages

`self.messages` is an `AsyncIterable` that yields validated, deserialized messages:

```python
async def handler(self) -> None:
    async for message in self.messages:
        # message is already a validated `message_schema` instance
        await self.broadcast(message)
```

Incoming **binary** frames are read with `websocket.receive_bytes()` and validated as JSON
with the schema returned by `get_message_schema("receive")`, using `self.validation_context`
as the pydantic validation context. Validated messages are handed to `handler` over an
`anyio` memory object stream.

The receive loop ends cleanly on any of three conditions, each logged as a warning before the
task group is cancelled and the connection torn down:

* a `ValidationError` — the frame was not valid JSON for the receive schema;
* a `WebSocketDisconnect` — the client went away;
* a `KeyError` — the client sent a **text** frame, which `receive_bytes()` cannot read.

The protocol is binary-only by design: a text frame is not decoded as a fallback, it simply
closes the connection.

---

## `receive` and `send` actions

Serialization is keyed on a `WebSocketAction` — `Literal["receive", "send"]`:

| Method | Description |
|---|---|
| `get_message_schema(action)` | Returns the schema for that direction. Returns `cls.message_schema` for both by default |
| `get_serializer(action)` | Returns a cached `TypeAdapter` for that schema, or `AnyTypeAdapter` when the schema is `None` |

Because the default `get_message_schema` ignores `action`, a single `message_schema`
validates **both** directions. If your view sends a different type than it receives, you
**must** override `get_message_schema` — otherwise `send` will try to validate the outgoing
message against the incoming schema and fail:

```python
from fastapi_views.types import WebSocketAction


class ChatView(WebSocketAPIView[ChatMessage, ChatReply]):
    message_schema = ChatMessage

    @classmethod
    def get_message_schema(cls, action: WebSocketAction) -> type[BaseModel]:
        return ChatReply if action == "send" else ChatMessage
```

Adapters are cached in `_serializers`, a dict created fresh for each subclass in
`__init_subclass__` (exactly like `_connections`) and keyed by schema — sibling views never
share adapters.

---

## Connection lifecycle hooks

Override `on_connect` and `on_disconnect` to run logic when a client connects or disconnects:

```python
class RoomView(WebSocketAPIView[ChatMessage]):
    message_schema = ChatMessage

    async def on_connect(self) -> None:
        self.logger.info("New connection, total=%d", len(self._connections))

    async def on_disconnect(self) -> None:
        self.logger.info("Client left")

    async def handler(self) -> None:
        async for message in self.messages:
            await self.broadcast(message)
```

`on_connect` runs after `websocket.accept()` and after the socket has been appended to
`_connections`, but before the receive loop and `handler` start. `on_disconnect` runs after
the connection is removed from `_connections` and the socket is closed. The whole cleanup
block is shielded from cancellation and bounded by `disconnect_timeout`.

Cleanup is idempotent: deregistration is skipped for a connection that was never registered,
so if `accept()` itself fails the original error propagates instead of being masked by the
cleanup. `close()` and `on_disconnect` still run in that case.

`self.logger` is a `logging.Logger` created per subclass as `f"{module}:{name}"`.

---

## Per-class state

`_connections` is a class-level list of all active `WebSocket` objects, created fresh for each
subclass in `__init_subclass__` — so sibling views never share connections. `_serializers` is
created the same way, so two views declaring the same `message_schema` still get their own
`TypeAdapter` cache. Use `_connections` to inspect or act on connected clients:

```python
class StatsView(WebSocketAPIView[Ping, StatusMessage]):
    message_schema = Ping

    @classmethod
    def get_message_schema(cls, action):
        return StatusMessage if action == "send" else Ping

    async def handler(self) -> None:
        async for _ in self.messages:
            await self.send(StatusMessage(online=len(self._connections)))
```

---

## Registering the view

`ViewRouter.register_websocket_view` adds the view as a WebSocket route:

```python
ViewRouter.register_websocket_view(
    view: type[WebSocketAPIView],
    prefix: str = "",
    dependencies: Sequence[Depends] | None = None,
) -> None
```

* `prefix` is the **full route path** (there is no separate `path` on the view), so
  `register_websocket_view(ChatView, prefix="/ws/chat")` serves `ChatView` at `/ws/chat`;
  path parameters work too, e.g. `prefix="/ws/{room}"`.
* `dependencies` are passed straight to `add_api_websocket_route` as route-level
  dependencies.
* Registering an abstract view (one that has not implemented `handler`) raises
  `TypeError: Cannot register abstract view ...`.
* Under the hood it calls `view.get_websocket_action(prefix)`, which returns
  `{"path": ..., "endpoint": ..., "name": view.get_name()}`.

WebSocket routes are not part of the OpenAPI document, so they do not appear in
`app.openapi()["paths"]` or the Swagger UI.

---

## FastAPI dependency injection

Path and query parameters, as well as `Depends(...)` dependencies, are supported through the `handler` signature:

```python
from typing import Annotated

from fastapi import Depends, Query


async def get_current_user(token: Annotated[str, Query()]) -> str:
    return token  # simplified


class AuthenticatedView(WebSocketAPIView[ChatMessage]):
    message_schema = ChatMessage

    async def handler(self, user: Annotated[str, Depends(get_current_user)]) -> None:
        async for message in self.messages:
            if message.user == user:
                await self.send(message)
```

The `handler` signature is copied onto the generated endpoint, with the first parameter
replaced by `Depends(cls)` and the rest turned keyword-only — the same mechanism regular
views use. Plain path and query parameters work without `Depends` as well:

```python
router.register_websocket_view(RoomView, prefix="/ws/{room}")


class RoomView(WebSocketAPIView[ChatMessage]):
    message_schema = ChatMessage

    async def handler(self, room: str, token: str | None = None) -> None: ...
```

---

## Disconnect timeout

`disconnect_timeout` (default `30`) bounds the shielded cleanup block that removes the
connection, closes the socket and runs `on_disconnect`. Increase it if your disconnect logic
involves slow I/O:

```python
class SlowCleanupView(WebSocketAPIView[ChatMessage]):
    message_schema = ChatMessage
    disconnect_timeout = 60

    async def on_disconnect(self) -> None:
        await flush_session_to_db(self.websocket)

    async def handler(self) -> None:
        async for message in self.messages:
            await self.send(message)
```

---

## Connecting from a browser

Messages are sent and received as **binary frames** of UTF-8 encoded JSON. A text frame is not
accepted by the receive loop — sending one logs a warning and closes the connection rather
than raising — so encode outgoing payloads and read incoming ones as `ArrayBuffer`:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/chat");
ws.binaryType = "arraybuffer";

ws.onopen = () => {
    const payload = JSON.stringify({ user: "alice", text: "hello" });
    ws.send(new TextEncoder().encode(payload));
};

ws.onmessage = (event) => {
    const reply = JSON.parse(new TextDecoder().decode(event.data));
    console.log(reply.text);
};

ws.onclose = () => console.log("disconnected");
```

---

## Complete example

```python
--8<-- "examples/websockets.py"
```
