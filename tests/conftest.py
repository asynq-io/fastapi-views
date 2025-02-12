import asyncio
from collections.abc import AsyncGenerator
from typing import Any, Optional

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fastapi_views import ViewRouter
from fastapi_views.models import BaseSchema
from fastapi_views.views import get
from fastapi_views.views.api import (
    APIView,
    AsyncCreateAPIView,
    AsyncDestroyAPIView,
    AsyncListAPIView,
    AsyncRetrieveAPIView,
)


@pytest_asyncio.fixture(scope="session")
def event_loop():
    return asyncio.get_event_loop()


@pytest.fixture
def app():
    return FastAPI()


@pytest_asyncio.fixture(scope="function")
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as test_client,
    ):
        yield test_client


class DummySchema(BaseSchema):
    x: str


class ExtendDummySchema(DummySchema):
    y: Optional[str] = None


@pytest.fixture(scope="session")
def dummy_data():
    return {"x": "test"}


def view_as_fixture(name: str, prefix: str = "/test"):
    def wrapper(cls):
        @pytest.fixture(name=name)
        def _view_fixture(app: FastAPI) -> None:
            router = ViewRouter()
            router.register_view(cls, prefix=prefix)
            app.include_router(router)

        return _view_fixture

    return wrapper


@view_as_fixture("list_view")
class TestListView(AsyncListAPIView):
    response_schema = DummySchema

    async def list(self) -> Any:
        return [{"x": "test"}]


@view_as_fixture("retrieve_view")
class TestRetrieveView(AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = DummySchema

    async def retrieve(self) -> Optional[Any]:
        return ExtendDummySchema(x="test")


@view_as_fixture("destroy_view")
class TestDestroyView(AsyncDestroyAPIView):
    detail_route = ""

    async def destroy(self) -> None:
        pass


@view_as_fixture("create_view")
class TestCreateView(AsyncCreateAPIView):
    response_schema = DummySchema

    async def create(self) -> Any:
        return ExtendDummySchema(x="test")


@view_as_fixture("custom_retrieve_view")
class TestCustomView(APIView):
    @get(path="/custom")
    async def custom_get(self) -> DummySchema:
        return ExtendDummySchema(x="test")
