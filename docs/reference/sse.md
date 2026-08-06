# Server-Sent Events

Streaming endpoints over `text/event-stream`. There are two entry points:

- **`ServerSentEventsAPIView`** (`fastapi_views.views.sse`) — a view whose abstract `events` action yields events; the route, framing, and OpenAPI content are generated for you.
- **`@sse_route`** (`fastapi_views.views.functools`) — decorate any method on a `View` to turn its (async) iterator of events into a streaming route.

Event models live in `fastapi_views.models` (`BaseServerSentEvent`, `IdBaseServerSentEvent`, `AnyServerSentEvent`); any object matching the `fastapi_views.types.ServerSentEventType` protocol (`id`, `event`, `data`, `retry`) can be yielded.

For a complete walkthrough see [Server Side Events](../usage/sse.md).

---

## Views

::: fastapi_views.views.sse
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

## Route decorator

::: fastapi_views.views.functools.sse_route
    handler: python
    options:
        show_root_heading: true
        show_signature_annotations: true

---

## Streaming event models

Discriminated lifecycle events for long-running streamed operations, in
`fastapi_views.models.streaming`.

::: fastapi_views.models.streaming
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
