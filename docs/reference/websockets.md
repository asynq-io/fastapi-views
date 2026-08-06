# WebSocket Views

Class-based WebSocket endpoint. Import from `fastapi_views.views.websockets`.

Requires the `websockets` extra (`pip install fastapi-views[websockets]`) for a WebSocket
protocol implementation. Register views with
[`ViewRouter.register_websocket_view`](#fastapi_views.router.ViewRouter.register_websocket_view),
whose `prefix` argument is the full route path.

The `receive` / `send` directions are named by `fastapi_views.types.WebSocketAction`
(`Literal["receive", "send"]`) and drive `get_message_schema` / `get_serializer`.

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
