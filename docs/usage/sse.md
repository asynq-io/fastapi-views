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

FastAPI Views generates this format automatically from your yielded data.

---

## `ServerSentEventsAPIView`

Subclass `ServerSentEventsAPIView` and implement the `events` async generator method. Yield dictionaries matching the `ServerSentEvent` schema (keys: `event`, `data`, and optionally `id` and `retry`).

```python
import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views import ServerSentEventsAPIView


class StockPrice(BaseModel):
    symbol: str
    price: float


class StockPriceSSEView(ServerSentEventsAPIView):
    response_schema = StockPrice

    async def events(self) -> AsyncIterator[Any]:
        yield {"event": "price", "data": {"symbol": "AAPL", "price": 182.50}}
        await asyncio.sleep(1)
        yield {"event": "price", "data": {"symbol": "AAPL", "price": 183.10}}
        await asyncio.sleep(1)
        yield {"event": "price", "data": {"symbol": "AAPL", "price": 181.90}}


router = ViewRouter()
router.register_view(StockPriceSSEView, prefix="/stocks")

app = FastAPI(title="Stock Prices")
app.include_router(router)
configure_app(app)
```

The `response_schema` is used to validate and serialize the `data` field of each event. The endpoint is registered as `GET /stocks` and returns `text/event-stream`.

### Event IDs and retry interval

Override the `event_id` property and `retry` property to customize the SSE metadata sent with each event:

```python
class MySSEView(ServerSentEventsAPIView):
    response_schema = MySchema

    @property
    def event_id(self) -> str:
        # The default implementation already returns a random UUID per event.
        # Override this to use sequential IDs or any other scheme.
        return "my-custom-id"

    @property
    def retry(self) -> int | None:
        # Suggest a client reconnect delay of 5000 ms
        return 5000

    async def events(self) -> AsyncIterator[Any]:
        ...
```

---

## `@sse_route` decorator

Use `@sse_route` to add additional SSE endpoints as named methods on any view class, alongside standard CRUD actions:

```python
import asyncio
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel
from fastapi_views.views import ServerSentEventsAPIView, sse_route


class APIModel(BaseModel):
    id: int
    name: str


class EventView(ServerSentEventsAPIView):
    response_schema = APIModel

    async def events(self) -> AsyncIterator[Any]:
        # Main SSE endpoint at GET /
        yield {"event": "data", "data": {"id": 1, "name": "first"}}
        await asyncio.sleep(2)
        yield {"event": "data", "data": {"id": 2, "name": "second"}}

    @sse_route("/custom-events", response_model=APIModel)
    async def custom_events(self) -> AsyncIterator[Any]:
        # Additional SSE endpoint at GET /custom-events
        yield {"event": "data", "data": {"id": 10, "name": "custom"}}
```

`@sse_route` accepts the same keyword arguments as `@get`, plus `response_model` and an optional `serializer_options` dict for Pydantic serialization settings.

---

## Accepting path and query parameters

SSE views support FastAPI's standard parameter injection. Add parameters to the `events` method signature:

```python
class FilteredSSEView(ServerSentEventsAPIView):
    response_schema = StockPrice

    async def events(self, symbol: str) -> AsyncIterator[Any]:
        # Accessible at GET /?symbol=AAPL
        async for price in live_price_feed(symbol):
            yield {"event": "price", "data": {"symbol": symbol, "price": price}}
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

FastAPI Views registers SSE endpoints with the correct `text/event-stream` response schema in the OpenAPI spec, derived from the `ServerSentEvent[response_schema]` model. The stream's data shape is visible in the Swagger UI and to API client generators.

---

## Complete example

```python
--8<-- "examples/sse.py"
```
