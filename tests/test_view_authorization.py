from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient
from joserfc import jwk
from pydantic import BaseModel, ConfigDict, Field
from starlette.status import (
    HTTP_200_OK,
    HTTP_304_NOT_MODIFIED,
    HTTP_403_FORBIDDEN,
)

from fastapi_views import ViewRouter
from fastapi_views.auth.jwt import JWTAuth, JWTConfig
from fastapi_views.handlers import add_error_handlers
from fastapi_views.permissions import AllowAny, IsOwner, set_app_auth
from fastapi_views.views.api import AsyncRetrieveAPIView
from fastapi_views.views.mixins import ConditionalMixin

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from fastapi_views.views.api import View


class DocSchema(BaseModel):
    id: UUID
    owner_id: UUID


class User(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: UUID = Field(alias="sub")
    permissions: list[str] = Field(default_factory=list)


def make_user(token: dict[str, Any]) -> User:
    return User(sub=UUID(token["sub"]))


def make_jwt_auth() -> JWTAuth:
    return JWTAuth(
        JWTConfig(key=jwk.OctKey.generate_key(256), algorithms=["HS256"]),
        custom_class=make_user,
    )


@pytest.fixture(autouse=True)
def _reset_app_auth() -> Generator[None, None, None]:
    set_app_auth(None)
    yield
    set_app_auth(None)


@pytest.fixture
def auth() -> JWTAuth:
    jwt_auth = make_jwt_auth()
    set_app_auth(jwt_auth)
    return jwt_auth


def bearer(auth: JWTAuth, user_id: UUID | None = None) -> dict[str, str]:
    token = auth.create_access_token({"sub": str(user_id or uuid4())}).access_token
    return {"Authorization": f"Bearer {token}"}


@asynccontextmanager
async def view_client(
    view: type[View],
    prefix: str = "/test",
) -> AsyncGenerator[AsyncClient, None]:
    app = FastAPI()
    add_error_handlers(app)
    router = ViewRouter()
    router.register_view(view, prefix=prefix)
    app.include_router(router)
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


class MissingDocView(AsyncRetrieveAPIView):
    response_schema = DocSchema
    detail_route = "/{id}"
    raise_on_none = False
    permission_classes: ClassVar = [IsOwner("user_id", "owner_id")]

    async def retrieve(self, id: str) -> Any:
        return None


class OpenMissingDocView(AsyncRetrieveAPIView):
    response_schema = DocSchema
    detail_route = "/{id}"
    raise_on_none = False

    async def retrieve(self, id: str) -> Any:
        return None


@pytest.mark.anyio
async def test_missing_object_without_permissions_returns_empty_ok():
    async with view_client(OpenMissingDocView) as client:
        response = await client.get(f"/test/{uuid4()}")
    assert response.status_code == HTTP_200_OK
    assert response.content == b""


@pytest.mark.anyio
async def test_missing_object_with_object_permission_returns_empty_ok(auth):
    async with view_client(MissingDocView) as client:
        response = await client.get(f"/test/{uuid4()}", headers=bearer(auth))
    assert response.status_code == HTTP_200_OK
    assert response.content == b""


class RawResponseDocView(AsyncRetrieveAPIView):
    response_schema = DocSchema
    detail_route = "/{id}"
    permission_classes: ClassVar = [IsOwner("user_id", "owner_id")]

    async def retrieve(self, id: str) -> Any:
        return Response(content=b"raw", media_type="text/plain")


class ConditionalDocView(ConditionalMixin, AsyncRetrieveAPIView):
    response_schema = DocSchema
    detail_route = "/{id}"
    conditional_requests = True
    permission_classes: ClassVar = [IsOwner("user_id", "owner_id")]

    async def retrieve(self, id: str) -> Any:
        return self.check_etag("v1") or DocSchema(
            id=UUID(id), owner_id=self.principal.user_id
        )


@pytest.mark.anyio
async def test_response_from_retrieve_passes_through(auth):
    async with view_client(RawResponseDocView) as client:
        response = await client.get(f"/test/{uuid4()}", headers=bearer(auth))
    assert response.status_code == HTTP_200_OK
    assert response.content == b"raw"


@pytest.mark.anyio
async def test_not_modified_from_retrieve_passes_through(auth):
    headers = {**bearer(auth), "if-none-match": '"v1"'}
    async with view_client(ConditionalDocView) as client:
        response = await client.get(f"/test/{uuid4()}", headers=headers)
    assert response.status_code == HTTP_304_NOT_MODIFIED


@pytest.mark.anyio
async def test_conditional_body_is_still_authorized(auth):
    async with view_client(ConditionalDocView) as client:
        response = await client.get(f"/test/{uuid4()}", headers=bearer(auth))
    assert response.status_code == HTTP_200_OK


class NotOwnerDocView(AsyncRetrieveAPIView):
    response_schema = DocSchema
    detail_route = "/{id}"
    permission_classes: ClassVar = [IsOwner("user_id", "owner_id")]

    async def retrieve(self, id: str) -> Any:
        return DocSchema(id=UUID(id), owner_id=UUID(int=999))


@pytest.mark.anyio
async def test_non_owner_object_is_forbidden(auth):
    async with view_client(NotOwnerDocView) as client:
        response = await client.get(f"/test/{uuid4()}", headers=bearer(auth))
    assert response.status_code == HTTP_403_FORBIDDEN


class CountingPermission(AllowAny):
    """``AllowAny`` recording how many times it has been instantiated."""

    instances = 0

    def __init__(self) -> None:
        type(self).instances += 1


class CountingDocView(AsyncRetrieveAPIView):
    response_schema = DocSchema
    detail_route = "/{id}"
    permission_classes: ClassVar = [CountingPermission]

    async def retrieve(self, id: str) -> Any:
        return DocSchema(id=UUID(id), owner_id=uuid4())


@pytest.mark.anyio
async def test_permissions_are_resolved_once_per_action():
    async with view_client(CountingDocView) as client:
        CountingPermission.instances = 0
        for _ in range(3):
            response = await client.get(f"/test/{uuid4()}")
            assert response.status_code == HTTP_200_OK
    assert CountingPermission.instances == 1
