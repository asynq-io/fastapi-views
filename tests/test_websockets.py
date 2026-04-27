from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from anyio import ClosedResourceError
from fastapi import Depends, FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from fastapi_views import ViewRouter
from fastapi_views.types import AnyTypeAdapter
from fastapi_views.views.websockets import WebSocketAPIView


class EchoView(WebSocketAPIView):
    name = "echo"

    async def handler(self) -> None:
        async for message in self.messages:
            await self.send(message)


class BroadcastView(WebSocketAPIView):
    name = "broadcast"

    async def handler(self) -> None:
        async for message in self.messages:
            await self.broadcast(message)


class HookView(WebSocketAPIView):
    name = "hook"
    connect_called: bool = False
    disconnect_called: bool = False

    async def on_connect(self) -> None:
        HookView.connect_called = True

    async def on_disconnect(self) -> None:
        HookView.disconnect_called = True

    async def handler(self) -> None:
        async for _ in self.messages:
            pass


class SchemaView(WebSocketAPIView):
    name = "schema"
    message_schema = str

    async def handler(self) -> None:
        async for message in self.messages:
            await self.send(message)


def ws_app(view_cls: type, path: str = "/ws") -> FastAPI:
    app = FastAPI()
    router = ViewRouter()
    router.register_websocket_view(view_cls, prefix=path)
    app.include_router(router)
    return app


def test_websocket_echo():
    with TestClient(ws_app(EchoView)).websocket_connect("/ws") as ws:
        ws.send_bytes(b'"hello"')
        data = ws.receive_bytes()
    assert data == b'"hello"'


def test_websocket_broadcast_sends_to_active_connection():
    with TestClient(ws_app(BroadcastView)).websocket_connect("/ws") as ws:
        ws.send_bytes(b'"broadcast"')
        data = ws.receive_bytes()
    assert data == b'"broadcast"'


def test_websocket_on_connect_hook():
    HookView.connect_called = False
    with TestClient(ws_app(HookView)).websocket_connect("/ws"):
        pass
    assert HookView.connect_called is True


def test_websocket_on_disconnect_hook():
    HookView.disconnect_called = False
    with TestClient(ws_app(HookView)).websocket_connect("/ws"):
        pass
    assert HookView.disconnect_called is True


def test_websocket_connections_isolated_per_subclass():
    class ViewA(WebSocketAPIView):
        async def handler(self) -> None:
            pass

    class ViewB(WebSocketAPIView):
        async def handler(self) -> None:
            pass

    assert ViewA._connections is not ViewB._connections
    assert ViewA._connections == []
    assert ViewB._connections == []


def test_websocket_connection_removed_after_disconnect():
    app = ws_app(EchoView)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_bytes(b'"ping"')
        ws.receive_bytes()
    assert EchoView._connections == []


def test_websocket_with_message_schema():
    with TestClient(ws_app(SchemaView)).websocket_connect("/ws") as ws:
        ws.send_bytes(b'"valid string"')
        data = ws.receive_bytes()
    assert data == b'"valid string"'


def test_get_message_schema_default_is_none():
    class MyView(WebSocketAPIView):
        async def handler(self) -> None:
            pass

    assert MyView.get_message_schema("receive") is None
    assert MyView.get_message_schema("send") is None


def test_get_message_schema_returns_class_attribute():
    assert SchemaView.get_message_schema("receive") is str
    assert SchemaView.get_message_schema("send") is str


def test_get_serializer_returns_any_type_adapter_without_schema():
    class MyView(WebSocketAPIView):
        async def handler(self) -> None:
            pass

    assert MyView.get_serializer("receive") is AnyTypeAdapter


def test_get_serializer_creates_and_caches_type_adapter():
    class CacheView(WebSocketAPIView):
        message_schema = float

        async def handler(self) -> None:
            pass

    first = CacheView.get_serializer("receive")
    assert isinstance(first, TypeAdapter)
    assert CacheView.get_serializer("receive") is first


def test_get_websocket_action_with_prefix():
    action = EchoView.get_websocket_action(prefix="/chat")
    assert action["path"] == "/chat"
    assert action["name"] == "echo"
    assert callable(action["endpoint"])


def test_get_websocket_action_uses_class_name_as_fallback():
    class UnnamedView(WebSocketAPIView):
        async def handler(self) -> None:
            pass

    action = UnnamedView.get_websocket_action()
    assert action["name"] == "UnnamedView"
    assert action["path"] == ""


def test_websocket_default_disconnect_timeout():
    assert WebSocketAPIView.disconnect_timeout == 30


def test_websocket_default_serializer_options():
    assert WebSocketAPIView.default_serializer_options == {"by_alias": True}


def test_register_abstract_websocket_view_raises():
    router = ViewRouter()
    with pytest.raises(TypeError, match="abstract"):
        router.register_websocket_view(WebSocketAPIView, prefix="/ws")


def test_register_websocket_view_registers_route():
    class SimpleView(WebSocketAPIView):
        name = "simple"

        async def handler(self) -> None:
            pass

    app = FastAPI()
    router = ViewRouter()
    router.register_websocket_view(SimpleView, prefix="/simple")
    app.include_router(router)
    assert any(r.path == "/simple" for r in app.routes)


def test_register_websocket_view_with_dependencies():
    def my_dep() -> None:
        pass

    class DepView(WebSocketAPIView):
        name = "dep"

        async def handler(self) -> None:
            pass

    app = FastAPI()
    router = ViewRouter()
    router.register_websocket_view(
        DepView, prefix="/dep", dependencies=[Depends(my_dep)]
    )
    app.include_router(router)
    assert any(r.path == "/dep" for r in app.routes)


def test_serialize_message_skips_validation_when_disabled():
    class NoValidateView(WebSocketAPIView):
        message_schema = str
        validate_on_send = False

        async def handler(self) -> None:
            pass

    mock_ws = MagicMock()
    view = NoValidateView.__new__(NoValidateView)
    view.websocket = mock_ws
    view.serializer_options = NoValidateView.default_serializer_options.copy()
    result = view._serialize_message("hello")
    assert result == b'"hello"'


def test_safe_send_swallows_websocket_disconnect():
    class SimpleView(WebSocketAPIView):
        async def handler(self) -> None:
            pass

    mock_ws = MagicMock()
    mock_ws.send_bytes = AsyncMock(side_effect=WebSocketDisconnect())
    view = SimpleView.__new__(SimpleView)
    view.websocket = mock_ws
    view.logger = MagicMock()

    async def run():
        await view._safe_send(b"data")

    asyncio.run(run())
    view.logger.warning.assert_called_once()


def test_safe_send_swallows_closed_resource_error():
    class SimpleView(WebSocketAPIView):
        async def handler(self) -> None:
            pass

    mock_ws = MagicMock()
    mock_ws.send_bytes = AsyncMock(side_effect=ClosedResourceError())
    view = SimpleView.__new__(SimpleView)
    view.websocket = mock_ws
    view.logger = MagicMock()

    async def run():
        await view._safe_send(b"data")

    asyncio.run(run())
    view.logger.warning.assert_called_once()


def test_register_websocket_view_without_dependencies():
    class NoDepsView(WebSocketAPIView):
        name = "nodeps"

        async def handler(self) -> None:
            pass

    app = FastAPI()
    router = ViewRouter()
    router.register_websocket_view(NoDepsView, prefix="/nodeps")
    app.include_router(router)
    assert any(r.path == "/nodeps" for r in app.routes)
