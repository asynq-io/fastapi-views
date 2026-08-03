from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from starlette.requests import HTTPConnection

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def FromScope(key: str) -> Any:  # noqa: N802
    """Dependency returning the value stored in the lifespan state under ``key``."""

    async def getter(connection: HTTPConnection) -> Any:
        return getattr(connection.state, key)

    return Depends(getter)


def merge_lifespans(
    *lifespans: Lifespan,
) -> Lifespan:

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        exit_stack = AsyncExitStack()
        async with exit_stack:
            for lifespan in lifespans:
                await exit_stack.enter_async_context(lifespan(app))
            yield

    return lifespan
