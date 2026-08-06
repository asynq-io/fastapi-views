# Server-Sent Events

FastAPI Views makes streaming Server-Sent Events (SSE) straightforward. It provides a dedicated `ServerSentEventsAPIView` base class and an `@sse_route` decorator that handle SSE framing, content-type headers, and Pydantic serialization automatically.

---

## What are Server-Sent Events?

Server-Sent Events are a standard web API for receiving a unidirectional stream of events from a server over a persistent HTTP connection. The client connects once and the server pushes messages whenever it has data. Unlike WebSockets, SSE uses plain HTTP and works well through proxies, firewalls, and load balancers.

Each message in the stream is framed as:

```
id: <event-id>
event: <event-name>
data: <json-payload>
retry: <milliseconds>

```

`data` is always a single line of JSON, `retry` is emitted only when the event sets it, and the blank line terminates the message. FastAPI Views generates this framing automatically from your yielded events.

---

## Event models

An event is any object exposing `id`, `event`, `data` and `retry` — formally the
`fastapi_views.types.ServerSentEventType` protocol. In practice you yield one of the
Pydantic models shipped in `fastapi_views.models`:

| Model | Fields | Use for |
|---|---|---|
| `BaseServerSentEvent` | `retry: int \| None = None` | base for fully custom events (declare your own `id`, `event`, `data`) |
| `IdBaseServerSentEvent` | `BaseServerSentEvent` + `id: UUID` (auto `uuid4`) | base for typed events that want an auto-generated UUID id |
| `AnyServerSentEvent` | `id: str` (auto UUID string), `event: str`, `data: Any`, `retry` | ad-hoc, untyped streams |

All three declare `__content_type__ = "text/event-stream"`, which is the media type they are
documented under in OpenAPI.

A custom typed event narrows `event` to a `Literal` and types `data` with a payload schema:

```python
from typing import Literal

from pydantic import BaseModel

from fastapi_views.models import IdBaseServerSentEvent


class Price(BaseModel):
    symbol: str
    price: float


class PriceEvent(IdBaseServerSentEvent):
    event: Literal["price"] = "price"
    data: Price
```

---

## Streaming (response lifecycle) events

`fastapi_views.models.streaming` ships a ready-made set of lifecycle events, loosely
inspired by the OpenAI responses API. Each is an `IdBaseServerSentEvent` with a fixed
`event` name and a typed `data` payload, plus a `new(...)` classmethod that builds the
payload for you:

| Event | `event` name | `data` payload |
|---|---|---|
| `ResponseStarted` | `response.started` | `StartedData` — `type`, `timestamp` |
| `ResponseResult[T]` | `response.result` | `ResultData[T]` — `type`, `items: list[T]`, `index`, `total_results` |
| `ResponseError` | `response.error` | `ErrorData` — `type`, `error: str` |
| `ResponseFinished` | `response.finished` | `FinishedData` — `type`, `timestamp`, `duration_s` |
| `ResponseCancelled` | `response.cancelled` | `CancelledData` — `type`, `timestamp` |

`ResponseEvent[T]` is a `TypeAliasType` union of all five, discriminated on `event` — use it as
the `response_schema` / `response_model` so OpenAPI documents every event the stream may emit.

```python
from fastapi_views.models.streaming import (
    ResponseCancelled,
    ResponseError,
    ResponseEvent,
    ResponseFinished,
    ResponseResult,
    ResponseStarted,
    ResultData,
)

yield ResponseStarted.new()
yield ResponseResult[Item](
    data=ResultData[Item](items=[Item(id=1, name="first")], index=1, total_results=2),
)
yield ResponseFinished.new(duration_s=3)
```

`timestamp` fields default to the current UTC time as whole seconds, `duration_s` is a
`NonNegativeInt`, and every event gets a fresh `uuid4` `id`.

!!! note
    `ResponseResult.new(items=...)` validates `items` against the *unparameterized*
    `ResultData` payload, i.e. `list[dict[str, Any]]` — so pass plain dicts to it.
    To pass model instances, build the payload explicitly as `ResultData[Item](...)`
    as shown above.

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

The `response_schema` is the **full event model**: its JSON schema becomes the documented `text/event-stream` content, and its `data` field annotation drives the serializer used for each event's `data`. When it is not set, `AnyServerSentEvent` is assumed. The endpoint is registered as `GET /stocks` with a `StreamingResponse` of media type `text/event-stream`.

