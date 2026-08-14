from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import AsyncMock

import pytest
from auth0_api_python.api_client import BaseAuthError
from fastapi import Depends, FastAPI
from joserfc import jwk, jwt
from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)

from fastapi_views.auth import (
    AuthBase,
    AutoScopesAuthView,
    Delete,
    ScopesAuth,
    TokenAuth,
)
from fastapi_views.auth import abc as auth_abc
from fastapi_views.auth import api_key as auth_api_key
from fastapi_views.auth.api_key import APIKeyAuth, ConstAPIKeyAuth
from fastapi_views.auth.jwt import (
    BearerAccessToken,
    JWTAuth,
    JWTConfig,
    utc_timestamp,
)
from fastapi_views.auth.scopes import (
    HierarchicalScopeValidator,
    Scope,
    ScopeValidator,
    SimpleScopeValidator,
)
from fastapi_views.exceptions import APIError, Unauthorized
from fastapi_views.handlers import add_error_handlers
from fastapi_views.integrations.auth0 import Auth0
from fastapi_views.permissions import set_app_auth

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence


def make_config(**kwargs: Any) -> JWTConfig:
    """Build a freshly-keyed HS256 config so tests never share signing keys."""
    key = jwk.OctKey.generate_key(256)
    kwargs.setdefault("algorithms", ["HS256"])
    return JWTConfig(key=key, **kwargs)


@pytest.fixture
def app() -> FastAPI:
    # Override conftest's plain app so APIError exceptions become JSON responses.
    app = FastAPI()
    add_error_handlers(app)
    return app


@pytest.fixture
def config() -> JWTConfig:
    return make_config(expiration_seconds=3600)


@pytest.fixture
def jwt_auth(config) -> JWTAuth:
    return JWTAuth(config, None)


@pytest.fixture
def app_auth(jwt_auth) -> Generator[JWTAuth, None, None]:
    """Register ``jwt_auth`` as the app auth for the duration of the test."""
    set_app_auth(jwt_auth)
    yield jwt_auth
    set_app_auth(None)


def test_jwt_config_get_key_raises_when_uninitialized():
    config = JWTConfig()
    with pytest.raises(ValueError, match="Key not initialized"):
        config.get_key()


def test_jwt_config_single_algorithm_populates_header_alg():
    config = JWTConfig(algorithms=["HS256"])
    assert config.header["alg"] == "HS256"


def test_jwt_config_does_not_override_explicit_header_alg():
    config = JWTConfig(algorithms=["HS256"], header={"alg": "HS512"})
    assert config.header["alg"] == "HS512"


def test_jwt_config_multiple_algorithms_leave_header_untouched():
    config = JWTConfig(algorithms=["HS256", "HS384"])
    assert "alg" not in config.header


def test_jwt_config_issuer_url_marks_iss_claim_essential():
    config = JWTConfig(issuer_url="https://issuer.example")
    assert config.claims_registry.options["iss"] == {
        "essential": True,
        "value": "https://issuer.example",
    }


def test_jwt_config_jwks_wraps_single_key():
    key = jwk.OctKey.generate_key(256)
    jwks = JWTAuth(JWTConfig(key=key), None).jwks
    assert "keys" in jwks
    assert len(jwks["keys"]) == 1


def test_jwt_config_jwks_serializes_key_set():
    key_set = jwk.KeySet([jwk.OctKey.generate_key(256), jwk.OctKey.generate_key(256)])
    jwks = JWTAuth(JWTConfig(key=key_set), None).jwks
    assert len(jwks["keys"]) == 2


def test_jwt_config_jwks_excludes_private_material():
    key = jwk.RSAKey.generate_key(2048, private=True)
    jwks = JWTAuth(JWTConfig(key=key), None).jwks
    # private exponent must never be exposed in a public JWKS
    assert "d" not in jwks["keys"][0]


def test_jwt_config_import_key_sets_single_key():
    config = JWTConfig(key_type="oct")
    config.import_key("a-shared-secret-value")
    assert config.get_key() is not None


def test_jwt_config_import_key_imports_key_set():
    jwks = JWTAuth(JWTConfig(key=jwk.KeySet([jwk.OctKey.generate_key(256)])), None).jwks
    config = JWTConfig()
    config.import_key(jwks)
    assert isinstance(config.get_key(), jwk.KeySet)


