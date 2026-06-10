# Authentication

FastAPI Views ships a lightweight JWT authentication layer built on top of FastAPI's
`Security` dependency system. It handles token extraction, validation, and scope
enforcement with a few composable pieces:

- **`BaseJsonWebToken`** — a Pydantic model describing your token claims, configured
  with a `JWTConfig` (signing key, algorithms, claims registry, …)
- **`TokenValidator`** — validates a raw bearer token and returns a decoded token model
- **`JWTAuth`** — wires a validator into reusable FastAPI `Security` dependencies
- **`OAuth2JWTAuth`** — extends `JWTAuth` with scope enforcement
- **`require_api_key`** — a standalone API-key header dependency

A protected dependency returns the **decoded token model instance** — there is no
separate user object. To carry extra data, subclass the token model.

The JWT pieces require the `joserfc` extra:

```bash
pip install "fastapi-views[jose]"
```

---

## Quick start

```python
from typing import Annotated

from fastapi import FastAPI
from joserfc import jwk

from fastapi_views.security import BaseJsonWebToken, JWTAuth
from fastapi_views.security.jwt import JWTConfig
from fastapi_views.security.validator import JoserfcTokenValidator


class AccessToken(BaseJsonWebToken):
    pass


# Configure the token model once with its signing key.
key = jwk.OctKey.import_key({"kty": "oct", "k": "<base64url-secret>"})
AccessToken.configure(JWTConfig(key=key, algorithms=["HS256"], expiration_seconds=3600))

auth = JWTAuth(JoserfcTokenValidator(AccessToken))

app = FastAPI()


@app.get("/me")
async def me(token: Annotated[AccessToken, auth.authenticated()]):
    return {"sub": token.sub}
```

`auth.authenticated()` returns a FastAPI `Security` dependency that resolves to the
decoded `AccessToken`. When a request arrives without an `Authorization: Bearer <token>`
header the response is `401 Unauthorized`; an invalid, malformed, or expired token also
yields `401`.

---

## The token model

Every token is a subclass of `BaseJsonWebToken` (itself a Pydantic model). It defines
the registered claims (`iss`, `sub`, `iat`, and a computed `exp`) and is configured with
a `JWTConfig` via `configure()` before use.

### Adding custom claims

Subclass the token model and declare extra fields — they are encoded into and validated
out of the JWT automatically:

```python
class AccessToken(BaseJsonWebToken):
    email: str | None = None
    org_id: str | None = None


@app.get("/me")
async def me(token: Annotated[AccessToken, auth.authenticated()]):
    return {"sub": token.sub, "email": token.email, "org": token.org_id}
```

### Issuing tokens

`JWTAuth.create_access_token(**claims)` builds and signs a token, returning a
`BearerAccessToken` (`token_type` + `access_token`) ready to return from a login route:

```python
from fastapi_views.security.jwt import BearerAccessToken


@app.post("/token")
async def login() -> BearerAccessToken:
    # ... verify credentials ...
    return auth.create_access_token(sub="user-1", email="a@b.com")
```

You can also encode/decode directly from the model:

```python
bearer = AccessToken(sub="user-1").encode_as_bearer()
claims = AccessToken.decode(bearer.access_token)
```

### `JWTConfig`

`JWTConfig` holds everything needed to sign and verify tokens:

```python
from joserfc.jwt import JWTClaimsRegistry

config = JWTConfig(
    key=key,                       # joserfc key or KeySet
    algorithms=["HS256"],          # accepted algorithms
    issuer_url="https://example.com",  # marks the `iss` claim essential + sets it on issue
    expiration_seconds=3600,       # populates the computed `exp` claim
    claims_registry=JWTClaimsRegistry(
        aud={"essential": True, "value": "https://api.example.com"},
    ),
)
AccessToken.configure(config)
```

When `issuer_url` is set, the `iss` claim is required on decode and auto-populated on
issue. When `expiration_seconds` is set, `exp` is computed from `iat`.

---

## Token validators

### `JoserfcTokenValidator`

Use this for any standard JWT flow (HS256, RS256, ES256, …). It decodes the raw token
with the model's configured key and returns the validated model. Invalid signatures,
malformed tokens, failed claims, and schema-validation errors all surface as
`401 Unauthorized`.

```python
from fastapi_views.security.validator import JoserfcTokenValidator

validator = JoserfcTokenValidator(AccessToken)
```

#### Asymmetric keys fetched at startup

For RS256/ES256 you typically fetch the issuer's JWKS on startup. `JWTConfig.fetch_jwks`
(requires `httpx`) downloads and imports a key set; `import_key` imports a single key:

```python
from contextlib import asynccontextmanager

AccessToken.configure(
    JWTConfig(algorithms=["RS256"], issuer_url="https://example.com")
)


@asynccontextmanager
async def lifespan(app):
    await AccessToken.jwt_config.fetch_jwks("/.well-known/jwks.json")
    yield


app = FastAPI(lifespan=lifespan)
```

### `Auth0TokenValidator`

Delegates verification to the `auth0-api-python` SDK (install with the `auth0` extra).
The model is validated from Auth0's verified claims:

