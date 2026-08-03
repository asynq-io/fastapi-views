from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from fastapi_views.lifespan import FromScope
from fastapi_views.middlewares.lifespan import LifespanMiddleware


@asynccontextmanager
async def fake_db(events):
    events.append("setup")
    yield {"name": "db"}
    events.append("teardown")


@pytest.mark.anyio
async def test_lifespan_middleware_provides_app_scoped_dependency(app):
    events = []

    app.add_middleware(LifespanMiddleware, db=lambda: fake_db(events))

    @app.get("/db")
    async def get_db(db: Annotated[dict, FromScope("db")]) -> dict:
        return db

    async with LifespanManager(app) as manager:
        assert events == ["setup"]
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/db")

    assert response.json() == {"name": "db"}
    assert events == ["setup", "teardown"]


@pytest.mark.anyio
async def test_lifespan_middleware_accepts_context_manager_instance(app):
    events = []

    app.add_middleware(LifespanMiddleware, db=fake_db(events))

    @app.get("/db")
    async def get_db(request: Request) -> dict:
        return request.state.db

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/db")

    assert response.json() == {"name": "db"}
    assert events == ["setup", "teardown"]


@pytest.mark.anyio
async def test_lifespan_middleware_tears_down_multiple_dependencies_in_reverse_order(
    app,
):
    events = []

    @asynccontextmanager
    async def dependency(name):
        events.append(f"setup {name}")
        yield name
        events.append(f"teardown {name}")

    app.add_middleware(
        LifespanMiddleware,
        first=lambda: dependency("first"),
        second=lambda: dependency("second"),
    )

    async with LifespanManager(app):
        pass

    assert events == [
        "setup first",
        "setup second",
        "teardown second",
        "teardown first",
    ]