def test_utc_timestamp_returns_int():
    assert isinstance(utc_timestamp(), int)


def test_encode_returns_bearer_access_token(jwt_auth):
    bearer = jwt_auth.create_access_token({"sub": "user-1"})
    assert isinstance(bearer, BearerAccessToken)
    assert bearer.token_type == "bearer"  # noqa: S105  # nosec B105
    assert bearer.access_token


@pytest.mark.anyio
async def test_encode_verify_round_trip(jwt_auth):
    bearer = jwt_auth.create_access_token({"sub": "user-1"})
    claims = await jwt_auth.verify(bearer.access_token)
    assert claims["sub"] == "user-1"


def test_encode_sets_exp_from_config_expiration(jwt_auth):
    bearer = jwt_auth.create_access_token({"sub": "user-1"})
    claims = jwt.decode(bearer.access_token, jwt_auth.config.get_key()).claims
    assert claims["exp"] == claims["iat"] + 3600


def test_encode_without_expiration_has_no_exp():
    auth = JWTAuth(make_config(), None)
    bearer = auth.create_access_token({"sub": "user-1"})
    claims = jwt.decode(bearer.access_token, auth.config.get_key()).claims
    assert "exp" not in claims
    assert bearer.expires_in is None


def test_encode_expires_in_overrides_config(jwt_auth):
    bearer = jwt_auth.create_access_token({"sub": "user-1"}, expires_in=60)
    claims = jwt.decode(bearer.access_token, jwt_auth.config.get_key()).claims
    assert claims["exp"] == claims["iat"] + 60
    assert bearer.expires_in == 60


def test_encode_explicit_exp_is_not_overridden(jwt_auth):
    bearer = jwt_auth.create_access_token({"sub": "user-1", "exp": utc_timestamp() + 5})
    claims = jwt.decode(bearer.access_token, jwt_auth.config.get_key()).claims
    # explicit exp wins over the config-derived value
    assert claims["exp"] != claims["iat"] + 3600


def test_encode_populates_iss_from_issuer_url():
    auth = JWTAuth(make_config(issuer_url="https://issuer.example"), None)
    bearer = auth.create_access_token({"sub": "user-1"})
    claims = jwt.decode(bearer.access_token, auth.config.get_key()).claims
    assert claims["iss"] == "https://issuer.example"


def test_encode_explicit_iss_is_not_overridden():
    auth = JWTAuth(make_config(issuer_url="https://issuer.example"), None)
    bearer = auth.create_access_token({"sub": "user-1", "iss": "https://other"})
    claims = jwt.decode(bearer.access_token, auth.config.get_key()).claims
    assert claims["iss"] == "https://other"


@pytest.mark.anyio
async def test_verify_accepts_valid_token(jwt_auth):
    bearer = jwt_auth.create_access_token({"sub": "user-1"})
    claims = await jwt_auth.verify(bearer.access_token)
    assert claims["sub"] == "user-1"


@pytest.mark.anyio
async def test_verify_rejects_bad_signature(jwt_auth):
    foreign = jwt.encode(
        {"alg": "HS256"},
        {"sub": "user-1", "iat": utc_timestamp()},
        jwk.OctKey.generate_key(256),
    )
    with pytest.raises(Unauthorized):
        await jwt_auth.verify(foreign)


@pytest.mark.anyio
async def test_verify_rejects_malformed_token(jwt_auth):
    with pytest.raises(Unauthorized):
        await jwt_auth.verify("not-a-jwt")


@pytest.mark.anyio
async def test_verify_enforces_issuer_claim():
    auth = JWTAuth(make_config(issuer_url="https://issuer.example"), None)
    forged = jwt.encode(
        {"alg": "HS256"},
        {"sub": "user-1", "iss": "https://attacker.example", "iat": utc_timestamp()},
        auth.config.get_key(),
    )
    with pytest.raises(Unauthorized):
        await auth.verify(forged)


@pytest.mark.parametrize(
    ("required", "granted", "expected"),
    [
        ("read:user", ["read:user"], True),
        ("read:user", ["*:user"], True),  # wildcard action grants everything
        ("read:user", ["read:*"], True),  # wildcard resource
        ("read:user", ["edit:user"], True),  # edit implies read (hierarchy)
        ("edit:user", ["read:user"], False),  # read does not imply edit
        ("edit:user", ["*:user"], True),
        ("read:post", ["read:user"], False),  # different resource
        ("read:user", ["read:other", "edit:user"], True),  # any granted match
        ("read:user", [], False),
    ],
)
def test_has_scope(jwt_auth, required, granted, expected):
    assert jwt_auth.has_scope(required, granted) is expected


