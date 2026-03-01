from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fastapi_views.models import BaseSchema
from fastapi_views.views import get
from fastapi_views.views.api import (
    APIView,
    AsyncCreateAPIView,
    AsyncDestroyAPIView,
    AsyncListAPIView,
    AsyncRetrieveAPIView,
)

from .utils import view_as_fixture

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(autouse=True, scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app():
    return FastAPI()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as test_client,
    ):
        yield test_client


class DummySchema(BaseSchema):
    x: str


class ExtendDummySchema(DummySchema):
    y: str | None = None


@pytest.fixture(scope="session")
def dummy_data():
    return {"x": "test"}


@view_as_fixture("list_view")
class TestListView(AsyncListAPIView):
    response_schema = DummySchema

    async def list(self) -> Any:
        return [{"x": "test"}]


@view_as_fixture("retrieve_view")
class TestRetrieveView(AsyncRetrieveAPIView):
    detail_route = ""
    response_schema = DummySchema

    async def retrieve(self) -> Any:
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
