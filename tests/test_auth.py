from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from joserfc import jwk, jwt
from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)

from fastapi_views.auth.api_key import APIKeyAuth
from fastapi_views.auth.jwt import (
    BearerAccessToken,
    JWTAuth,
    JWTConfig,
    utc_timestamp,
)
from fastapi_views.exceptions import APIError, Unauthorized
from fastapi_views.handlers import add_error_handlers

# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# JWTAuth.create_access_token / encode
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# JWTAuth.verify
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Scopes
# --------------------------------------------------------------------------- #


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
def test_has_scope(jwt_auth, required, granted, expected):
    assert jwt_auth.has_scope(required, granted) is expected


def test_resolve_action_includes_self_and_implied(jwt_auth):
    # explicit hierarchy: edit implies read, all implies read+edit
    assert jwt_auth._resolve_action("edit") == {"edit", "read"}
    assert jwt_auth._resolve_action("*") == {"*", "read", "edit"}
    assert jwt_auth._resolve_action("unknown") == {"unknown"}


# --------------------------------------------------------------------------- #
# JWTAuth endpoints
# --------------------------------------------------------------------------- #


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
    async def items(token=jwt_auth.requires("user:read")):
        return {"sub": token["sub"]}

    assert (await client.get("/items")).status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_endpoint_allows_sufficient_scope(jwt_auth, app, client):
    @app.get("/items")
    async def items(token=jwt_auth.requires("user:read")):
        return {"sub": token["sub"]}

    bearer = jwt_auth.create_access_token({"sub": "user-1", "scope": "user:edit"})
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_200_OK
    assert response.json() == {"sub": "user-1"}


@pytest.mark.anyio
async def test_endpoint_forbids_insufficient_scope(jwt_auth, app, client):
    @app.get("/items")
    async def items(token=jwt_auth.requires("user:edit")):
        return {"sub": token["sub"]}

    bearer = jwt_auth.create_access_token({"sub": "user-1", "scope": "user:read"})
    response = await client.get(
        "/items", headers={"Authorization": f"Bearer {bearer.access_token}"}
    )
    assert response.status_code == HTTP_403_FORBIDDEN
    assert "user:edit" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# API key
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Auth0
# --------------------------------------------------------------------------- #


try:
    from auth0_api_python.api_client import BaseAuthError

    from fastapi_views.auth.auth0 import Auth0

    HAS_AUTH0 = True
except ImportError:
    HAS_AUTH0 = False

auth0_required = pytest.mark.skipif(
    not HAS_AUTH0, reason="auth0-api-python is not installed"
)


if HAS_AUTH0:

    class _FakeAuthError(BaseAuthError):
        def get_error_code(self) -> str:
            return "invalid_token"

        def get_status_code(self) -> int:
            return HTTP_401_UNAUTHORIZED

        def get_headers(self) -> dict[str, str]:
            return {"WWW-Authenticate": "Bearer"}


@auth0_required
@pytest.mark.anyio
async def test_auth0_verify_returns_verified_claims():
    api_client = AsyncMock()
    api_client.verify_access_token.return_value = {"sub": "auth0|123"}

    auth = Auth0(api_client)
    claims = await auth.verify("any-token")

    assert claims["sub"] == "auth0|123"
    api_client.verify_access_token.assert_awaited_once_with("any-token")


@auth0_required
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