def test_resolve_action_includes_self_and_implied():
    # explicit hierarchy: edit/delete imply read, all implies read+edit+delete
    validator = HierarchicalScopeValidator()
    assert validator._resolve_action("edit") == {"edit", "read"}
    assert validator._resolve_action("delete") == {"delete", "read"}
    assert validator._resolve_action("*") == {"*", "read", "edit", "delete"}
    assert validator._resolve_action("unknown") == {"unknown"}


def test_scopes_auth_defaults_to_hierarchical_validator(jwt_auth):
    assert isinstance(jwt_auth.scope_validator, HierarchicalScopeValidator)


@pytest.mark.parametrize(
    ("required", "granted", "expected"),
    [
        ("read:user", ["read:user"], True),  # exact match
        ("read:user", ["read:user", "edit:post"], True),  # contained verbatim
        ("read:user", ["*:user"], False),  # no wildcard expansion
        ("read:user", ["edit:user"], False),  # no hierarchy
        ("read:user", [], False),
    ],
)
def test_simple_scope_validator(required, granted, expected):
    assert SimpleScopeValidator().has_scope(required, granted) is expected


def test_scopes_auth_uses_injected_validator(config):
    auth = JWTAuth(config, scope_validator=SimpleScopeValidator())
    assert isinstance(auth.scope_validator, SimpleScopeValidator)
    # delegates to the simple strategy: hierarchy no longer applies
    assert auth.has_scope("read:user", ["read:user"]) is True
    assert auth.has_scope("read:user", ["edit:user"]) is False


@pytest.mark.anyio
async def test_endpoint_forbids_with_simple_validator(config, app, client):
    auth = JWTAuth(config, scope_validator=SimpleScopeValidator())

    @app.get("/items")
    async def items(token=auth.requires("read:user")):
        return {"sub": token["sub"]}

    # "edit:user" would satisfy the hierarchical validator but not the simple one
    bearer = auth.create_access_token({"sub": "user-1", "scope": "edit:user"})
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_endpoint_requires_token(jwt_auth, app, client):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return {"sub": token["sub"]}

    assert (await client.get("/me")).status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_endpoint_accepts_valid_token(jwt_auth, app, client):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return {"sub": token["sub"]}

    bearer = jwt_auth.create_access_token({"sub": "user-1"})
    response = await client.get(
        "/me", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"sub": "user-1"}


@pytest.mark.anyio
async def test_endpoint_rejects_invalid_token(jwt_auth, app, client):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return {"sub": token["sub"]}

    response = await client.get(
        "/me", headers={"Authorization": "Bearer garbage.token.value"}
    )
    assert response.status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_endpoint_requires_scope_rejects_missing_token(jwt_auth, app, client):
    @app.get("/items")
    async def items(token=jwt_auth.requires("read:user")):
        return {"sub": token["sub"]}

    assert (await client.get("/items")).status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_endpoint_allows_sufficient_scope(jwt_auth, app, client):
    @app.get("/items")
    async def items(token=jwt_auth.requires("read:user")):
        return {"sub": token["sub"]}

    bearer = jwt_auth.create_access_token({"sub": "user-1", "scope": "edit:user"})
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"sub": "user-1"}


@pytest.mark.anyio
async def test_endpoint_forbids_insufficient_scope(jwt_auth, app, client):
    @app.get("/items")
    async def items(token=jwt_auth.requires("edit:user")):
        return {"sub": token["sub"]}

    bearer = jwt_auth.create_access_token({"sub": "user-1", "scope": "read:user"})
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_403_FORBIDDEN
    assert "edit:user" in response.json()["detail"]


@pytest.mark.anyio
async def test_api_key_accepts_present_key(app, client):
    auth = APIKeyAuth()

    @app.get("/protected")
    async def protected(key=auth.authenticated()):
        return {"key": key}

    response = await client.get("/protected", headers={"X-Api-Key": "the-secret"})
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"key": "the-secret"}


@pytest.mark.anyio
async def test_api_key_rejects_missing_header(app, client):
    auth = APIKeyAuth()

    @app.get("/protected")
    async def protected(key=auth.authenticated()):
        return {"key": key}

    response = await client.get("/protected")
    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid API Key"


