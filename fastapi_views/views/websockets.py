import functools
from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Awaitable, Callable
from logging import Logger, getLogger
from typing import Any, ClassVar, Generic, TypeVar

from anyio import (
    CancelScope,
    ClosedResourceError,
    create_memory_object_stream,
    create_task_group,
    move_on_after,
)
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError
from typing_extensions import ParamSpec

from fastapi_views.types import (
    AnyTypeAdapter,
    SerializerOptions,
    TypeAdapterMap,
    WebSocketAction,
)

from .mixins import DependencyMixin

P = ParamSpec("P")
S = TypeVar("S")
R = TypeVar("R")


class WebSocketAPIView(DependencyMixin, ABC, Generic[P, S, R]):
    logger: Logger
    name: str
    message_schema: Any | None = None
    default_serializer_options: ClassVar[SerializerOptions] = {
        "by_alias": True,
    }
    disconnect_timeout: int = 30
    _serializers: ClassVar[TypeAdapterMap] = {}
    _connections: ClassVar[list[WebSocket]]

    def __init_subclass__(cls) -> None:
        cls._connections = []
        cls.logger = getLogger(f"{cls.__module__}:{cls.get_name()}")

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.validation_context = None
        self.serializer_options = self.default_serializer_options.copy()
        self._snd, self._rcv = create_memory_object_stream()

    @classmethod
    def get_name(cls) -> str:
        return getattr(cls, "name", cls.__name__)

    @classmethod
    def get_message_schema(cls, action: WebSocketAction) -> Any:  # noqa: ARG003
        return cls.message_schema

    @classmethod
    def get_serializer(cls, action: WebSocketAction) -> TypeAdapter[Any]:
        schema = cls.get_message_schema(action)
        if schema is None:
            return AnyTypeAdapter
        if schema not in cls._serializers:
            cls._serializers[schema] = TypeAdapter(schema)
        return cls._serializers[schema]

    async def _receiver(self, cancel_scope: CancelScope) -> None:
        await self.websocket.accept()
        self._connections.append(self.websocket)
        serializer = self.get_serializer("receive")
        try:
            async with self._snd:
                while True:
                    data = await self.websocket.receive_bytes()
                    message = serializer.validate_json(
                        data, context=self.validation_context
                    )
                    await self._snd.send(message)
        except (ValidationError, WebSocketDisconnect) as e:
            self.logger.warning(
                "Exception while receiving data from websocket", exc_info=e
            )
            cancel_scope.cancel()

    async def _handler(
        self, fn: Callable[[], Awaitable[None]], cancel_scope: CancelScope
    ) -> None:
        try:
            async with self._rcv:
                await fn()
        finally:
            cancel_scope.cancel()

    @classmethod
    def get_websocket_endpoint(cls) -> Callable:

        async def endpoint(
            self: WebSocketAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> None:
            try:
                await self.on_connect()
                fn = functools.partial(self.handler, *args, **kwargs)
                async with create_task_group() as tg:
                    tg.start_soon(self._receiver, tg.cancel_scope)
                    tg.start_soon(self._handler, fn, tg.cancel_scope)
            finally:
                with move_on_after(self.disconnect_timeout, shield=True):
                    self._connections.remove(self.websocket)
                    await self.websocket.close()
                    await self.on_disconnect()

        cls._patch_endpoint_signature(endpoint, cls.handler)
        return endpoint

    @classmethod
    def get_websocket_action(cls, prefix: str = "") -> dict[str, Any]:
        endpoint = cls.get_websocket_endpoint()
        return {
            "path": prefix,
            "endpoint": endpoint,
            "name": cls.get_name(),
        }

    async def _safe_send(self, data: bytes, websocket: WebSocket | None = None) -> None:
        websocket = websocket or self.websocket
        try:
            await websocket.send_bytes(data)
        except (WebSocketDisconnect, ClosedResourceError) as e:
            self.logger.warning("Error sending bytes to websocket", exc_info=e)

    async def send(self, message: S) -> None:
        serializer = self.get_serializer("send")
        data = serializer.dump_json(message, **self.serializer_options)
        await self._safe_send(data)

    async def broadcast(self, message: S) -> None:
        serializer = self.get_serializer("send")
        data = serializer.dump_json(message, **self.serializer_options)
        async with create_task_group() as tg:
            for connection in self._connections:
                tg.start_soon(self._safe_send, data, connection)

    @property
    def messages(self) -> AsyncIterable[R]:
        return self._rcv

    async def on_connect(self) -> None:
        pass

    async def on_disconnect(self) -> None:
        pass

    @abstractmethod
    async def handler(self, *args: P.args, **kwargs: P.kwargs) -> None:
        raise NotImplementedError