```python
from auth0_api_python.api_client import ApiClient

from fastapi_views.security.auth0 import Auth0TokenValidator

api_client = ApiClient(
    domain="your-tenant.auth0.com",
    audience="https://api.example.com",
)
validator = Auth0TokenValidator(AccessToken, api_client)
auth = JWTAuth(validator)
```

### Custom validator

Subclass `TokenValidator` to integrate any backend. It is generic over the token model
passed to its constructor:

```python
from typing import Any

from fastapi_views.security.validator import TokenValidator
from fastapi_views.exceptions import Unauthorized


class MyTokenValidator(TokenValidator):
    async def validate(self, token: str) -> Any:
        claims = await my_verify(token)
        if claims is None:
            raise Unauthorized("Invalid token")
        return self.token_model.model_validate(claims)
```

---

## Publishing a JWKS endpoint

`JWTAuth.get_jwks()` returns the **public** key set for the configured token model
(private material is stripped), ready to serve at `/.well-known/jwks.json`:

```python
@app.get("/.well-known/jwks.json")
async def jwks():
    return auth.get_jwks()
```

---

## Scope enforcement

Scope support lives in `OAuth2JWTAuth`, which pairs with `ScopesJsonWebToken` (a token
model with a space-delimited `scope` claim exposed as a `scopes` list).

```python
from typing import Annotated

from fastapi_views.security import OAuth2JWTAuth, ScopesJsonWebToken
from fastapi_views.security.jwt import JWTConfig
from fastapi_views.security.validator import JoserfcTokenValidator


class AccessToken(ScopesJsonWebToken):
    pass


AccessToken.configure(JWTConfig(key=key, algorithms=["HS256"], expiration_seconds=3600))
auth = OAuth2JWTAuth(JoserfcTokenValidator(AccessToken))
```

### `requires(*scopes)`

Pass every scope an endpoint requires as positional arguments. The token must satisfy
**all** of them or the request is rejected with `403 Forbidden`.

```python
@app.get("/reports")
async def get_report(token: Annotated[AccessToken, auth.requires("reports:read")]):
    ...


@app.post("/reports")
async def create_report(
    token: Annotated[AccessToken, auth.requires("reports:read", "reports:write")],
):
    ...
```

A missing scope produces:

```json
{
  "status": 403,
  "title": "Forbidden",
  "detail": "Token is missing required scope: reports:write"
}
```

Scopes follow the `resource:action` pattern (e.g. `items:read`, `orders:*`).

### Scope hierarchy

`OAuth2JWTAuth` resolves scopes hierarchically out of the box:

- a wildcard action grants every action on a resource — `items:*` satisfies `items:read`
- a wildcard resource grants the action everywhere — `*:read` satisfies `items:read`
- the default action hierarchy is `edit` ⊃ `read` and `*` ⊃ `{read, edit}`, so a token
  with `items:edit` satisfies an `items:read` requirement

Customise the hierarchy by subclassing and overriding the `scope_hierarhy` class
attribute (mapping each action to the set of actions it implies):

```python
class MyAuth(OAuth2JWTAuth):
    scope_hierarhy = {
        "read": set(),
        "write": {"read"},
        "admin": {"read", "write"},
    }


auth = MyAuth(JoserfcTokenValidator(AccessToken))
```

---

## API key authentication

`require_api_key` builds a header-based API-key dependency. It reads the `X-Api-Key`
header by default and compares it with the expected value in constant time, raising
`401 Unauthorized` when the header is missing or wrong.

```python
from fastapi import Depends, FastAPI

from fastapi_views.security import require_api_key

app = FastAPI()


@app.get("/ping", dependencies=[Depends(require_api_key("my-secret-key"))])
async def ping():
    return {"pong": True}
```

Customise the header name (and OpenAPI metadata):

```python
require_api_key("my-secret-key", name="Authorization-Key", description="Service key")
```

---

## Fetching a database user from token claims

Token claims are often not enough — you may need the full database record. Wrap the auth
dependency in a factory that returns a `Depends`, then declare reusable `Annotated`
aliases for each access level:

```python
from typing import Annotated

from fastapi import Depends


def get_current_user(*scopes: str):
    def _dependency(token: Annotated[AccessToken, auth.requires(*scopes)]):
        return get_user_from_database(user_id=token.sub)

    return Depends(_dependency)


# Reusable aliases
CurrentUser = Annotated[UserModel, get_current_user()]
EditorUser = Annotated[UserModel, get_current_user("documents:edit")]


@app.get("/me")
async def me(user: CurrentUser):
    return {"id": user.id}


@app.put("/documents/{id}")
async def update_document(id: int, user: EditorUser):
    ...
```

---

## Using auth with `ViewRouter`

Protect every route under a prefix at the router level with `protected_router`, which
attaches the auth dependency and documents the `401`/`403` responses for you:

```python
from fastapi import FastAPI

from fastapi_views import ViewRouter, configure_app

# JWTAuth — requires a valid token for all routes
router = auth.protected_router(ViewRouter, prefix="/items")

# OAuth2JWTAuth — additionally require scopes for all routes
router = auth.protected_router(ViewRouter, "items:read", prefix="/items")

router.register_view(ItemViewSet)

app = FastAPI()
app.include_router(router)
configure_app(app)
```

You can also pass the dependency directly to any router or route:

```python
router = ViewRouter(prefix="/items", dependencies=[auth.authenticated()])
```
