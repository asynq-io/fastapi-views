from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fastapi_views import ViewRouter
from fastapi_views.handlers import add_error_handlers
from fastapi_views.views.api import View


def view_as_fixture(name: str, prefix: str = "/test"):
    def wrapper(cls):
        @pytest.fixture(name=name)
        def _view_fixture(app: FastAPI) -> None:
            router = ViewRouter()
            router.register_view(cls, prefix=prefix)
            app.include_router(router)

        return _view_fixture

    return wrapper


@asynccontextmanager
async def view_client(
    view: type[View], prefix: str = "/test", *, error_handlers: bool = False
) -> AsyncGenerator[AsyncClient, None]:
    app = FastAPI()
    if error_handlers:
        add_error_handlers(app)
    router = ViewRouter()
    router.register_view(view, prefix=prefix)
    app.include_router(router)
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c
