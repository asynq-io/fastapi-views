from abc import ABC, abstractmethod
from collections.abc import Callable, MutableMapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

State = MutableMapping[str, Any]

Dependency = (
    AbstractAsyncContextManager[Any] | Callable[[], AbstractAsyncContextManager[Any]]
)


class LifespanMiddleware(ABC):
    def __init__(
        self,
        app: ASGIApp,
    ) -> None:
        self.app = app

    @abstractmethod
    async def setup(self, state: State) -> None:
        raise NotImplementedError

    @abstractmethod
    async def teardown(self) -> None:
        raise NotImplementedError

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "lifespan":
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})

        async def receive_hook() -> Message:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await self.setup(state)
            return message

        async def send_hook(message: Message) -> None:
            if message["type"].startswith("lifespan.shutdown."):
                await self.teardown()
            await send(message)

        await self.app(scope, receive_hook, send_hook)


class StatefulLifespanMiddleware(LifespanMiddleware):
    """Sets up app-scoped dependencies in the ASGI lifespan state.

    Each dependency is an async context manager (or a factory returning one),
    entered on startup and exited on shutdown. The entered value is stored in
    the lifespan state under its keyword name and is available in request
    handlers via ``request.state`` or ``FromScope``.
    """

    def __init__(self, app: ASGIApp, **dependencies: Dependency) -> None:
        super().__init__(app)
        self.dependencies = dependencies
        self._exit_stack = AsyncExitStack()

    async def setup(self, state: State) -> None:
        for key, dependency in self.dependencies.items():
            if not isinstance(dependency, AbstractAsyncContextManager):
                dependency = dependency()
            state[key] = await self._exit_stack.enter_async_context(dependency)

    async def teardown(self) -> None:
        await self._exit_stack.aclose()
