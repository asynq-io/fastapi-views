from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace, UnionType
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, get_args
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI, Security
from httpx import ASGITransport, AsyncClient
from joserfc import jwk
from pydantic import BaseModel, ConfigDict, Field
from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)

from fastapi_views import ViewRouter, configure_app
from fastapi_views.auth.jwt import JWTAuth, JWTConfig
from fastapi_views.auth.scopes import (
    HierarchicalScopeValidator,
    Scope,
    ScopeValidator,
    SimpleScopeValidator,
)
from fastapi_views.exceptions import Unauthorized
from fastapi_views.handlers import add_error_handlers
from fastapi_views.permissions import (
    AllowAny,
    AndPermission,
    Authenticated,
    BasePermission,
    CurrentUser,
    HasPermissions,
    HasScopes,
    IsAdmin,
    IsAdminOrOwner,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
    IsOwner,
    NotPermission,
    OrPermission,
    Principal,
    get_app_auth,
    permission_denied,
    set_app_auth,
)
from fastapi_views.views import AsyncListAPIView, AsyncRetrieveAPIView

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Sequence


def make_jwt_auth(custom_class: Any = None) -> JWTAuth:
    return JWTAuth(
        JWTConfig(key=jwk.OctKey.generate_key(256), algorithms=["HS256"]),
        custom_class=custom_class,
    )


def _token(auth: JWTAuth, **claims: Any) -> str:
    claims.setdefault("sub", str(uuid4()))
    return auth.create_access_token(claims).access_token


