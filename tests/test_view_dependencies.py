from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from joserfc import jwk
from pydantic import BaseModel
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)

from fastapi_views import ViewRouter
from fastapi_views.auth.jwt import JWTAuth, JWTConfig
from fastapi_views.views.bulk import AsyncBulkAPIViewSet
from fastapi_views.views.generics import (
    AsyncGenericCreateAPIView,
    AsyncGenericListAPIView,
)

from .utils import view_client

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


class Item(BaseModel):
    id: UUID
    name: str


class CreateItem(BaseModel):
    name: str


class UpdateItem(BaseModel):
    id: UUID
    name: str


class ItemRepository:
    async def create(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": uuid4(), **kwargs}

    async def list(self) -> list[dict[str, Any]]:
        return []


class BulkItemRepository:
    async def create_many(
        self, items: Sequence[Mapping[str, Any]], **_options: Any
    ) -> list[dict[str, Any]]:
        return [{"id": uuid4(), **item} for item in items]

    async def update_many(
        self, values: Mapping[str, Any], **_kwargs: Any
    ) -> list[dict[str, Any]]:
        return [{"id": uuid4(), **values}]

    async def bulk_update(
        self, items: Sequence[Mapping[str, Any]], **_options: Any
    ) -> None:
        pass

    async def delete_many(self, **_kwargs: Any) -> None:
        pass


def recorder(calls: list[str], name: str) -> Callable[[], None]:
    def dependency() -> None:
        calls.append(name)

    return dependency


def make_auth() -> JWTAuth:
    return JWTAuth(
        JWTConfig(key=jwk.OctKey.generate_key(256), algorithms=["HS256"]), None
    )


@pytest.mark.anyio
async def test_action_dependencies_run_only_for_their_action():
    calls: list[str] = []

    class ItemView(AsyncGenericListAPIView, AsyncGenericCreateAPIView):
        response_schema = Item
        create_schema = CreateItem
        filter = None
        repository = ItemRepository()
        action_dependencies: ClassVar = {
            "list": [Depends(recorder(calls, "list"))],
            "create": [Depends(recorder(calls, "create"))],
        }

    async with view_client(ItemView) as client:
        assert (await client.get("/test")).status_code == HTTP_200_OK
        assert calls == ["list"]
        calls.clear()
        response = await client.post("/test", json={"name": "a"})
        assert response.status_code == HTTP_201_CREATED
        assert calls == ["create"]


@pytest.mark.anyio
async def test_action_dependencies_enforce_scopes():
    auth = make_auth()

    class ItemView(AsyncGenericListAPIView, AsyncGenericCreateAPIView):
        response_schema = Item
        create_schema = CreateItem
        filter = None
        repository = ItemRepository()
        action_dependencies: ClassVar = {
            "list": [auth.requires("items:read")],
            "create": [auth.requires("items:edit")],
        }

    async with view_client(ItemView, error_handlers=True) as client:
        assert (await client.get("/test")).status_code == HTTP_401_UNAUTHORIZED

        bearer = auth.create_access_token({"sub": "user-1", "scope": "items:read"})
        headers = {"Authorization": f"Bearer {bearer.access_token}"}
        assert (await client.get("/test", headers=headers)).status_code == HTTP_200_OK
        response = await client.post("/test", json={"name": "a"}, headers=headers)
        assert response.status_code == HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_bulk_action_dependencies_run_only_for_their_action():
    calls: list[str] = []

    class ItemBulkViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = CreateItem
        filter = None
        repository = BulkItemRepository()
        action_dependencies: ClassVar = {
            "bulk_create": [Depends(recorder(calls, "bulk_create"))],
        }

    async with view_client(ItemBulkViewSet) as client:
        response = await client.post("/test/bulk", json=[{"name": "a"}])
        assert response.status_code == HTTP_201_CREATED
        assert calls == ["bulk_create"]
        calls.clear()
        response = await client.delete("/test/bulk")
        assert response.status_code == HTTP_204_NO_CONTENT
        assert calls == []


@pytest.mark.anyio
async def test_register_view_merges_router_dependencies():
    calls: list[str] = []

    class ItemView(AsyncGenericListAPIView):
        response_schema = Item
        filter = None
        repository = ItemRepository()
        action_dependencies: ClassVar = {
            "list": [Depends(recorder(calls, "list"))],
        }

    app = FastAPI()
    router = ViewRouter()
    router.register_view(
        ItemView, prefix="/test", dependencies=[Depends(recorder(calls, "router"))]
    )
    app.include_router(router)
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert (await client.get("/test")).status_code == HTTP_200_OK
        assert calls == ["router", "list"]