@pytest.mark.anyio
async def test_api_key_honors_custom_header_name(app, client):
    auth = APIKeyAuth(name="Authorization-Key")

    @app.get("/protected")
    async def protected(key=auth.authenticated()):
        return {"key": key}

    response = await client.get(
        "/protected", headers={"Authorization-Key": "the-secret"}
    )
    assert response.status_code == HTTP_200_OK


@pytest.mark.anyio
async def test_api_key_401_advertises_subclass_challenge(app, client):
    class CustomAPIKeyAuth(APIKeyAuth):
        challenge: ClassVar[str] = "CustomScheme"

    auth = CustomAPIKeyAuth()

    @app.get("/protected")
    async def protected(key=auth.authenticated()):
        return {"key": key}

    response = await client.get("/protected")
    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "CustomScheme"


@pytest.mark.anyio
async def test_const_api_key_accepts_matching_key(app, client):
    auth = ConstAPIKeyAuth("the-secret")

    @app.get("/protected")
    async def protected(key=auth.authenticated()):
        return {"key": key}

    response = await client.get("/protected", headers={"X-Api-Key": "the-secret"})
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"key": "the-secret"}


@pytest.mark.anyio
async def test_const_api_key_rejects_wrong_key(app, client):
    auth = ConstAPIKeyAuth("the-secret")

    @app.get("/protected")
    async def protected(key=auth.authenticated()):
        return {"key": key}

    response = await client.get("/protected", headers={"X-Api-Key": "not-the-secret"})
    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid API Key"
    assert response.headers["WWW-Authenticate"] == "APIKey"


@pytest.mark.anyio
async def test_const_api_key_rejects_missing_header(app, client):
    auth = ConstAPIKeyAuth("the-secret")

    @app.get("/protected")
    async def protected(key=auth.authenticated()):
        return {"key": key}

    response = await client.get("/protected")
    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid API Key"


@pytest.mark.anyio
async def test_const_api_key_compares_digest_once_per_request(app, client, monkeypatch):
    auth = ConstAPIKeyAuth("the-secret")
    calls: list[tuple[Any, Any]] = []
    compare_digest = secrets.compare_digest

    def counting_compare_digest(a: Any, b: Any) -> bool:
        calls.append((a, b))
        return compare_digest(a, b)

    monkeypatch.setattr(auth_api_key.secrets, "compare_digest", counting_compare_digest)

    @app.get("/protected")
    async def protected(key=auth.authenticated()):
        return {"key": key}

    response = await client.get("/protected", headers={"X-Api-Key": "the-secret"})
    assert response.status_code == HTTP_200_OK
    assert len(calls) == 1


class _FakeAuthError(BaseAuthError):
    def get_error_code(self) -> str:
        return "invalid_token"

    def get_status_code(self) -> int:
        return HTTP_401_UNAUTHORIZED

    def get_headers(self) -> dict[str, str]:
        return {"WWW-Authenticate": "Bearer"}


@pytest.mark.anyio
async def test_auth0_verify_returns_verified_claims():
    api_client = AsyncMock()
    api_client.verify_access_token.return_value = {"sub": "auth0|123"}

    auth = Auth0(api_client)
    claims = await auth.verify("any-token")

    assert claims["sub"] == "auth0|123"
    api_client.verify_access_token.assert_awaited_once_with("any-token")


@pytest.mark.anyio
async def test_auth0_verify_maps_auth_error_to_api_error():
    api_client = AsyncMock()
    api_client.verify_access_token.side_effect = _FakeAuthError("token expired")

    auth = Auth0(api_client)
    with pytest.raises(APIError) as exc_info:
        await auth.verify("any-token")

    error = exc_info.value
    assert error.status_code == HTTP_401_UNAUTHORIZED
    assert error.as_model().detail == "token expired"


def test_auth0_reads_scope_claim_by_default():
    auth = Auth0(AsyncMock())
    granted = auth.get_granted_scopes({"scope": "read:items edit:items"})
    assert granted == ["read:items", "edit:items"]


def test_auth0_reads_permissions_claim_when_configured():
    auth = Auth0(AsyncMock(), permission_key="permissions")
    granted = auth.get_granted_scopes({"permissions": ["read:items"]})
    assert granted == ["read:items"]


