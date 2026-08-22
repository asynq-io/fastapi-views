from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI, Security
from httpx import ASGITransport, AsyncClient
from joserfc import jwk
from pydantic import BaseModel, Field
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)

from fastapi_views import ViewRouter
from fastapi_views.auth import AutoScopesAuthView
from fastapi_views.auth.api_key import ConstAPIKeyAuth
from fastapi_views.auth.jwt import JWTAuth, JWTConfig
from fastapi_views.filters.models import BaseFilter
from fastapi_views.handlers import add_error_handlers
from fastapi_views.models import AnyServerSentEvent
from fastapi_views.permissions import (
    AllowAny,
    BasePermission,
    CurrentUser,
    HasPermissions,
    IsAuthenticated,
    IsOwner,
    set_app_auth,
)
from fastapi_views.permissions.views import AsyncObjectPermissionsMixin
from fastapi_views.views import ServerSentEventsAPIView, action
from fastapi_views.views.api import APIView, AsyncListAPIView
from fastapi_views.views.bulk import AsyncBulkAPIViewSet
from fastapi_views.views.jsonpatch import AsyncGenericJsonPatchAPIView

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Mapping, Sequence

    from fastapi_views.views.api import View


OWNER_ID = UUID(int=1)
OTHER_ID = UUID(int=2)


class User(BaseModel):
    user_id: UUID
    permissions: list[str] = Field(default_factory=list)


def make_user(token: dict[str, Any]) -> User:
    return User(
        user_id=UUID(token["sub"]),
        permissions=token.get("scope", "").split(),
    )


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


def bearer(
    auth: JWTAuth,
    user_id: UUID | None = None,
    scope: str = "",
) -> dict[str, str]:
    payload = {"sub": str(user_id or uuid4()), "scope": scope}
    token = auth.create_access_token(payload).access_token
    return {"Authorization": f"Bearer {token}"}


def build_app(view: type[View], prefix: str) -> FastAPI:
    app = FastAPI()
    add_error_handlers(app)
    router = ViewRouter()
    router.register_view(view, prefix=prefix)
    app.include_router(router)
    return app


@asynccontextmanager
async def view_client(
    view: type[View],
    prefix: str = "/test",
) -> AsyncGenerator[AsyncClient, None]:
    app = build_app(view, prefix)
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


class Item(BaseModel):
    id: UUID
    name: str


class CreateItem(BaseModel):
    name: str


class UpdateItem(BaseModel):
    id: UUID
    name: str


class ItemValues(BaseModel):
    name: str


class NameFilter(BaseFilter):
    name: str | None = None


class RecordingBulkRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_many(
        self, items: Sequence[Mapping[str, Any]], /, **kwargs: Any
    ) -> Sequence[Item]:
        self.calls.append("create_many")
        return [Item(id=uuid4(), name=item["name"]) for item in items]

    async def update_many(
        self, values: Mapping[str, Any], /, *args: Any, **kwargs: Any
    ) -> Sequence[Item]:
        self.calls.append("update_many")
        return [Item(id=uuid4(), name=values["name"])]

    async def bulk_update(
        self, items: Sequence[Mapping[str, Any]], /, **kwargs: Any
    ) -> None:
        self.calls.append("bulk_update")

    async def delete_many(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append("delete_many")


def protected_bulk_viewset(repo: RecordingBulkRepository) -> type[APIView]:
    class ProtectedBulkViewSet(AsyncBulkAPIViewSet):
        api_component_name = "BulkItem"
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        permission_classes: ClassVar = [IsAuthenticated]
        repository = repo

    return ProtectedBulkViewSet


BULK_REQUESTS = [
    ("POST", [{"name": "a"}], None),
    ("PUT", [{"id": str(uuid4()), "name": "a"}], None),
    ("PATCH", {"name": "a"}, {"name": "old"}),
    ("DELETE", None, {"name": "old"}),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("method", "json", "params"), BULK_REQUESTS)
async def test_anonymous_bulk_action_is_unauthorized(auth, method, json, params):
    repository = RecordingBulkRepository()
    async with view_client(protected_bulk_viewset(repository), "/items") as client:
        response = await client.request(method, "/items/bulk", json=json, params=params)

    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert repository.calls == []


@pytest.mark.anyio
async def test_authenticated_bulk_create_is_allowed(auth):
    repository = RecordingBulkRepository()
    async with view_client(protected_bulk_viewset(repository), "/items") as client:
        response = await client.post(
            "/items/bulk", json=[{"name": "a"}], headers=bearer(auth)
        )

    assert response.status_code == HTTP_201_CREATED
    assert repository.calls == ["create_many"]


class ProtectedEventsView(ServerSentEventsAPIView):
    api_component_name = "ProtectedEvent"
    response_schema = AnyServerSentEvent
    permission_classes: ClassVar = [IsAuthenticated]
    streamed: ClassVar[bool] = False

    async def events(self):
        type(self).streamed = True
        yield AnyServerSentEvent(id="1", event="tick", data={"x": 1})


@pytest.mark.anyio
async def test_anonymous_sse_stream_is_unauthorized(auth):
    ProtectedEventsView.streamed = False
    async with view_client(ProtectedEventsView, "/events") as client:
        response = await client.get("/events")

    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert ProtectedEventsView.streamed is False


@pytest.mark.anyio
async def test_authenticated_sse_stream_is_allowed(auth):
    ProtectedEventsView.streamed = False
    async with view_client(ProtectedEventsView, "/events") as client:
        response = await client.get("/events", headers=bearer(auth))

    assert response.status_code == HTTP_200_OK
    assert "event: tick" in response.text


class DocId(BaseModel):
    id: int


class Doc(DocId):
    name: str
    owner_id: UUID


class PatchDoc(BaseModel):
    name: str


class DocRepository:
    def __init__(self, doc: Doc) -> None:
        self.doc = doc
        self.updates: list[dict[str, Any]] = []
        self.get_calls = 0

    async def get(self, **kwargs: Any) -> Doc | None:
        self.get_calls += 1
        return self.doc if kwargs["id"] == self.doc.id else None

    async def update_one(self, values: dict[str, Any], **kwargs: Any) -> Doc | None:
        self.updates.append(values)
        return self.doc.model_copy(update=values)


def protected_jsonpatch_view(repo: DocRepository) -> type[APIView]:
    class ProtectedJsonPatchView(
        AsyncObjectPermissionsMixin[Doc],
        AsyncGenericJsonPatchAPIView[DocId, Doc],
    ):
        api_component_name = "ProtectedDoc"
        primary_key = DocId
        response_schema = Doc
        partial_update_schema = PatchDoc
        permission_classes: ClassVar = [IsAuthenticated & IsOwner()]
        repository = repo  # type: ignore[assignment]

    return ProtectedJsonPatchView


PATCH_OPERATIONS = [{"op": "replace", "path": "/name", "value": "renamed"}]


@pytest.mark.anyio
async def test_json_patch_by_non_owner_is_forbidden(auth):
    repository = DocRepository(Doc(id=1, name="first", owner_id=OWNER_ID))
    async with view_client(
        protected_jsonpatch_view(repository), "/documents"
    ) as client:
        response = await client.patch(
            "/documents/1", json=PATCH_OPERATIONS, headers=bearer(auth, OTHER_ID)
        )

    assert response.status_code == HTTP_403_FORBIDDEN
    assert repository.updates == []


@pytest.mark.anyio
async def test_json_patch_by_owner_is_allowed(auth):
    repository = DocRepository(Doc(id=1, name="first", owner_id=OWNER_ID))
    async with view_client(
        protected_jsonpatch_view(repository), "/documents"
    ) as client:
        response = await client.patch(
            "/documents/1", json=PATCH_OPERATIONS, headers=bearer(auth, OWNER_ID)
        )

    assert response.status_code == HTTP_200_OK
    assert repository.updates == [{"name": "renamed"}]


@pytest.mark.anyio
async def test_anonymous_json_patch_is_unauthorized(auth):
    repository = DocRepository(Doc(id=1, name="first", owner_id=OWNER_ID))
    async with view_client(
        protected_jsonpatch_view(repository), "/documents"
    ) as client:
        response = await client.patch("/documents/1", json=PATCH_OPERATIONS)

    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert repository.updates == []


class PingSchema(BaseModel):
    ping: str


class CustomActionView(APIView):
    api_component_name = "CustomAction"
    permission_classes: ClassVar = [IsAuthenticated]

    @action(methods=["GET"])
    async def ping(self) -> PingSchema:
        return PingSchema(ping="pong")


@pytest.mark.anyio
async def test_custom_action_accepts_valid_credentials(auth):
    async with view_client(CustomActionView, "/custom") as client:
        response = await client.get("/custom/ping", headers=bearer(auth))

    assert response.status_code == HTTP_200_OK
    assert response.json() == {"ping": "pong"}


@pytest.mark.anyio
async def test_anonymous_custom_action_is_unauthorized(auth):
    async with view_client(CustomActionView, "/custom") as client:
        response = await client.get("/custom/ping")

    assert response.status_code == HTTP_401_UNAUTHORIZED


def test_custom_action_advertises_security_scheme(auth):
    app = build_app(CustomActionView, "/custom")

    spec = app.openapi()

    assert spec["components"]["securitySchemes"]
    assert spec["paths"]["/custom/ping"]["get"]["security"]


class ScopedReportView(AutoScopesAuthView, AsyncListAPIView):
    api_component_name = "ScopedReport"
    resource = "reports"
    response_schema = PingSchema
    action_scopes: ClassVar[Mapping[str, str]] = {
        **AutoScopesAuthView.action_scopes,
        "publish": "edit",
    }

    async def list(self) -> list[PingSchema]:
        return []

    @action(methods=["POST"])
    async def publish(self) -> PingSchema:
        return PingSchema(ping="published")


class UnscopedReportView(ScopedReportView):
    api_component_name = "UnscopedReport"
    action_scopes: ClassVar[Mapping[str, str]] = AutoScopesAuthView.action_scopes


@pytest.mark.anyio
async def test_auto_scopes_view_enforces_scope_on_custom_action(auth):
    async with view_client(ScopedReportView, "/reports") as client:
        permitted = await client.post(
            "/reports/publish", headers=bearer(auth, scope="edit:reports")
        )
        insufficient = await client.post(
            "/reports/publish", headers=bearer(auth, scope="read:reports")
        )
        anonymous = await client.post("/reports/publish")

    assert permitted.status_code == HTTP_200_OK
    assert insufficient.status_code == HTTP_403_FORBIDDEN
    assert anonymous.status_code == HTTP_401_UNAUTHORIZED


def test_auto_scopes_view_rejects_custom_action_without_scope(auth):
    with pytest.raises(LookupError, match="publish"):
        build_app(UnscopedReportView, "/reports")


class DynamicPermissionsView(AsyncListAPIView):
    api_component_name = "DynamicDoc"
    response_schema = PingSchema

    def get_permissions(self) -> list[BasePermission]:
        return [IsAuthenticated()]

    async def list(self) -> list[PingSchema]:
        return []


class DynamicAllowAnyView(AsyncListAPIView):
    api_component_name = "DynamicOpenDoc"
    response_schema = PingSchema

    def get_permissions(self) -> list[BasePermission]:
        return [AllowAny()]

    async def list(self) -> list[PingSchema]:
        return []


@pytest.mark.anyio
async def test_dynamic_permissions_accept_valid_credentials(auth):
    async with view_client(DynamicPermissionsView, "/dynamic") as client:
        response = await client.get("/dynamic", headers=bearer(auth))

    assert response.status_code == HTTP_200_OK
    assert response.json() == []


@pytest.mark.anyio
async def test_anonymous_request_to_dynamic_permissions_is_unauthorized(auth):
    async with view_client(DynamicPermissionsView, "/dynamic") as client:
        response = await client.get("/dynamic")

    assert response.status_code == HTTP_401_UNAUTHORIZED


def test_dynamic_permissions_are_documented_as_protected(auth):
    app = build_app(DynamicPermissionsView, "/dynamic")

    spec = app.openapi()

    assert spec["paths"]["/dynamic"]["get"]["security"]


@pytest.mark.anyio
async def test_dynamic_permissions_without_any_auth_fail_closed():
    async with view_client(DynamicAllowAnyView, "/dynamic") as client:
        with pytest.raises(RuntimeError, match="No app auth configured"):
            await client.get("/dynamic")


class ChallengeDocView(AsyncListAPIView):
    api_component_name = "ChallengeDoc"
    response_schema = PingSchema
    permission_classes: ClassVar = [IsAuthenticated & HasPermissions("read:docs")]

    async def list(self) -> list[PingSchema]:
        return []


def build_injected_app(auth: JWTAuth) -> FastAPI:
    app = FastAPI()
    add_error_handlers(app)

    @app.get("/injected", dependencies=[Security(auth.resolve_dependency)])
    async def injected(user: CurrentUser) -> dict[str, str]:
        return {"user": " ".join(user.permissions)}

    return app


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.mark.anyio
async def test_anonymous_request_carries_authenticate_challenge(auth):
    async with view_client(ChallengeDocView, "/documents") as client:
        response = await client.get("/documents")

    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == auth.challenge


@pytest.mark.anyio
async def test_invalid_token_reports_its_own_reason(auth):
    headers = {"Authorization": "Bearer not-a-token"}
    async with view_client(ChallengeDocView, "/documents") as client:
        response = await client.get("/documents", headers=headers)

    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == auth.challenge
    assert response.json()["detail"] == "Invalid token"


@pytest.mark.anyio
async def test_forbidden_response_carries_no_challenge(auth):
    async with view_client(ChallengeDocView, "/documents") as client:
        response = await client.get(
            "/documents", headers=bearer(auth, scope="read:other")
        )

    assert response.status_code == HTTP_403_FORBIDDEN
    assert "www-authenticate" not in response.headers


@pytest.mark.anyio
async def test_injected_principal_challenges_anonymous_callers(auth):
    async with app_client(build_injected_app(auth)) as client:
        response = await client.get("/injected")

    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == auth.challenge


@pytest.mark.anyio
async def test_injected_principal_reports_invalid_token_reason(auth):
    headers = {"Authorization": "Bearer not-a-token"}
    async with app_client(build_injected_app(auth)) as client:
        response = await client.get("/injected", headers=headers)

    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == auth.challenge
    assert response.json()["detail"] == "Invalid token"


@pytest.mark.anyio
async def test_api_key_scheme_advertises_its_own_challenge():
    api_key_auth = ConstAPIKeyAuth("secret")
    set_app_auth(api_key_auth)

    async with view_client(ChallengeDocView, "/documents") as client:
        response = await client.get("/documents")

    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == api_key_auth.challenge
