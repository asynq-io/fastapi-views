from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from joserfc import jwk, jwt
from joserfc.errors import InvalidClaimError
from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)

from fastapi_views import ViewRouter
from fastapi_views.exceptions import APIError, Unauthorized
from fastapi_views.handlers import add_error_handlers
from fastapi_views.security import (
    JWTAuth,
    OAuth2JWTAuth,
    ScopesJsonWebToken,
    require_api_key,
)
from fastapi_views.security.jwt import (
    BaseJsonWebToken,
    BearerAccessToken,
    JWTConfig,
    utc_timestamp,
)
from fastapi_views.security.validator import JoserfcTokenValidator

# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #


def make_token_cls(
    base: type[BaseJsonWebToken] = BaseJsonWebToken, **config: Any
) -> type[BaseJsonWebToken]:
    """Build a freshly-configured token subclass with its own signing key.

    Each call produces an isolated subclass so that ``configure`` (which stores
    config on a ClassVar) never leaks between tests.
    """
    key = jwk.OctKey.generate_key(256)
    config.setdefault("algorithms", ["HS256"])
    cls: type[BaseJsonWebToken] = type(base.__name__ + "Sub", (base,), {})
    cls.configure(JWTConfig(key=key, **config))
    return cls


@pytest.fixture
def app() -> FastAPI:
    # Override conftest's plain app so APIError exceptions become JSON responses.
    app = FastAPI()
    add_error_handlers(app)
    return app


@pytest.fixture
def token_cls() -> type[BaseJsonWebToken]:
    return make_token_cls(expiration_seconds=3600)


@pytest.fixture
def jwt_auth(token_cls) -> JWTAuth:
    return JWTAuth(JoserfcTokenValidator(token_cls))


@pytest.fixture
def scope_token_cls() -> type[ScopesJsonWebToken]:
    return make_token_cls(ScopesJsonWebToken, expiration_seconds=3600)  # type: ignore[return-value]


@pytest.fixture
def oauth(scope_token_cls) -> OAuth2JWTAuth:
    return OAuth2JWTAuth(JoserfcTokenValidator(scope_token_cls))


# --------------------------------------------------------------------------- #
# JWTConfig
# --------------------------------------------------------------------------- #


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
    jwks = JWTConfig(key=key).jwks
    assert "keys" in jwks
    assert len(jwks["keys"]) == 1


def test_jwt_config_jwks_serializes_key_set():
    key_set = jwk.KeySet([jwk.OctKey.generate_key(256), jwk.OctKey.generate_key(256)])
    jwks = JWTConfig(key=key_set).jwks
    assert len(jwks["keys"]) == 2


def test_jwt_config_jwks_excludes_private_material():
    key = jwk.RSAKey.generate_key(2048, private=True)
    jwks = JWTConfig(key=key).jwks
    # private exponent must never be exposed in a public JWKS
    assert "d" not in jwks["keys"][0]


def test_jwt_config_import_key_sets_key():
    config = JWTConfig(key_type="oct")
    config.import_key("a-shared-secret-value")
    assert config.get_key() is not None


# --------------------------------------------------------------------------- #
# BaseJsonWebToken
# --------------------------------------------------------------------------- #


def test_utc_timestamp_returns_int():
    assert isinstance(utc_timestamp(), int)


def test_encode_decode_round_trip(token_cls):
    encoded = token_cls(sub="user-1").encode()
    decoded = token_cls.decode(encoded)
    assert decoded.sub == "user-1"


def test_exp_is_iat_plus_expiration(token_cls):
    token = token_cls(sub="user-1")
    assert token.exp == token.iat + 3600


def test_exp_is_none_without_expiration():
    token = make_token_cls()(sub="user-1")
    assert token.exp is None


def test_iss_auto_populated_from_issuer_url():
    cls = make_token_cls(issuer_url="https://issuer.example", expiration_seconds=3600)
    assert cls(sub="user-1").iss == "https://issuer.example"


def test_explicit_iss_is_not_overridden():
    cls = make_token_cls(issuer_url="https://issuer.example", expiration_seconds=3600)
    assert cls(sub="user-1", iss="https://other").iss == "https://other"


def test_raw_is_inaccessible_before_decode(token_cls):
    with pytest.raises(ValueError, match="only accessible for decoded"):
        _ = token_cls(sub="user-1").raw


def test_raw_exposes_decoded_claims(token_cls):
    decoded = token_cls.decode(token_cls(sub="user-1").encode())
    assert decoded.raw["sub"] == "user-1"


def test_encode_as_bearer(token_cls):
    bearer = token_cls(sub="user-1").encode_as_bearer()
    assert isinstance(bearer, BearerAccessToken)
    assert bearer.token_type == "bearer"  # noqa: S105  # nosec B105
    assert token_cls.decode(bearer.access_token).sub == "user-1"


def test_decode_enforces_issuer_claim():
    cls = make_token_cls(issuer_url="https://issuer.example", expiration_seconds=3600)
    forged = jwt.encode(
        {"alg": "HS256"},
        {"sub": "user-1", "iss": "https://attacker.example", "iat": utc_timestamp()},
        cls.jwt_config.get_key(),
    )
    with pytest.raises(InvalidClaimError):
        cls.decode(forged)