@pytest.mark.anyio
async def test_with_test_user_bypasses_verification(jwt_auth, app, client):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return token

    with jwt_auth.with_test_user({"sub": "tester"}):
        response = await client.get("/me")

    assert response.status_code == HTTP_200_OK
    assert response.json() == {"sub": "tester"}
    # override is cleared once the context exits
    assert (await client.get("/me")).status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_with_test_user_honors_falsy_user(jwt_auth, app, client):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return token

    with jwt_auth.with_test_user({}):
        response = await client.get("/me")

    assert response.status_code == HTTP_200_OK
    assert response.json() == {}


def test_with_test_user_is_reset_when_body_raises(jwt_auth):
    with (
        pytest.raises(RuntimeError, match="boom"),
        jwt_auth.with_test_user({"sub": "t"}),
    ):
        raise RuntimeError("boom")

    assert jwt_auth._test_user is None


@pytest.mark.parametrize(
    ("action", "scope"),
    [
        ("list", "read:items"),
        ("retrieve", "read:items"),
        ("create", "edit:items"),
        ("update", "edit:items"),
        ("bulk_update", "edit:items"),
        ("destroy", "delete:items"),
        ("bulk_delete", "delete:items"),
    ],
)
def test_auto_scopes_auth_view_maps_action_to_scope(app_auth, action, scope):
    class ItemsView(AutoScopesAuthView):
        resource = "items"

    (dependency,) = ItemsView.get_dependencies(action)
    assert list(dependency.scopes) == [scope]


def test_auto_scopes_auth_view_returns_no_dependencies_without_action(app_auth):
    class ItemsView(AutoScopesAuthView):
        resource = "items"

    assert ItemsView.get_dependencies() == []


def test_auto_scopes_auth_view_rejects_unknown_action(app_auth):
    class ItemsView(AutoScopesAuthView):
        resource = "items"

    unknown_action: Any = "publish"
    with pytest.raises(LookupError, match="publish"):
        ItemsView.get_dependencies(unknown_action)


def test_auto_scopes_auth_view_merges_action_dependencies(app_auth):
    marker = Depends(lambda: None)

    class ItemsView(AutoScopesAuthView):
        resource = "items"
        action_dependencies: ClassVar = {"retrieve": [marker]}

    scope_dependency, extra = ItemsView.get_dependencies("retrieve")
    assert list(scope_dependency.scopes) == ["read:items"]
    assert extra is marker


class _PrefixScopeValidator(ScopeValidator):
    """Deliberately permissive validator: a granted prefix covers a scope."""

    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        return any(scope.startswith(granted) for granted in granted_scopes)


def test_token_auth_applies_custom_class():
    auth = TokenAuth(custom_class=lambda raw: {"opaque": raw})
    assert auth.wrap_token("abc") == {"opaque": "abc"}


@pytest.mark.anyio
async def test_token_auth_endpoint_applies_custom_class(app, client):
    auth = TokenAuth(custom_class=lambda raw: {"opaque": raw})

    @app.get("/me")
    async def me(principal=auth.authenticated()):
        return principal

    response = await client.get("/me", headers={"Authorization": "Bearer opaque-value"})
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"opaque": "opaque-value"}


@pytest.mark.anyio
async def test_token_auth_without_custom_class_returns_raw_credential(app, client):
    auth = TokenAuth()

    @app.get("/me")
    async def me(principal=auth.authenticated()):
        return {"raw": principal}

    response = await client.get("/me", headers={"Authorization": "Bearer raw-value"})
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"raw": "raw-value"}


@pytest.mark.anyio
async def test_scopes_auth_still_applies_custom_class(config, app, client):
    auth = JWTAuth(config, custom_class=lambda token: {"user": token["sub"]})

    @app.get("/items")
    async def items(principal=auth.requires("read:items")):
        return principal

    bearer = auth.create_access_token({"sub": "user-1", "scope": "read:items"})
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"user": "user-1"}


@pytest.mark.anyio
async def test_custom_class_not_applied_to_test_user(app, client):
    auth = TokenAuth(custom_class=lambda raw: {"opaque": raw})

    @app.get("/me")
    async def me(principal=auth.authenticated()):
        return principal

    with auth.with_test_user({"sub": "tester"}):
        response = await client.get("/me")

    assert response.json() == {"sub": "tester"}