class User(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: UUID = Field(alias="sub")
    org_id: UUID | None = None
    permissions: list[str] = Field(default_factory=list)


def make_user(token: dict[str, Any]) -> User:
    """custom_class: build a typed User from decoded JWT claims."""
    return User(
        sub=UUID(token["sub"]),
        permissions=token.get("scope", "").split(),
    )


class StrictUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: UUID = Field(alias="sub")
    org_id: UUID


class Device(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_id: UUID = Field(alias="sub")


class Wrapper(BaseModel):
    label: str

    @classmethod
    def from_principal(cls, p: Any) -> Wrapper:
        if isinstance(p, User):
            return cls(label=f"user:{p.user_id}")
        return cls(label="anon")


class AttrUser(BaseModel):
    user_id: UUID

    @classmethod
    def from_principal(cls, p: Any) -> AttrUser:
        return cls(user_id=p.user_id)


class CountingUser:
    coercions: ClassVar[int] = 0

    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id

    @classmethod
    def from_principal(cls, p: Any) -> CountingUser:
        cls.coercions += 1
        return cls(UUID(p["sub"]))


def counting_sub_dependency(principal: Authenticated[CountingUser]) -> UUID:
    return principal.user_id


def user(
    permissions: list[str] | None = None,
    user_id: UUID | None = None,
) -> User:
    return User(sub=user_id or UUID(int=1), permissions=permissions or [])


def view(method: str = "GET") -> SimpleNamespace:
    return SimpleNamespace(request=SimpleNamespace(method=method))


@pytest.fixture(autouse=True)
def _reset_app_auth() -> Generator[None, None, None]:
    set_app_auth(None)
    yield
    set_app_auth(None)


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


def build_app(*views: type) -> FastAPI:
    app = FastAPI()
    add_error_handlers(app)
    router = ViewRouter()
    for view_cls in views:
        router.register_view(view_cls, prefix="/test")
    app.include_router(router)
    return app


class DocSchema(BaseModel):
    id: UUID
    owner_id: UUID


class TestComposition:
    def test_and_both_pass(self):
        perm = IsAuthenticated & HasPermissions("read:docs")
        assert perm.has_permission(user(permissions=["read:docs"]), view())

    def test_and_short_circuits_on_anonymous(self):
        perm = IsAuthenticated & HasPermissions("read:docs")
        assert not perm.has_permission(None, view())

    def test_and_missing_permission(self):
        perm = IsAuthenticated & HasPermissions("read:docs")
        assert not perm.has_permission(user(permissions=[]), view())

    def test_or_first_passes(self):
        perm = IsAuthenticated | HasPermissions("read:docs")
        assert perm.has_permission(user(), view())

    def test_or_second_passes(self):
        perm = IsAdmin("admin") | HasPermissions("read:docs")
        assert perm.has_permission(user(permissions=["read:docs"]), view())

    def test_or_neither_passes(self):
        perm = IsAdmin("admin") | HasPermissions("read:docs")
        assert not perm.has_permission(user(permissions=[]), view())

    def test_not(self):
        assert (~IsAuthenticated).has_permission(None, view())
        assert not (~IsAuthenticated).has_permission(user(), view())

    def test_class_and_instance_compose(self):
        perm = IsAuthenticated & IsOwner("user_id", "owner_id")
        own = user(user_id=UUID(int=1))
        obj = SimpleNamespace(owner_id=UUID(int=1))
        assert perm.has_object_permission(own, view(), obj)

    def test_and_required_scopes_aggregate(self):
        perm = HasPermissions("read:docs") & HasPermissions("write:docs")
        assert sorted(perm.required_scopes) == ["read:docs", "write:docs"]

    def test_or_required_scopes_empty(self):
        perm = IsAdmin("admin") | HasPermissions("read:docs")
        assert perm.required_scopes == []

    def test_resolve_normalizes_class_and_instance(self):
        assert isinstance(BasePermission.resolve(IsAuthenticated), IsAuthenticated)
        inst = IsOwner("user_id", "owner_id")
        assert BasePermission.resolve(inst) is inst

    def test_class_or_none_builds_pep604_union(self):
        union = IsAuthenticated | None
        assert isinstance(union, UnionType)
        assert set(get_args(union)) == {IsAuthenticated, type(None)}

    def test_class_or_plain_type_builds_pep604_union(self):
        union = IsAuthenticated | str
        assert isinstance(union, UnionType)
        assert set(get_args(union)) == {IsAuthenticated, str}

    def test_composites_are_permissions(self):
        perm = IsAuthenticated & HasPermissions("read:docs")
        assert isinstance(perm, AndPermission)
        assert isinstance(perm | IsAdmin("admin"), OrPermission)
        assert isinstance(~perm, NotPermission)


class TestBuiltins:
    def test_allow_any(self):
        assert AllowAny().has_permission(None, view())
        assert AllowAny().has_object_permission(user(), view(), object())

    def test_is_authenticated(self):
        assert IsAuthenticated().has_permission(user(), view())
        assert not IsAuthenticated().has_permission(None, view())

    def test_has_permissions(self):
        perm = HasPermissions("read:docs", "write:docs")
        assert perm.has_permission(
            user(permissions=["read:docs", "write:docs"]), view()
        )
        assert not perm.has_permission(user(permissions=["read:docs"]), view())
        assert not perm.has_permission(None, view())
        assert sorted(perm.required_scopes) == ["read:docs", "write:docs"]

    def test_has_scopes_alias(self):
        assert HasScopes is HasPermissions

    def test_is_owner(self):
        perm = IsOwner("user_id", "owner_id")
        own = user(user_id=UUID(int=1))
        obj = SimpleNamespace(owner_id=UUID(int=1))
        assert perm.has_object_permission(own, view(), obj)
        assert not perm.has_object_permission(user(user_id=UUID(int=2)), view(), obj)
        assert not perm.has_object_permission(None, view(), obj)
        assert not perm.has_object_permission(own, view(), None)

    def test_is_admin(self):
        perm = IsAdmin("admin")
        assert perm.has_permission(user(permissions=["admin"]), view())
        assert not perm.has_permission(user(permissions=[]), view())
        assert not perm.has_permission(None, view())
        assert perm.required_scopes == ["admin"]

    def test_is_admin_or_owner_object(self):
        perm = IsAdminOrOwner("admin", "user_id", "owner_id")
        obj = SimpleNamespace(owner_id=UUID(int=1))
        assert perm.has_object_permission(
            user(permissions=["admin"], user_id=UUID(int=9)), view(), obj
        )
        assert perm.has_object_permission(user(user_id=UUID(int=1)), view(), obj)
        assert not perm.has_object_permission(user(user_id=UUID(int=9)), view(), obj)

    def test_is_authenticated_or_read_only(self):
        perm = IsAuthenticatedOrReadOnly()
        assert perm.has_permission(None, view("GET"))
        assert perm.has_permission(user(), view("POST"))
        assert not perm.has_permission(None, view("POST"))


class _PrefixScopeValidator(ScopeValidator):
    """Deliberately permissive validator: a granted prefix covers a scope."""

    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        return any(scope.startswith(granted) for granted in granted_scopes)


class TestScopeValidator:
    def test_defaults_to_verbatim_matching(self):
        perm = HasScopes("read:items")
        assert isinstance(perm.scope_validator, SimpleScopeValidator)
        assert perm.has_permission(user(permissions=["read:items"]), view())
        assert not perm.has_permission(user(permissions=["edit:items"]), view())
        assert not perm.has_permission(user(permissions=["*:items"]), view())
        assert not perm.has_permission(user(permissions=["*"]), view())

    def test_explicit_simple_validator_matches_the_default(self):
        perm = HasScopes("read:items", scope_validator=SimpleScopeValidator())
        assert perm.has_permission(user(permissions=["read:items"]), view())
        assert not perm.has_permission(user(permissions=["edit:items"]), view())

    def test_hierarchical_validator_honours_implied_actions(self):
        perm = HasScopes("read:items", scope_validator=HierarchicalScopeValidator())
        assert perm.has_permission(user(permissions=["read:items"]), view())
        assert perm.has_permission(user(permissions=["edit:items"]), view())
        assert perm.has_permission(user(permissions=["delete:items"]), view())
        assert not perm.has_permission(user(permissions=["read:docs"]), view())

    def test_hierarchical_validator_honours_wildcards(self):
        perm = HasScopes("read:items", scope_validator=HierarchicalScopeValidator())
        assert perm.has_permission(user(permissions=["*:*"]), view())
        assert perm.has_permission(user(permissions=["*:items"]), view())
        assert perm.has_permission(user(permissions=["read:*"]), view())

    def test_has_permissions_accepts_the_same_keyword(self):
        perm = HasPermissions(
            "read:items", "read:docs", scope_validator=HierarchicalScopeValidator()
        )
        assert perm.has_permission(user(permissions=["edit:*"]), view())
        assert not perm.has_permission(user(permissions=["edit:items"]), view())

    def test_custom_validator_is_used(self):
        perm = HasScopes("read:items", scope_validator=_PrefixScopeValidator())
        assert perm.has_permission(user(permissions=["read:"]), view())
        assert not perm.has_permission(user(permissions=["edit:"]), view())

    def test_anonymous_is_rejected_before_the_validator_runs(self):
        perm = HasScopes("read:items", scope_validator=_PrefixScopeValidator())
        assert not perm.has_permission(None, view())

    def test_missing_permissions_attribute_grants_nothing(self):
        perm = HasScopes("read:items", scope_validator=HierarchicalScopeValidator())
        assert not perm.has_permission(SimpleNamespace(), view())

    def test_required_scopes_are_unaffected_by_the_validator(self):
        perm = HasScopes(
            "read:items", "read:docs", scope_validator=HierarchicalScopeValidator()
        )
        assert sorted(perm.required_scopes) == ["read:docs", "read:items"]

    def test_composites_delegate_to_the_configured_validator(self):
        hierarchical = HasScopes(
            "read:items", scope_validator=HierarchicalScopeValidator()
        )
        both = IsAuthenticated & hierarchical
        assert both.has_permission(user(permissions=["edit:items"]), view())
        either = IsAdmin("admin") | hierarchical
        assert either.has_permission(user(permissions=["edit:items"]), view())
        assert (~hierarchical).has_permission(user(permissions=["read:docs"]), view())
        assert not (~hierarchical).has_permission(
            user(permissions=["edit:items"]), view()
        )
        assert both.required_scopes == ["read:items"]


class TestPermissionDenied:
    def test_anonymous_is_unauthorized(self):
        assert isinstance(permission_denied(None), Unauthorized)

    def test_anonymous_yields_401(self):
        assert permission_denied(None).get_status() == HTTP_401_UNAUTHORIZED

    def test_authenticated_yields_403(self):
        assert permission_denied(user()).get_status() == HTTP_403_FORBIDDEN


class TestAuthenticated:
    @pytest.mark.anyio
    async def test_isinstance_returns_typed_principal(self):
        auth = make_jwt_auth(custom_class=make_user)
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/me", dependencies=[Security(auth.resolve_dependency)])
        async def me(principal: Authenticated[User]) -> dict:
            return {"id": str(principal.user_id), "perms": principal.permissions}

        async with app_client(app) as client:
            uid = str(uuid4())
            token = auth.create_access_token(
                {"sub": uid, "scope": "read:docs"}
            ).access_token
            resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == HTTP_200_OK
            body = resp.json()
            assert body["id"] == uid
            assert body["perms"] == ["read:docs"]

    @pytest.mark.anyio
    async def test_anonymous_yields_401(self):
        auth = make_jwt_auth(custom_class=make_user)
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/me", dependencies=[Security(auth.resolve_dependency)])
        async def me(principal: Authenticated[User]) -> dict:
            return {"id": str(principal.user_id)}

        async with app_client(app) as client:
            assert (await client.get("/me")).status_code == HTTP_401_UNAUTHORIZED

    @pytest.mark.anyio
    async def test_coercion_failure_yields_403(self):
        auth = make_jwt_auth()
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/strict", dependencies=[Security(auth.resolve_dependency)])
        async def strict(principal: Authenticated[StrictUser]) -> dict:
            return {"id": str(principal.user_id)}

        async with app_client(app) as client:
            no_org = auth.create_access_token({"sub": str(uuid4())}).access_token
            assert (
                await client.get(
                    "/strict", headers={"Authorization": f"Bearer {no_org}"}
                )
            ).status_code == HTTP_403_FORBIDDEN

    @pytest.mark.anyio
    async def test_coercion_succeeds_when_required_field_present(self):
        auth = make_jwt_auth()
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/strict", dependencies=[Security(auth.resolve_dependency)])
        async def strict(principal: Authenticated[StrictUser]) -> dict:
            return {"org": str(principal.org_id)}

        async with app_client(app) as client:
            org = uuid4()
            token = auth.create_access_token(
                {"sub": str(uuid4()), "org_id": str(org)}
            ).access_token
            resp = await client.get(
                "/strict", headers={"Authorization": f"Bearer {token}"}
            )
            assert resp.status_code == HTTP_200_OK
            assert resp.json()["org"] == str(org)

    @pytest.mark.anyio
    async def test_union_picks_fitting_member(self):
        auth = make_jwt_auth()
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/actor", dependencies=[Security(auth.resolve_dependency)])
        async def actor(principal: Authenticated[StrictUser | Device]) -> dict:
            return {"kind": type(principal).__name__}

        async with app_client(app) as client:
            user_token = auth.create_access_token(
                {"sub": str(uuid4()), "org_id": str(uuid4())}
            ).access_token
            device_token = auth.create_access_token({"sub": str(uuid4())}).access_token
            user_resp = await client.get(
                "/actor", headers={"Authorization": f"Bearer {user_token}"}
            )
            device_resp = await client.get(
                "/actor", headers={"Authorization": f"Bearer {device_token}"}
            )
            assert user_resp.status_code == HTTP_200_OK
            assert user_resp.json()["kind"] == "StrictUser"
            assert device_resp.status_code == HTTP_200_OK
            assert device_resp.json()["kind"] == "Device"

    @pytest.mark.anyio
    async def test_from_principal_wrapper(self):
        auth = make_jwt_auth(custom_class=make_user)
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/w", dependencies=[Security(auth.resolve_dependency)])
        async def w(principal: Authenticated[Wrapper]) -> dict:
            return {"label": principal.label}

        async with app_client(app) as client:
            token = _token(auth)
            resp = await client.get("/w", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == HTTP_200_OK
            assert resp.json()["label"].startswith("user:")

    @pytest.mark.anyio
    async def test_attribute_error_during_coercion_yields_403(self):
        auth = make_jwt_auth()
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/attr", dependencies=[Security(auth.resolve_dependency)])
        async def attr(principal: Authenticated[AttrUser]) -> dict:
            return {"id": str(principal.user_id)}

        async with app_client(app) as client:
            token = _token(auth)
            resp = await client.get(
                "/attr", headers={"Authorization": f"Bearer {token}"}
            )
            assert resp.status_code == HTTP_403_FORBIDDEN

    @pytest.mark.anyio
    async def test_union_skips_member_raising_attribute_error(self):
        auth = make_jwt_auth()
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/either", dependencies=[Security(auth.resolve_dependency)])
        async def either(principal: Authenticated[AttrUser | Device]) -> dict:
            return {"kind": type(principal).__name__}

        async with app_client(app) as client:
            token = _token(auth)
            resp = await client.get(
                "/either", headers={"Authorization": f"Bearer {token}"}
            )
            assert resp.status_code == HTTP_200_OK
            assert resp.json()["kind"] == "Device"

    @pytest.mark.anyio
    async def test_parameterized_generic_target_passes_dict_through(self):
        auth = make_jwt_auth()
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/claims", dependencies=[Security(auth.resolve_dependency)])
        async def claims(principal: Authenticated[dict[str, Any]]) -> dict:
            return {"sub": principal["sub"]}

        async with app_client(app) as client:
            uid = str(uuid4())
            token = auth.create_access_token({"sub": uid}).access_token
            resp = await client.get(
                "/claims", headers={"Authorization": f"Bearer {token}"}
            )
            assert resp.status_code == HTTP_200_OK
            assert resp.json()["sub"] == uid

    @pytest.mark.anyio
    async def test_resolver_is_shared_so_coercion_runs_once(self):
        auth = make_jwt_auth()
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/once", dependencies=[Security(auth.resolve_dependency)])
        async def once(
            principal: Authenticated[CountingUser],
            shared: Annotated[UUID, Depends(counting_sub_dependency)],
        ) -> dict:
            return {
                "same": principal.user_id == shared,
                "coercions": CountingUser.coercions,
            }

        CountingUser.coercions = 0
        async with app_client(app) as client:
            token = _token(auth)
            resp = await client.get(
                "/once", headers={"Authorization": f"Bearer {token}"}
            )
            assert resp.status_code == HTTP_200_OK
            assert resp.json() == {"same": True, "coercions": 1}

    @pytest.mark.anyio
    async def test_current_user(self):
        auth = make_jwt_auth(custom_class=make_user)
        app = FastAPI()
        add_error_handlers(app)

        @app.get("/me", dependencies=[Security(auth.resolve_dependency)])
        async def me(principal: CurrentUser) -> dict:
            return {"perms": list(principal.permissions)}

        async with app_client(app) as client:
            token = auth.create_access_token(
                {"sub": str(uuid4()), "scope": "read:docs write:docs"}
            ).access_token
            resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == HTTP_200_OK
            assert resp.json()["perms"] == ["read:docs", "write:docs"]
            assert (await client.get("/me")).status_code == HTTP_401_UNAUTHORIZED


class DocListView(AsyncListAPIView):
    response_schema = DocSchema
    permission_classes: ClassVar = [IsAuthenticated & HasPermissions("read:docs")]

    async def list(self) -> list[dict[str, str]]:
        return [{"id": str(uuid4()), "owner_id": str(uuid4())}]


class TestViewBridge:
    @pytest.mark.anyio
    async def test_permitted(self):
        set_app_auth(make_jwt_auth(custom_class=make_user))
        app = build_app(DocListView)
        auth = get_app_auth()
        async with app_client(app) as client:
            token = auth.create_access_token(
                {"sub": str(uuid4()), "scope": "read:docs"}
            ).access_token
            assert (
                await client.get("/test", headers={"Authorization": f"Bearer {token}"})
            ).status_code == HTTP_200_OK

    @pytest.mark.anyio
    async def test_missing_permission_yields_403(self):
        set_app_auth(make_jwt_auth(custom_class=make_user))
        app = build_app(DocListView)
        auth = get_app_auth()
        async with app_client(app) as client:
            token = auth.create_access_token(
                {"sub": str(uuid4()), "scope": "other"}
            ).access_token
            assert (
                await client.get("/test", headers={"Authorization": f"Bearer {token}"})
            ).status_code == HTTP_403_FORBIDDEN

    @pytest.mark.anyio
    async def test_anonymous_yields_401(self):
        set_app_auth(make_jwt_auth(custom_class=make_user))
        app = build_app(DocListView)
        async with app_client(app) as client:
            assert (await client.get("/test")).status_code == HTTP_401_UNAUTHORIZED

    @pytest.mark.anyio
    async def test_openapi_advertises_security_scopes(self):
        set_app_auth(make_jwt_auth(custom_class=make_user))
        app = build_app(DocListView)
        spec = app.openapi()
        schemes = spec["components"]["securitySchemes"]
        assert schemes, "expected a security scheme for the bridge"
        security = spec["paths"]["/test"]["get"]["security"]
        required_scopes = [
            scope for item in security for scopes in item.values() for scope in scopes
        ]
        assert "read:docs" in required_scopes

    @pytest.mark.anyio
    async def test_allow_any_does_not_wire_auth(self):
        class PublicView(AsyncListAPIView):
            response_schema = DocSchema
            permission_classes: ClassVar = [AllowAny]

            async def list(self) -> list[dict[str, str]]:
                return []

        set_app_auth(make_jwt_auth(custom_class=make_user))
        app = build_app(PublicView)
        spec = app.openapi()
        assert spec["paths"]["/test"]["get"].get("security") in (None, [])
        async with app_client(app) as client:
            assert (await client.get("/test")).status_code == HTTP_200_OK


class OwnerRetrieveView(AsyncRetrieveAPIView):
    response_schema = DocSchema
    permission_classes: ClassVar = [IsOwner("user_id", "owner_id")]
    detail_route = "/{id}"

    async def retrieve(self, id: str) -> DocSchema:
        return DocSchema(id=UUID(id), owner_id=self.principal.user_id)


class NotOwnerRetrieveView(AsyncRetrieveAPIView):
    response_schema = DocSchema
    permission_classes: ClassVar = [IsOwner("user_id", "owner_id")]
    detail_route = "/{id}"

    async def retrieve(self, id: str) -> DocSchema:
        return DocSchema(id=UUID(id), owner_id=UUID(int=999))


class TestObjectLevel:
    @pytest.mark.anyio
    async def test_owner_succeeds(self):
        set_app_auth(make_jwt_auth(custom_class=make_user))
        app = build_app(OwnerRetrieveView)
        auth = get_app_auth()
        async with app_client(app) as client:
            token = _token(auth)
            assert (
                await client.get(
                    f"/test/{uuid4()}", headers={"Authorization": f"Bearer {token}"}
                )
            ).status_code == HTTP_200_OK

    @pytest.mark.anyio
    async def test_non_owner_forbidden(self):
        set_app_auth(make_jwt_auth(custom_class=make_user))
        app = build_app(NotOwnerRetrieveView)
        auth = get_app_auth()
        async with app_client(app) as client:
            token = _token(auth)
            assert (
                await client.get(
                    f"/test/{uuid4()}", headers={"Authorization": f"Bearer {token}"}
                )
            ).status_code == HTTP_403_FORBIDDEN

    @pytest.mark.anyio
    async def test_anonymous_yields_401(self):
        set_app_auth(make_jwt_auth(custom_class=make_user))
        app = build_app(NotOwnerRetrieveView)
        async with app_client(app) as client:
            assert (
                await client.get(f"/test/{uuid4()}")
            ).status_code == HTTP_401_UNAUTHORIZED


class TestConfigureApp:
    @pytest.mark.anyio
    async def test_configure_app_registers_app_auth(self):
        auth = make_jwt_auth(custom_class=make_user)
        app = FastAPI()
        configure_app(app, auth=auth, limits=None)
        assert get_app_auth() is auth
        router = ViewRouter()
        router.register_view(DocListView, prefix="/test")
        app.include_router(router)
        async with app_client(app) as client:
            token = auth.create_access_token(
                {"sub": str(uuid4()), "scope": "read:docs"}
            ).access_token
            assert (
                await client.get("/test", headers={"Authorization": f"Bearer {token}"})
            ).status_code == HTTP_200_OK

    def test_get_app_auth_raises_when_unset(self):
        set_app_auth(None)
        with pytest.raises(RuntimeError, match="No app auth configured"):
            get_app_auth()

    def test_principal_protocol_is_runtime_checkable(self):
        assert isinstance(user(), Principal)
        assert not isinstance(object(), Principal)