# --------------------------------------------------------------------------- #
# JoserfcTokenValidator
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_validator_accepts_valid_token(token_cls):
    validator = JoserfcTokenValidator(token_cls)
    token = await validator.validate(token_cls(sub="user-1").encode())
    assert token.sub == "user-1"


@pytest.mark.anyio
async def test_validator_rejects_bad_signature_as_unauthorized(token_cls):
    # token signed with a different key -> bad signature
    foreign = jwt.encode(
        {"alg": "HS256"},
        {"sub": "user-1", "iat": utc_timestamp()},
        jwk.OctKey.generate_key(256),
    )
    with pytest.raises(Unauthorized):
        await JoserfcTokenValidator(token_cls).validate(foreign)


@pytest.mark.anyio
async def test_validator_rejects_malformed_token_as_unauthorized(token_cls):
    with pytest.raises(Unauthorized):
        await JoserfcTokenValidator(token_cls).validate("not-a-jwt")


@pytest.mark.anyio
async def test_validator_rejects_missing_required_claim_as_unauthorized(token_cls):
    # `sub` is required by BaseJsonWebToken; omit it to trigger a ValidationError
    without_sub = jwt.encode(
        {"alg": "HS256"}, {"iat": utc_timestamp()}, token_cls.jwt_config.get_key()
    )
    with pytest.raises(Unauthorized) as exc_info:
        await JoserfcTokenValidator(token_cls).validate(without_sub)
    assert exc_info.value.as_model().errors


# --------------------------------------------------------------------------- #
# JWTAuth
# --------------------------------------------------------------------------- #


def test_create_access_token_is_decodable(jwt_auth, token_cls):
    bearer = jwt_auth.create_access_token(sub="user-1")
    assert isinstance(bearer, BearerAccessToken)
    assert token_cls.decode(bearer.access_token).sub == "user-1"


def test_get_jwks_returns_public_key_set(jwt_auth):
    assert "keys" in jwt_auth.get_jwks()


@pytest.mark.anyio
async def test_validate_token_rejects_missing_token(jwt_auth):
    with pytest.raises(Unauthorized, match="Not authenticated"):
        await jwt_auth.validate_token(None)


@pytest.mark.anyio
async def test_validate_token_accepts_valid_token(jwt_auth, token_cls):
    raw = token_cls(sub="user-1").encode()
    assert (await jwt_auth.validate_token(raw)).sub == "user-1"


def test_protected_router_appends_auth_dependency_and_responses(jwt_auth):
    router = jwt_auth.protected_router(ViewRouter)
    assert len(router.dependencies) == 1
    # router-level Unauthorized/Forbidden responses are documented
    assert 401 in router.responses
    assert 403 in router.responses


@pytest.mark.anyio
async def test_jwt_auth_endpoint_requires_token(jwt_auth, app, client):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return {"sub": token.sub}

    assert (await client.get("/me")).status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_jwt_auth_endpoint_accepts_valid_token(jwt_auth, app, client):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return {"sub": token.sub}

    bearer = jwt_auth.create_access_token(sub="user-1")
    response = await client.get(
        "/me", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"sub": "user-1"}


@pytest.mark.anyio
async def test_jwt_auth_endpoint_rejects_invalid_token(jwt_auth, app, client):
    @app.get("/me")
    async def me(token=jwt_auth.authenticated()):
        return {"sub": token.sub}

    response = await client.get(
        "/me", headers={"Authorization": "Bearer garbage.token.value"}
    )
    assert response.status_code == HTTP_401_UNAUTHORIZED


# --------------------------------------------------------------------------- #
# OAuth2 scopes
# --------------------------------------------------------------------------- #


def test_scopes_property_splits_space_delimited_scope(scope_token_cls):
    token = scope_token_cls(sub="user-1", scope="user:read post:edit")
    assert token.scopes == ["user:read", "post:edit"]


def test_scopes_property_empty_when_no_scope(scope_token_cls):
    assert scope_token_cls(sub="user-1").scopes == []


@pytest.mark.parametrize(
    ("required", "granted", "expected"),
    [
        ("user:read", ["user:read"], True),
        ("user:read", ["user:*"], True),  # wildcard action grants everything
        ("user:read", ["*:read"], True),  # wildcard resource
        ("user:read", ["user:edit"], True),  # edit implies read (hierarchy)
        ("user:edit", ["user:read"], False),  # read does not imply edit
        ("user:edit", ["user:*"], True),
        ("post:read", ["user:read"], False),  # different resource
        ("user:read", ["other:read", "user:edit"], True),  # any granted match
        ("user:read", [], False),
    ],
)
def test_has_scope(oauth, required, granted, expected):
    assert oauth.has_scope(required, granted) is expected


def test_resolve_action_includes_self_and_implied(oauth):
    # explicit hierarchy: edit implies read, all implies read+edit
    assert oauth._resolve_action("edit") == {"edit", "read"}
    assert oauth._resolve_action("*") == {"*", "read", "edit"}
    assert oauth._resolve_action("unknown") == {"unknown"}