def test_jwks_is_cached_while_the_key_is_unchanged(jwt_auth):
    assert jwt_auth.jwks is jwt_auth.jwks


def test_jwks_reflects_rotated_key():
    auth = JWTAuth(make_config(), None)
    before = auth.jwks
    rotated = jwk.OctKey.generate_key(256)
    auth.config.import_key(rotated.as_dict(private=True))

    after = auth.jwks
    assert after is not before
    assert after == {"keys": [rotated.as_dict(private=False)]}


def test_jwks_reflects_rotation_to_a_key_set():
    auth = JWTAuth(make_config(), None)
    assert len(auth.jwks["keys"]) == 1
    auth.config.import_key(
        {
            "keys": [
                jwk.OctKey.generate_key(256).as_dict(private=True),
                jwk.OctKey.generate_key(256).as_dict(private=True),
            ]
        }
    )
    assert len(auth.jwks["keys"]) == 2


@pytest.mark.anyio
async def test_jwks_endpoint_serves_rotated_key(app, client):
    auth = JWTAuth(make_config(), None)

    @app.get("/.well-known/jwks.json")
    async def jwks():
        return auth.jwks

    first = (await client.get("/.well-known/jwks.json")).json()
    auth.config.import_key(jwk.OctKey.generate_key(256).as_dict(private=True))
    second = (await client.get("/.well-known/jwks.json")).json()
    assert first != second


def test_token_auth_and_scopes_auth_are_exported_from_auth_package():
    assert TokenAuth is auth_abc.TokenAuth
    assert ScopesAuth is auth_abc.ScopesAuth
    assert {"TokenAuth", "ScopesAuth"} <= set(auth_abc.__all__)


def test_delete_action_is_exported_alongside_the_other_actions():
    assert Delete == "delete"
    assert Delete in HierarchicalScopeValidator.scope_hierarchy
    assert {"All", "Delete", "Edit", "Read"} <= set(auth_abc.__all__)
    assert auth_abc.Delete == Delete


def test_get_granted_scopes_without_claim_is_empty(jwt_auth):
    assert jwt_auth.get_granted_scopes({"sub": "user-1"}) == []
    assert jwt_auth.get_granted_scopes({"sub": "user-1", "scope": ""}) == []


def test_get_granted_scopes_handles_irregular_whitespace(jwt_auth):
    granted = jwt_auth.get_granted_scopes({"scope": "  read:items \t edit:items\n"})
    assert granted == ["read:items", "edit:items"]


def test_scopeless_token_grants_nothing_under_a_permissive_validator(config):
    auth = JWTAuth(config, scope_validator=_PrefixScopeValidator())
    granted = auth.get_granted_scopes({"sub": "user-1"})
    assert auth.has_scope("read:items", granted) is False


@pytest.mark.anyio
async def test_endpoint_forbids_scopeless_token_under_permissive_validator(
    config, app, client
):
    auth = JWTAuth(config, scope_validator=_PrefixScopeValidator())

    @app.get("/items")
    async def items(token=auth.requires("read:items")):
        return {"sub": token["sub"]}

    bearer = auth.create_access_token({"sub": "user-1"})
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_403_FORBIDDEN


def test_auth_base_unauthorized_has_meaningful_detail():
    auth = AuthBase(lambda: None)
    with pytest.raises(Unauthorized) as exc_info:
        auth.unauthorized()

    detail = exc_info.value.as_model().detail
    assert detail == "Missing or invalid credentials"
    assert "No permission" not in detail


@pytest.mark.anyio
async def test_missing_bearer_token_401_advertises_bearer_challenge(
    jwt_auth, app, client
):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return token

    response = await client.get("/me")
    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
    detail = response.json()["detail"]
    assert detail == "Missing or invalid bearer token"
    assert "No permission" not in detail


@pytest.mark.anyio
async def test_invalid_bearer_token_401_advertises_bearer_challenge(
    jwt_auth, app, client
):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return token

    response = await client.get(
        "/me", headers={"Authorization": "Bearer garbage.token.value"}
    )
    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "No permission" not in response.json()["detail"]


@pytest.mark.anyio
async def test_scoped_endpoint_401_advertises_bearer_challenge(jwt_auth, app, client):
    @app.get("/items")
    async def items(token=jwt_auth.requires("read:items")):
        return token

    response = await client.get("/items")
    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
