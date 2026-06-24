# Authentication

FastAPI Views ships a small, composable authentication layer built on top of FastAPI's
`Security` dependency system. It is built from two orthogonal pieces:

- a **scheme** (`AuthorizationScheme`) extracts the raw credential from the request — the
  `Authorization: Bearer <token>` header, an API-key header, a cookie, …
- an **`Auth`** turns that raw credential into a **principal** by implementing `verify()`

Concrete primitives compose those two:

- **`Auth`** — the base primitive: a scheme plus a presence check, returning the raw credential
- **`TokenAuth` / `ScopesAuth`** — bearer-token bases; `ScopesAuth` adds scope enforcement
- **`JWTAuth`** — verifies and issues JWTs (via `joserfc`), with scope support
- **`Auth0`** — verifies tokens with the `auth0-api-python` SDK
- **`APIKeyAuth`** — a header-based API-key scheme

A protected dependency resolves to the **decoded claims as a `dict[str, Any]`** — there is no
token model. Access claims by key (`token["sub"]`). Scope enforcement lives only on the
token-based auths, so an API key — which carries no scopes — never exposes a `requires` method.

The JWT pieces require the `jose` extra:

```bash
pip install "fastapi-views[jose]"
```

---

## Quick start

```python
from typing import Annotated, Any

from fastapi import FastAPI
from joserfc import jwk

from fastapi_views.auth.jwt import JWTAuth, JWTConfig

# Configure signing once, then build the auth.
key = jwk.OctKey.generate_key(256)
config = JWTConfig(key=key, algorithms=["HS256"], expiration_seconds=3600)
auth = JWTAuth(config, scheme=None)  # scheme=None → default HTTP Bearer

app = FastAPI()


@app.get("/me")
async def me(token: Annotated[dict[str, Any], auth.authenticated()]):
    return {"sub": token["sub"]}
```

`auth.authenticated()` returns a FastAPI `Security` dependency that resolves to the decoded
claims. A request without an `Authorization: Bearer <token>` header yields `401 Unauthorized`;
an invalid, malformed, or expired token also yields `401`.

---

## The principal is a claims dict

`verify()` returns the decoded claims as a plain `dict[str, Any]` — registered claims
(`iss`, `sub`, `iat`, `exp`, …) alongside any custom claims you signed into the token:

```python
@app.get("/me")
async def me(token: Annotated[dict[str, Any], auth.authenticated()]):
    return {"sub": token["sub"], "email": token.get("email")}
```

