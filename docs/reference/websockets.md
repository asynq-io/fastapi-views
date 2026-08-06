# WebSocket Views

Class-based WebSocket endpoint. Import from `fastapi_views.views.websockets`.

Requires the `websockets` extra (`pip install fastapi-views[websockets]`) for a WebSocket
protocol implementation. Register views with
[`ViewRouter.register_websocket_view`](#fastapi_views.router.ViewRouter.register_websocket_view),
whose `prefix` argument is the full route path.

The `receive` / `send` directions are named by `fastapi_views.types.WebSocketAction`
(`Literal["receive", "send"]`) and drive `get_message_schema` / `get_serializer`.

The wire protocol is **binary-only**: frames are UTF-8 encoded JSON read with
`receive_bytes()` and written with `send_bytes()`. A text frame from the client ends the
receive loop and closes the connection, as does a `ValidationError` or a disconnect.

`__init_subclass__` gives every subclass its own `_connections` list and `_serializers`
adapter cache (the base class keeps an empty `_serializers` default because `get_serializer`
is a classmethod reachable on the ABC itself) and calls `super().__init_subclass__(**kwargs)`
so cooperative mixins keep working.

For a complete walkthrough see [WebSockets](../usage/websockets.md).

---

::: fastapi_views.views.websockets
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

## Registration

::: fastapi_views.router.ViewRouter.register_websocket_view
    handler: python
    options:
        show_root_heading: true
        show_signature_annotations: true