The status code defaults to `200`; override it by annotating `events` with
`@override(status_code=...)` (importable from `fastapi_views.views`), which sets both the
documented and the returned status.

### Response headers

`sse_headers` is a class attribute holding the headers sent with the stream. It defaults to:

```python
class ServerSentEventsAPIView(APIView):
    sse_headers = {
        "Cache-Control": "no-store",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
```

Override it on your subclass to add or replace headers (for example to drop `X-Accel-Buffering` when you are not behind nginx).

!!! note
    Unlike regular `APIView` responses, event `data` is dumped without the view's
    `serializer_options` (so `by_alias` is **not** applied). Use `@sse_route`'s
    `serializer_options` argument when you need alias or exclusion behaviour.

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
from fastapi_views.models.streaming import (
    ResponseEvent,
    ResponseFinished,
    ResponseResult,
    ResultData,
)


class ItemStreamView(ServerSentEventsAPIView):
    response_schema = ResponseEvent[Item]

    async def events(self) -> AsyncIterator[ResponseEvent[Item]]:
        yield ResponseResult[Item](
            data=ResultData[Item](items=[Item(id=1, name="first")], index=1),
        )
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

### Signature

```python
@sse_route(
    path: str = "",
    serializer_options: SerializerOptions | None = None,
    headers: dict[str, str] | None = None,
    **kwargs,  # any RouteOptions accepted by @route
)
```

| Argument | Description |
|---|---|
| `path` | Route path appended to the view's prefix (default `""`) |
| `serializer_options` | Pydantic `dump_json` options applied to each event's `data` (`by_alias`, `exclude_none`, `include`, `exclude`, `exclude_unset`, `exclude_defaults`, `round_trip`). Defaults to no options |
| `headers` | Response headers. When omitted, defaults to `Cache-Control: no-store`, `Connection: keep-alive`, `X-Accel-Buffering: no`. Passing a dict **replaces** the defaults, so re-include the ones you still want |
| `response_model` | The full event model, as with `response_schema`. Defaults to `AnyServerSentEvent` |
| `**kwargs` | Any other route option (`tags`, `dependencies`, `summary`, `responses`, `status_code`, …) |

The decorator forces `methods=["GET"]`, `response_class=StreamingResponse` and
`response_model=None` on the underlying route (the event model is documented through
`responses[status_code]["content"]` instead, since FastAPI cannot validate a stream),
and returns a `StreamingResponse` with media type `text/event-stream`.

Both async and sync generators are supported; sync generators are iterated in a
threadpool via `starlette.concurrency.iterate_in_threadpool`.

!!! note
    `status_code` only affects which status key the event schema is documented under —
    the returned `StreamingResponse` is always `200`. For a non-`200` SSE response, use
    `ServerSentEventsAPIView` with `@override(status_code=...)` on `events` instead.

```python
@sse_route(
    "/custom-events",
    response_model=ResponseEvent[Item],
    serializer_options={"by_alias": True, "exclude_none": True},
    headers={"Cache-Control": "no-store", "X-Stream": "items"},
    tags=["streaming"],
)
async def custom_events(self) -> AsyncIterator[ResponseEvent[Item]]: ...
```

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

Because a stream cannot be validated by FastAPI, SSE routes are registered with
`response_model=None` and document the event model as explicit response *content*
instead. `fastapi_views.views.functools.sse_openapi_content` builds it:

* a model class (any `OpenAPIBase` subclass, which includes every SSE model above)
  renders itself via `get_openapi_content()`, keyed by its `__content_type__`
  (`text/event-stream`);
* anything else — a union, a `TypeAliasType` such as `ResponseEvent[Item]` — is rendered
  through a pydantic `TypeAdapter` in `serialization` mode and keyed by
  `AnyServerSentEvent.__content_type__`.

Both use `ref_template="#/components/schemas/{model}"`, so nested models travel in `$defs`
and are relocated into `components/schemas` by `configure_app`. A `ResponseEvent[Item]`
stream therefore shows up as a discriminated `oneOf` over
`ResponseStarted` / `ResponseResult_Item_` / `ResponseError` / `ResponseCancelled` /
`ResponseFinished` in the Swagger UI and to API client generators.

The companion helper `sse_data_annotation(model)` extracts the `data` field annotation used
to serialize each payload, falling back to `Any` for unions and type aliases (so pydantic
infers the serializer from the runtime value).

---

## Complete example

```python
--8<-- "examples/sse.py"
```