There is no schema validation step — if you need typed access or validation, parse the dict
into your own model inside the endpoint or a wrapping dependency (see
[Fetching a database user](#fetching-a-database-user-from-token-claims)).

---

## `JWTConfig`

`JWTConfig` holds everything needed to sign and verify tokens:

```python
from joserfc.jwt import JWTClaimsRegistry

config = JWTConfig(
    key=key,                            # joserfc key or KeySet
    algorithms=["HS256"],               # accepted algorithms
    issuer_url="https://example.com",   # marks `iss` essential + sets it on issue
    expiration_seconds=3600,            # default token lifetime → `exp` on issue
    claims_registry=JWTClaimsRegistry(
        aud={"essential": True, "value": "https://api.example.com"},
    ),
)
auth = JWTAuth(config, scheme=None)
```

When `issuer_url` is set, the `iss` claim is required on `verify()` and auto-populated on
`create_access_token()`. When `expiration_seconds` is set, `exp` is computed from `iat` at issue time.

---

## Issuing tokens

`JWTAuth.create_access_token(payload, expires_in=None)` signs a claims dict and returns a
`BearerAccessToken` (`token_type`, `access_token`, `expires_in`), ready to return from a
login route:

```python
from fastapi_views.auth.jwt import BearerAccessToken


@app.post("/token")
async def login() -> BearerAccessToken:
    # ... verify credentials ...
    return auth.create_access_token({"sub": "user-1", "scope": "items:read"})
```

`create_access_token` fills in sensible defaults with `setdefault`, so explicit values always win:

- `iat` is set to the current time
- `iss` is set from `config.issuer_url` (when configured)
- `exp` is set to `iat + expires_in`, where `expires_in` falls back to
  `config.expiration_seconds`

Pass `expires_in` to override the configured lifetime for a single token. It is also echoed
back on the returned model:

```python
bearer = auth.create_access_token({"sub": "user-1"}, expires_in=60)
assert bearer.expires_in == 60
```

---

## Verifying tokens

`await auth.verify(raw)` decodes the raw token with the configured key, runs the claims
registry, and returns the claims dict. Invalid signatures, malformed tokens, and failed
claims (expired, wrong issuer, …) all surface as `401 Unauthorized`:

```python
claims = await auth.verify(bearer.access_token)
assert claims["sub"] == "user-1"
```

You normally never call `verify` yourself — `authenticated()` and `requires()` call it for you.

### Asymmetric keys fetched at startup

For RS256/ES256 you typically fetch the issuer's JWKS on startup. `JWTAuth.fetch_jwks`
(requires `httpx`) downloads and imports the key set, using `config.issuer_url` as the base URL:

```python
from contextlib import asynccontextmanager

config = JWTConfig(algorithms=["RS256"], issuer_url="https://example.com")
auth = JWTAuth(config, scheme=None)


@asynccontextmanager
async def lifespan(app):
    await auth.fetch_jwks("/.well-known/jwks.json")
    yield


app = FastAPI(lifespan=lifespan)
```

---

## Publishing a JWKS endpoint

`config.jwks` returns the **public** key set (private material stripped), ready to serve at
`/.well-known/jwks.json`:

```python
@app.get("/.well-known/jwks.json")
async def jwks():
    return auth.config.jwks
```

---

## Scope enforcement

`JWTAuth` (and `Auth0`) are `ScopesAuth` subclasses, so scope checks are built in. Encode a
space-delimited `scope` claim when issuing the token:

```python
auth.encode({"sub": "user-1", "scope": "items:read items:write"})
```

### `requires(*scopes)`

Pass every scope an endpoint requires as positional arguments. The token must satisfy
**all** of them or the request is rejected with `403 Forbidden`:

```python
@app.get("/reports")
async def get_report(token: Annotated[dict, auth.requires("reports:read")]):
    ...


@app.post("/reports")
async def create_report(
    token: Annotated[dict, auth.requires("reports:read", "reports:write")],
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

### Scope validation

How a required scope is matched against a token's granted scopes is delegated to a
`ScopeValidator`. Two strategies ship out of the box:

- `HierarchicalScopeValidator` (the default) parses scopes into `resource:action` segments
  and resolves them hierarchically
- `SimpleScopeValidator` grants access only when the required scope is present verbatim
  among the granted scopes (a plain contains/equality check, with no `resource:action`
  structure assumed)

Select a strategy with the `scope_validator` argument:

```python
from fastapi_views.auth.scopes import SimpleScopeValidator

auth = JWTAuth(config, scope_validator=SimpleScopeValidator())
```

#### Hierarchical scopes

The default `HierarchicalScopeValidator` resolves scopes hierarchically:

- a wildcard action grants every action on a resource — `items:*` satisfies `items:read`
- a wildcard resource grants the action everywhere — `*:read` satisfies `items:read`
- the default action hierarchy is `edit` ⊃ `read` and `*` ⊃ `{read, edit}`, so a token
  with `items:edit` satisfies an `items:read` requirement

Customise the hierarchy by subclassing and overriding the `scope_hierarchy` class attribute
(mapping each action to the set of actions it implies):

```python
from fastapi_views.auth.scopes import HierarchicalScopeValidator


class MyScopeValidator(HierarchicalScopeValidator):
    scope_hierarchy = {
        "read": set(),
        "write": {"read"},
        "admin": {"read", "write"},
    }


auth = JWTAuth(config, scope_validator=MyScopeValidator())
```

Need entirely custom matching? Subclass `ScopeValidator` and implement `has_scope`:

```python
from collections.abc import Sequence

from fastapi_views.auth.scopes import Scope, ScopeValidator


class PrefixScopeValidator(ScopeValidator):
    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        return any(scope.startswith(granted) for granted in granted_scopes)
```

---

## Auth0

`Auth0` delegates verification to the `auth0-api-python` SDK (install with the `auth0`
extra). It is itself a `ScopesAuth`, so `authenticated()` and `requires()` work the same way;
`verify()` returns Auth0's verified claims dict:

```python
from auth0_api_python.api_client import ApiClient

from fastapi_views.auth.auth0 import Auth0

api_client = ApiClient(
    domain="your-tenant.auth0.com",
    audience="https://api.example.com",
)
auth = Auth0(api_client)  # scheme defaults to HTTP Bearer
```

Errors from the SDK are mapped to the matching `APIError` (status, title, headers); invalid
tokens surface as `401 Unauthorized`.

---

## API key authentication

`APIKeyAuth` reads an API key from a request header (default `X-Api-Key`). When the header is
missing the request is rejected with `401 Unauthorized` (`{"detail": "Invalid API Key"}`);
otherwise the dependency resolves to the **raw key**, leaving validation to you:

```python
from typing import Annotated

from fastapi import FastAPI

from fastapi_views.auth.api_key import APIKeyAuth
from fastapi_views.exceptions import Unauthorized

api_auth = APIKeyAuth()

app = FastAPI()


@app.get("/ping")
async def ping(key: Annotated[str, api_auth.authenticated()]):
    if not is_valid_api_key(key):  # your own lookup / constant-time compare
        raise Unauthorized("Invalid API Key")
    return {"pong": True}
```

Customise the header name and OpenAPI metadata:

```python
APIKeyAuth(name="Authorization-Key", description="Service key")
```

---

## Custom authentication

Subclass `ScopesAuth` and implement `verify()` to integrate any backend while keeping scope
enforcement. Return a claims dict (with a `scope` claim if you want scopes), or raise an
`APIError`:

```python
from typing import Any

from fastapi_views.auth.abc import ScopesAuth
from fastapi_views.exceptions import Unauthorized


class MyAuth(ScopesAuth):
    async def verify(self, raw: str) -> dict[str, Any]:
        claims = await my_verify(raw)
        if claims is None:
            raise Unauthorized("Invalid token")
        return claims
```

For a non-bearer credential, pass a custom scheme — any callable (sync or async) returning
`str | None` works as an `AuthorizationScheme`:

```python
from fastapi import Cookie


def cookie_scheme(session: str | None = Cookie(default=None)) -> str | None:
    return session


auth = JWTAuth(config, scheme=cookie_scheme)
```

If you don't need scopes at all, subclass `Auth` directly — it has no `requires` method.

---

## Fetching a database user from token claims

Token claims are often not enough — you may need the full database record. Wrap the auth
dependency in a factory that returns a `Depends`, then declare reusable `Annotated` aliases
for each access level:

```python
from typing import Annotated

from fastapi import Depends


def get_current_user(*scopes: str):
    def _dependency(token: Annotated[dict[str, Any], auth.requires(*scopes)]):
        return get_user_from_database(user_id=token["sub"])

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

Protect every route under a prefix by attaching the auth dependency at the router level:

```python
from fastapi import FastAPI

from fastapi_views import ViewRouter, configure_app

# Require a valid token for all routes
router = ViewRouter(prefix="/items", dependencies=[auth.authenticated()])

# ...or additionally require scopes for all routes
router = ViewRouter(prefix="/items", dependencies=[auth.requires("items:read")])

router.register_view(ItemViewSet)

app = FastAPI()
app.include_router(router)
configure_app(app)
```

The same dependencies work on individual routes via the standard FastAPI `dependencies=[...]`
argument or as an `Annotated` parameter.
