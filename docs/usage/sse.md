# Server-Sent Events

FastAPI Views makes streaming Server-Sent Events (SSE) straightforward. It provides a dedicated `ServerSentEventsAPIView` base class and an `@sse_route` decorator that handle SSE framing, content-type headers, and Pydantic serialization automatically.

---

## What are Server-Sent Events?

Server-Sent Events are a standard web API for receiving a unidirectional stream of events from a server over a persistent HTTP connection. The client connects once and the server pushes messages whenever it has data. Unlike WebSockets, SSE uses plain HTTP and works well through proxies, firewalls, and load balancers.

Each message in the stream has the format:

```
id: <event-id>
event: <event-name>
data: <json-payload>

```

FastAPI Views generates this format automatically from your yielded events.

---

## Event models

Every yielded event is a Pydantic model with `id`, `event`, `data`, and an optional `retry` field. The library ships with:

* `fastapi_views.models.AnyServerSentEvent` — a generic event with `id: str` (auto-generated UUID by default), `event: str`, and untyped `data`. Use it for ad-hoc streams.
* `fastapi_views.models.BaseServerSentEvent` / `IdBaseServerSentEvent` — bases for defining your own typed event models (fix `event` with a `Literal`, type `data` with your payload schema).
* `fastapi_views.models.streaming` — ready-made response lifecycle events loosely modeled on the OpenAI responses API: `ResponseStarted`, `ResponseResult[T]`, `ResponseError`, `ResponseFinished`, `ResponseCancelled`, and the discriminated union alias `ResponseEvent[T]`.

---

## `ServerSentEventsAPIView`

Subclass `ServerSentEventsAPIView` and implement the `events` async generator method. Yield event model instances; set `response_schema` to the event model so the stream is documented and the `data` field is serialized with the right schema.

```python
import asyncio
from collections.abc import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.models import AnyServerSentEvent
from fastapi_views.views import ServerSentEventsAPIView


class StockPrice(BaseModel):
    symbol: str
    price: float


class StockPriceSSEView(ServerSentEventsAPIView):
    response_schema = AnyServerSentEvent

    async def events(self) -> AsyncIterator[AnyServerSentEvent]:
        yield AnyServerSentEvent(event="price", data={"symbol": "AAPL", "price": 182.50})
        await asyncio.sleep(1)
        yield AnyServerSentEvent(event="price", data={"symbol": "AAPL", "price": 183.10})


router = ViewRouter()
router.register_view(StockPriceSSEView, prefix="/stocks")

app = FastAPI(title="Stock Prices")
app.include_router(router)
configure_app(app)
```

The `response_schema` is the **full event model**: its JSON schema becomes the documented `text/event-stream` content, and its `data` field annotation is used to validate and serialize each event's `data`. When it is not set, `AnyServerSentEvent` is assumed. The endpoint is registered as `GET /stocks` and returns `text/event-stream`.

### Event IDs and retry interval

`id` and `retry` are regular fields on the yielded event — set them per event:

```python
class MySSEView(ServerSentEventsAPIView):
    response_schema = AnyServerSentEvent

    async def events(self) -> AsyncIterator[AnyServerSentEvent]:
        # `id` defaults to a random UUID per event; pass your own for
        # sequential IDs, and `retry` to suggest a client reconnect delay.
        yield AnyServerSentEvent(id="1", event="tick", data={"n": 1}, retry=5000)
```

### Typed lifecycle events

For result streams, reuse the prebuilt events from `fastapi_views.models.streaming`:

```python
from fastapi_views.models.streaming import ResponseEvent, ResponseFinished, ResponseResult


class ItemStreamView(ServerSentEventsAPIView):
    response_schema = ResponseEvent[Item]

    async def events(self) -> AsyncIterator[ResponseEvent[Item]]:
        yield ResponseResult.new(items=[Item(id=1, name="first")], index=1)
        yield ResponseFinished.new()
```

---

## `@sse_route` decorator

Use `@sse_route` to add additional SSE endpoints as named methods on any view class, alongside standard CRUD actions:

```python
from fastapi_views.models import AnyServerSentEvent
from fastapi_views.views import ServerSentEventsAPIView, sse_route


class EventView(ServerSentEventsAPIView):
    response_schema = AnyServerSentEvent

    async def events(self) -> AsyncIterator[AnyServerSentEvent]:
        # Main SSE endpoint at GET /
        yield AnyServerSentEvent(event="data", data={"id": 1, "name": "first"})

    @sse_route("/custom-events", response_model=AnyServerSentEvent)
    async def custom_events(self) -> AsyncIterator[AnyServerSentEvent]:
        # Additional SSE endpoint at GET /custom-events
        yield AnyServerSentEvent(event="data", data={"id": 10, "name": "custom"})
```

`@sse_route` accepts the same keyword arguments as `@get`, plus `response_model` (the full event model, like `response_schema` above) and an optional `serializer_options` dict for Pydantic serialization settings. Sync generators are supported as well and are iterated in a threadpool.

---

## Accepting path and query parameters

SSE views support FastAPI's standard parameter injection. Add parameters to the `events` method signature:

```python
class FilteredSSEView(ServerSentEventsAPIView):
    response_schema = AnyServerSentEvent

    async def events(self, symbol: str) -> AsyncIterator[AnyServerSentEvent]:
        # Accessible at GET /?symbol=AAPL
        async for price in live_price_feed(symbol):
            yield AnyServerSentEvent(event="price", data={"symbol": symbol, "price": price})
```

---

## Connecting from a browser

```javascript
const source = new EventSource("/stocks");

source.addEventListener("price", (event) => {
    const data = JSON.parse(event.data);
    console.log(`${data.symbol}: $${data.price}`);
});

source.onerror = () => {
    console.error("SSE connection lost, browser will reconnect automatically");
};
```

---

## OpenAPI documentation

FastAPI Views registers SSE endpoints with the correct `text/event-stream` response schema in the OpenAPI spec, derived from the event model (`response_schema` / `response_model`). Models referenced by the event travel in `$defs` and are relocated into `components/schemas` by `configure_app`, so the stream's shape is visible in the Swagger UI and to API client generators.

---

## Complete example

```python
--8<-- "examples/sse.py"
```