@pytest.mark.anyio
async def test_oauth_endpoint_rejects_missing_token(oauth, app, client):
    @app.get("/items")
    async def items(token=oauth.requires("user:read")):
        return {"sub": token.sub}

    assert (await client.get("/items")).status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_oauth_endpoint_allows_sufficient_scope(oauth, app, client):
    @app.get("/items")
    async def items(token=oauth.requires("user:read")):
        return {"sub": token.sub}

    bearer = oauth.create_access_token(sub="user-1", scope="user:edit")
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"sub": "user-1"}


@pytest.mark.anyio
async def test_oauth_endpoint_forbids_insufficient_scope(oauth, app, client):
    @app.get("/items")
    async def items(token=oauth.requires("user:edit")):
        return {"sub": token.sub}

    bearer = oauth.create_access_token(sub="user-1", scope="user:read")
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_403_FORBIDDEN
    assert "user:edit" in response.json()["detail"]


def test_oauth_protected_router_with_scopes_adds_dependency(oauth):
    router = oauth.protected_router(ViewRouter, "user:read")
    assert len(router.dependencies) == 1
    assert 403 in router.responses


def test_oauth_protected_router_without_scopes_falls_back(oauth):
    router = oauth.protected_router(ViewRouter)
    assert len(router.dependencies) == 1
    assert 401 in router.responses


# --------------------------------------------------------------------------- #
# API key
# --------------------------------------------------------------------------- #


def test_require_api_key_is_cached():
    assert require_api_key("secret") is require_api_key("secret")
    assert require_api_key("secret") is not require_api_key("other")


@pytest.mark.anyio
async def test_api_key_accepts_valid_key(app, client):
    @app.get("/protected", dependencies=[Depends(require_api_key("the-secret"))])
    async def protected():
        return {"ok": True}

    response = await client.get("/protected", headers={"X-Api-Key": "the-secret"})
    assert response.status_code == HTTP_200_OK


@pytest.mark.anyio
async def test_api_key_rejects_missing_header(app, client):
    @app.get("/protected", dependencies=[Depends(require_api_key("the-secret"))])
    async def protected():
        return {"ok": True}

    response = await client.get("/protected")
    assert response.status_code == HTTP_401_UNAUTHORIZED
    assert "missing" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_api_key_rejects_wrong_key(app, client):
    @app.get("/protected", dependencies=[Depends(require_api_key("the-secret"))])
    async def protected():
        return {"ok": True}

    response = await client.get("/protected", headers={"X-Api-Key": "wrong"})
    assert response.status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_api_key_honors_custom_header_name(app, client):
    dependency = require_api_key("the-secret", name="Authorization-Key")

    @app.get("/protected", dependencies=[Depends(dependency)])
    async def protected():
        return {"ok": True}

    response = await client.get(
        "/protected", headers={"Authorization-Key": "the-secret"}
    )
    assert response.status_code == HTTP_200_OK


# --------------------------------------------------------------------------- #
# Auth0 validator
# --------------------------------------------------------------------------- #


try:
    from auth0_api_python.api_client import BaseAuthError

    from fastapi_views.security.auth0 import Auth0TokenValidator
except ImportError:
    pytest.skip("auth0-api-python is not installed", allow_module_level=True)


class _FakeAuthError(BaseAuthError):
    def get_error_code(self) -> str:
        return "invalid_token"

    def get_status_code(self) -> int:
        return HTTP_401_UNAUTHORIZED

    def get_headers(self) -> dict[str, str]:
        return {"WWW-Authenticate": "Bearer"}


@pytest.mark.anyio
async def test_auth0_validator_returns_token_from_verified_claims():
    token_model = make_token_cls(expiration_seconds=3600)
    api_client = AsyncMock()
    api_client.verify_access_token.return_value = {"sub": "auth0|123"}

    validator = Auth0TokenValidator(token_model, api_client=api_client)
    token = await validator.validate("any-token")

    assert token.sub == "auth0|123"
    api_client.verify_access_token.assert_awaited_once_with("any-token")


@pytest.mark.anyio
async def test_auth0_validator_maps_auth_error_to_api_error():
    token_model = make_token_cls(expiration_seconds=3600)
    api_client = AsyncMock()
    api_client.verify_access_token.side_effect = _FakeAuthError("token expired")

    validator = Auth0TokenValidator(token_model, api_client=api_client)
    with pytest.raises(APIError) as exc_info:
        await validator.validate("any-token")

    error = exc_info.value
    assert error.status_code == HTTP_401_UNAUTHORIZED
    assert error.as_model().detail == "token expired"


@pytest.mark.anyio
async def test_auth0_validator_maps_invalid_claims_to_unauthorized():
    token_model = make_token_cls(expiration_seconds=3600)
    api_client = AsyncMock()
    api_client.verify_access_token.return_value = {}  # missing required `sub`

    validator = Auth0TokenValidator(token_model, api_client=api_client)
    with pytest.raises(Unauthorized) as exc_info:
        await validator.validate("any-token")
    assert exc_info.value.as_model().errors
