from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from joserfc import jwk
from pydantic import BaseModel, ConfigDict, Field
from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)

from fastapi_views import ViewRouter, configure_app
from fastapi_views.auth import AutoScopesAuthView
from fastapi_views.auth.jwt import JWTAuth, JWTConfig
from fastapi_views.permissions import HasPermissions, IsAuthenticated, set_app_auth
from fastapi_views.views.api import AsyncListAPIView

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


class User(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: UUID = Field(alias="sub")
    permissions: list[str] = Field(default_factory=list)


def make_user(token: dict[str, Any]) -> User:
    return User(sub=UUID(token["sub"]), permissions=token.get("scope", "").split())


def make_jwt_auth() -> JWTAuth:
    """A freshly-keyed auth, so a token minted by another one never verifies."""
    return JWTAuth(
        JWTConfig(key=jwk.OctKey.generate_key(256), algorithms=["HS256"]),
        custom_class=make_user,
    )


VIEW_AUTH = make_jwt_auth()


def bearer(auth: JWTAuth, scope: str = "") -> dict[str, str]:
    token = auth.create_access_token({"sub": str(uuid4()), "scope": scope}).access_token
    return {"Authorization": f"Bearer {token}"}


class DocSchema(BaseModel):
    id: UUID


class DocListView(AsyncListAPIView):
    api_component_name = "Doc"
    response_schema = DocSchema
    permission_classes: ClassVar = [IsAuthenticated & HasPermissions("read:docs")]

    async def list(self) -> list[DocSchema]:
        return []


class OwnAuthDocListView(DocListView):
    api_component_name = "OwnAuthDoc"
    auth = VIEW_AUTH


class ReportListView(AutoScopesAuthView, AsyncListAPIView):
    api_component_name = "Report"
    resource = "reports"
    response_schema = DocSchema

    async def list(self) -> list[DocSchema]:
        return []


class OwnAuthReportListView(ReportListView):
    api_component_name = "OwnAuthReport"
    auth = VIEW_AUTH


@pytest.fixture(autouse=True)
def _reset_app_auth() -> Generator[None, None, None]:
    set_app_auth(None)
    yield
    set_app_auth(None)


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


def register(app: FastAPI, view: type, prefix: str) -> None:
    router = ViewRouter()
    router.register_view(view, prefix=prefix)
    app.include_router(router)


@pytest.mark.anyio
async def test_auto_scopes_view_enforces_its_own_auth():
    app_auth = make_jwt_auth()
    app = FastAPI()
    configure_app(app, auth=app_auth, limits=None)
    register(app, OwnAuthReportListView, "/reports")

    async with app_client(app) as client:
        own = await client.get("/reports", headers=bearer(VIEW_AUTH, "read:reports"))
        foreign = await client.get("/reports", headers=bearer(app_auth, "read:reports"))

    assert own.status_code == HTTP_200_OK
    assert foreign.status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_permission_view_enforces_its_own_auth():
    app_auth = make_jwt_auth()
    app = FastAPI()
    configure_app(app, auth=app_auth, limits=None)
    register(app, OwnAuthDocListView, "/documents")

    async with app_client(app) as client:
        own = await client.get("/documents", headers=bearer(VIEW_AUTH, "read:docs"))
        foreign = await client.get("/documents", headers=bearer(app_auth, "read:docs"))

    assert own.status_code == HTTP_200_OK
    assert foreign.status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_views_registered_before_configure_app_are_enforced():
    auth = make_jwt_auth()
    app = FastAPI()
    register(app, DocListView, "/documents")
    configure_app(app, auth=auth, limits=None)

    async with app_client(app) as client:
        anonymous = await client.get("/documents")
        permitted = await client.get("/documents", headers=bearer(auth, "read:docs"))
        forbidden = await client.get("/documents", headers=bearer(auth, "read:other"))

    assert anonymous.status_code == HTTP_401_UNAUTHORIZED
    assert permitted.status_code == HTTP_200_OK
    assert forbidden.status_code == HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_auto_scopes_view_validates_scopes_against_the_app_auth():
    auth = make_jwt_auth()
    app = FastAPI()
    register(app, ReportListView, "/reports")
    configure_app(app, auth=auth, limits=None)

    async with app_client(app) as client:
        anonymous = await client.get("/reports")
        permitted = await client.get("/reports", headers=bearer(auth, "read:reports"))
        insufficient = await client.get("/reports", headers=bearer(auth, "read:other"))

    assert anonymous.status_code == HTTP_401_UNAUTHORIZED
    assert permitted.status_code == HTTP_200_OK
    assert insufficient.status_code == HTTP_403_FORBIDDEN


def test_openapi_advertises_scopes_when_auth_is_configured_last():
    auth = make_jwt_auth()
    app = FastAPI()
    register(app, DocListView, "/documents")
    configure_app(app, auth=auth, limits=None)

    spec = app.openapi()

    assert spec["components"]["securitySchemes"]
    security = spec["paths"]["/documents"]["get"]["security"]
    scopes = [
        scope for item in security for values in item.values() for scope in values
    ]
    assert scopes == ["read:docs"]


@pytest.mark.anyio
async def test_view_without_any_configured_auth_fails_closed():
    app = FastAPI()
    register(app, DocListView, "/documents")

    with pytest.raises(RuntimeError, match="No app auth configured"):
        async with app_client(app) as client:
            await client.get("/documents", headers={"Authorization": "Bearer whatever"})


@pytest.mark.anyio
async def test_two_apps_enforce_their_own_auth():
    first_auth, second_auth = make_jwt_auth(), make_jwt_auth()
    first, second = FastAPI(), FastAPI()
    for app, auth in ((first, first_auth), (second, second_auth)):
        register(app, DocListView, "/documents")
        configure_app(app, auth=auth, limits=None)

    async with app_client(first) as client:
        own = await client.get("/documents", headers=bearer(first_auth, "read:docs"))
        foreign = await client.get(
            "/documents", headers=bearer(second_auth, "read:docs")
        )
    assert own.status_code == HTTP_200_OK
    assert foreign.status_code == HTTP_401_UNAUTHORIZED

    async with app_client(second) as client:
        own = await client.get("/documents", headers=bearer(second_auth, "read:docs"))
        foreign = await client.get(
            "/documents", headers=bearer(first_auth, "read:docs")
        )
    assert own.status_code == HTTP_200_OK
    assert foreign.status_code == HTTP_401_UNAUTHORIZED
