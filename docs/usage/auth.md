# Authentication

FastAPI Views ships a small, composable authentication layer built on top of FastAPI's
`Security` dependency system. It is built from two orthogonal pieces:

- a **scheme** (`AuthorizationScheme`) extracts the raw credential from the request — the
  `Authorization: Bearer <token>` header, an API-key header, a cookie, …
- an **auth object** turns that raw credential into a **principal** — by verifying it (`verify()`)
  and/or wrapping it (`wrap_token()`)

Concrete primitives compose those two:

- **`AuthBase`** — the base primitive: a scheme plus a presence check, returning the raw credential
- **`TokenAuth` / `ScopesAuth`** — bearer-token bases; `TokenAuth` adds the `Bearer` challenge and
  `custom_class` wrapping, `ScopesAuth` adds `verify()` plus scope enforcement
- **`JWTAuth`** — verifies and issues JWTs (via `joserfc`), with scope support
- **`Auth0`** — verifies tokens with the `auth0-api-python` SDK
- **`APIKeyAuth` / `ConstAPIKeyAuth`** — header-based API-key schemes
- **`AutoScopesAuthView`** — a view mixin that derives the required scope from the action

`fastapi_views.auth` re-exports the pieces that don't need an optional dependency:

```python
from fastapi_views.auth import (
    All,
    APIKeyAuth,
    AuthBase,
    AuthorizationScheme,
    AutoScopesAuthView,
    ConstAPIKeyAuth,
    Delete,
    Edit,
    HierarchicalScopeValidator,
    Read,
    Scope,
    ScopeValidator,
    ScopesAuth,
    SimpleScopeValidator,
    TokenAuth,
)
```

`TokenAuth` and `ScopesAuth` are defined in `fastapi_views.auth.abc` and the scope pieces
(`Scope`, the validators, and the `All` / `Delete` / `Edit` / `Read` action constants) in
`fastapi_views.auth.scopes`; both modules remain importable directly, so existing
`from fastapi_views.auth.abc import ScopesAuth` imports keep working.

`JWTAuth` (`fastapi_views.auth.jwt`) and `Auth0` (`fastapi_views.integrations.auth0`) are
deliberately **not** re-exported: they import `joserfc` and `auth0-api-python` at module level,
so re-exporting them would make a plain `import fastapi_views.auth` fail for anyone who has not
installed the optional `jose` / `auth0` extras.

A protected dependency resolves to the **decoded claims as a `dict[str, Any]`** — there is no
token model. Access claims by key (`token["sub"]`). Pass a `custom_class` (or override
`wrap_token`) to get something else — see
[Wrapping the principal in your own type](#wrapping-the-principal-in-your-own-type). Scope
enforcement lives only on the token-based auths, so an API key — which carries no scopes — never
exposes a `requires` method.

The JWT pieces require the `jose` extra (`joserfc`), the Auth0 integration the `auth0` extra
(`auth0-api-python`):

```bash
pip install "fastapi-views[jose]"
pip install "fastapi-views[auth0]"
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

The full signature is
`JWTAuth(config, scheme=None, custom_class=None, scope_validator=None)`; only `config` is
required. Leaving `scheme` as `None` installs a non-erroring `HTTPBearer` scheme, so the `401`
comes from the auth object (as an `APIError`) rather than from FastAPI.

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

All fields, with their defaults:

| Field | Default | Purpose |
| --- | --- | --- |
| `key` | `None` | `joserfc` key or `KeySet`; `get_key()` raises `ValueError` while unset |
| `key_type` | `None` | `"oct" \| "RSA" \| "EC" \| "OKP"`, used by `import_key` |
| `issuer_url` | `""` | Marks `iss` essential and is used as the base URL for `fetch_jwks` |
| `header` | `{}` | JWS/JWE header used when encoding |
| `algorithms` | `None` | Accepted algorithms |
| `claims_registry` | `JWTClaimsRegistry(now=utc_timestamp, leeway=10)` | Claim validation on `verify()` |
| `encoder_cls` / `decoder_cls` | `None` | Custom JSON encoder/decoder classes |
| `registry` | `None` | `JWSRegistry` or `JWERegistry` |
| `default_type` | `None` | Default token type passed to `jwt.encode` |
| `expiration_seconds` | `None` | Default token lifetime → `exp` on issue |

When `issuer_url` is set, the `iss` claim is required on `verify()` and auto-populated on
`create_access_token()`. When `expiration_seconds` is set, `exp` is computed from `iat` at issue time.
When exactly one algorithm is given and `header` has no `alg`, `header["alg"]` is filled in for you.

`config.import_key(data, parameters=None)` imports a key from a serialized form — a JWKS
document (any mapping containing `"keys"`) becomes a `KeySet`, anything else is imported as a
single key using `key_type`.

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
    return auth.create_access_token({"sub": "user-1", "scope": "read:items"})
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

For RS256/ES256 you typically fetch the issuer's JWKS on startup.
`await auth.fetch_jwks(url, **kwargs)` (requires `httpx`, otherwise `ImportError`) downloads and
imports the key set, using `config.issuer_url` as the base URL and forwarding `kwargs` to the
`GET` request:

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

`JWTAuth.jwks` returns the **public** key set (private material stripped), ready to serve at
`/.well-known/jwks.json`. A single key is wrapped in a `{"keys": [...]}` document; a `KeySet` is
serialized as-is:

```python
@app.get("/.well-known/jwks.json")
async def jwks():
    return auth.jwks
```

The serialization is memoized against the identity of the key currently on the config, so
repeated reads are cheap, while a **key rotation** — `await auth.fetch_jwks(...)` or
`config.import_key(...)` — is picked up on the next read with no cache invalidation on your side.
Reading `auth.jwks` before any key has been loaded raises `ValueError("Key not initialized")`.

---

## Scope enforcement

`JWTAuth` (and `Auth0`) are `ScopesAuth` subclasses, so scope checks are built in. Encode a
space-delimited `scope` claim when issuing the token:

```python
auth.encode({"sub": "user-1", "scope": "read:items edit:items"})
```

`ScopesAuth.get_granted_scopes(token)` reads that claim, splitting it on arbitrary whitespace; a
missing or empty `scope` claim yields an **empty** list, so a scopeless token satisfies nothing.
Override the method if your tokens carry scopes elsewhere (this is exactly what the Auth0
integration does).

### `requires(*scopes)`

Pass every scope an endpoint requires as positional arguments. The token must satisfy
**all** of them or the request is rejected with `403 Forbidden`:

```python
@app.get("/reports")
async def get_report(token: Annotated[dict[str, Any], auth.requires("read:reports")]):
    ...


@app.post("/reports")
async def create_report(
    token: Annotated[dict[str, Any], auth.requires("read:reports", "edit:reports")],
):
    ...
```

`requires(*scopes)` is just `Security(self.dependency, scopes=scopes)`, so it works anywhere a
FastAPI dependency does: as an `Annotated` marker, in `dependencies=[...]`, or as a parameter
default. A missing scope produces the standard problem-details body:

```json
{
  "type": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.3",
  "title": "Forbidden",
  "status": 403,
  "detail": "Token is missing required scope: edit:reports"
}
```

Scopes follow the `action:resource` pattern (e.g. `read:items`, `*:orders`), matching the
shape of Auth0 permissions. `Scope` is an annotated `str` (stripped, 1–2048 characters) and the
default action names are available as constants:

```python
from fastapi_views.auth import All, Delete, Edit, Read

# Read == "read", Edit == "edit", Delete == "delete", All == "*"
```

### Scope validation

How a required scope is matched against a token's granted scopes is delegated to a
`ScopeValidator`. Two strategies ship out of the box:

- `HierarchicalScopeValidator` (the default) parses scopes into `action:resource` segments
  and resolves them hierarchically
- `SimpleScopeValidator` grants access only when the required scope is present verbatim
  among the granted scopes (a plain contains/equality check, with no `action:resource`
  structure assumed)

Select a strategy with the `scope_validator` argument:

```python
from fastapi_views.auth.scopes import SimpleScopeValidator

auth = JWTAuth(config, scope_validator=SimpleScopeValidator())
```

#### Hierarchical scopes

The default `HierarchicalScopeValidator` resolves scopes hierarchically:

- a wildcard action grants every action on a resource — `*:items` satisfies `read:items`
- a wildcard resource grants the action everywhere — `read:*` satisfies `read:items`
- the default action hierarchy is `edit` ⊃ `read`, `delete` ⊃ `read` and
  `*` ⊃ `{read, edit, delete}`, so a token with `edit:items` satisfies a `read:items`
  requirement

Customise the hierarchy by subclassing and overriding the `scope_hierarchy` class attribute
(mapping each action to the set of actions it implies):

```python
from typing import ClassVar

from fastapi_views.auth.scopes import HierarchicalScopeValidator


class MyScopeValidator(HierarchicalScopeValidator):
    scope_hierarchy: ClassVar[dict[str, set[str]]] = {
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

!!! note
    `granted_scopes` is an empty sequence for a token without a `scope` claim — never `[""]`.
    A deliberately permissive validator like the one above therefore cannot be tricked into
    matching every scope by a scopeless token.

---

## Auth0

`Auth0` delegates verification to the `auth0-api-python` SDK (install with the `auth0`
extra). It is itself a `ScopesAuth`, so `authenticated()` and `requires()` work the same way;
`verify()` returns Auth0's verified claims dict:

```python
from auth0_api_python import ApiClient, ApiClientOptions

from fastapi_views.integrations.auth0 import Auth0

api_client = ApiClient(
    ApiClientOptions(
        domain="your-tenant.auth0.com",
        audience="https://api.example.com",
    )
)
auth = Auth0(api_client)  # scheme defaults to HTTP Bearer
```

Errors from the SDK are mapped to the matching `APIError` (status, title, detail and headers
taken from the SDK error); invalid tokens surface as `401 Unauthorized`.

Auth0 exposes authorization data in two different places depending on tenant configuration:
the space-delimited `scope` claim, or a `permissions` list when RBAC "Add Permissions in the
Access Token" is enabled. Select which one to read with `permission_key`:

```python
auth = Auth0(api_client, permission_key="permissions")
```

Both string (`"read:items edit:items"`) and list (`["read:items"]`) claim shapes are handled.
The full signature is
`Auth0(api_client, scheme=None, scope_validator=None, custom_class=None, permission_key="scope")`.

A runnable end-to-end example lives in
[`examples/auth0.py`](https://github.com/asynq-io/fastapi-views/blob/main/examples/auth0.py).

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
APIKeyAuth(name="Authorization-Key", scheme_name="ServiceKey", description="Service key")
```

### `ConstAPIKeyAuth`

When a single static key is enough, `ConstAPIKeyAuth` does the comparison for you using
`secrets.compare_digest` (constant time), rejecting a missing or mismatched key with
`401 Unauthorized`:

```python
from fastapi_views.auth import ConstAPIKeyAuth

api_auth = ConstAPIKeyAuth(settings.api_key, name="X-Api-Key")


@app.get("/ping")
async def ping(key: Annotated[str, api_auth.authenticated()]):
    return {"pong": True}
```

---

## Unauthorized responses

A missing or rejected credential is raised as an `Unauthorized` `APIError`, so it renders as a
problem-details body. Every primitive supplies a meaningful `detail` and, where a challenge
applies, the matching `WWW-Authenticate` header:

| Raised by | `detail` | `WWW-Authenticate` |
| --- | --- | --- |
| `AuthBase.unauthorized()` | `Missing or invalid credentials` | — |
| `TokenAuth.unauthorized()` (inherited by `ScopesAuth`, `JWTAuth`, `Auth0`) | `Missing or invalid bearer token` | `Bearer` |
| `APIKeyAuth.unauthorized()` (and `ConstAPIKeyAuth`) | `Invalid API Key` | `APIKey` |
| `JWTAuth.verify()` on an invalid token | the underlying `joserfc` error message | `Bearer` |
| `Auth0.verify()` on an invalid token | the SDK's error description | forwarded from the SDK |

A request to a bearer-protected route with no `Authorization` header therefore gets:

```json
{
  "type": "https://datatracker.ietf.org/doc/html/rfc7235#section-3.1",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Missing or invalid bearer token"
}
```

The challenge value comes from the `TokenAuth.challenge` class variable, `"Bearer"` by default as
[RFC 6750](https://datatracker.ietf.org/doc/html/rfc6750#section-3) requires. Override it in a
subclass that authenticates with something other than a bearer token — a session cookie, say — so
the `401` advertises the right scheme:

```python
from typing import ClassVar

from fastapi_views.auth import TokenAuth


class SessionAuth(TokenAuth):
    challenge: ClassVar[str] = 'Cookie realm="app"'
```

Override `unauthorized()` itself when you need a different detail, status, or extra headers.

---

## Custom authentication

Subclass `ScopesAuth` and implement `verify()` to integrate any backend while keeping scope
enforcement. Return a claims dict (with a `scope` claim if you want scopes), or raise an
`APIError`:

```python
from typing import Any

from fastapi_views.auth import ScopesAuth
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

If you don't need scopes at all, subclass `AuthBase` (for an opaque credential of any kind) or
`TokenAuth` (for a bearer-shaped one) — neither exposes a `requires` method. Two hooks cover
almost every customisation:

- **`unauthorized()`** — the `401` raised when the credential is absent or rejected (this is how
  `APIKeyAuth` adds its `WWW-Authenticate: APIKey` header)
- **`wrap_token(token)`** — turns the credential into the principal handed to the endpoint;
  it is the identity function on `AuthBase`, and on `TokenAuth` it applies `custom_class`

Prefer overriding `wrap_token` to overriding `get_dependency()`: the dependency is built once in
`__init__` and already handles the `with_test_user` short-circuit and, on `ScopesAuth`, scope
validation.

### Wrapping the principal in your own type

`TokenAuth` and its subclasses (`ScopesAuth`, `JWTAuth`, `Auth0`) accept a `custom_class`
callable, which `wrap_token` applies to the credential that survived verification. The dependency
then resolves to whatever it returns:

```python
from pydantic import BaseModel


class Principal(BaseModel):
    sub: str
    scope: str = ""


auth = JWTAuth(config, custom_class=Principal.model_validate)


@app.get("/me")
async def me(principal: Annotated[Principal, auth.authenticated()]):
    return {"sub": principal.sub}
```

What the callable receives depends on the class it is configured on:

- on `ScopesAuth`, `JWTAuth` and `Auth0` — the **verified claims dict**, *after* scope validation
- on a plain `TokenAuth` — the **raw credential string**, since there is no `verify()` step to
  turn it into claims

`custom_class` is typed `Callable[[Any], Any]`, so any one-argument callable works: a Pydantic
`model_validate`, a dataclass, a lambda, a lookup function. When you need more than that, override
`wrap_token` instead:

```python
from typing import Any


class TenantAuth(JWTAuth):
    def wrap_token(self, token: Any) -> Principal:
        return Principal(sub=token["sub"], scope=token.get("scope", ""))
```

A `with_test_user` value is returned exactly as given and never goes through `wrap_token`, so a
test principal doesn't have to satisfy your wrapper.

---

## Testing protected routes

`AuthBase.with_test_user(user)` is a context manager that short-circuits the dependency and
returns `user` for every request made inside it — no signing, no headers, no
`dependency_overrides`. It is reset on exit, including when the body raises:

```python
async def test_me(client, auth):
    with auth.with_test_user({"sub": "tester"}):
        response = await client.get("/me")
    assert response.json() == {"sub": "tester"}
```

The override applies before scope validation too, so a test user is never rejected by
`requires(...)`, and the value is handed to the endpoint verbatim — `wrap_token` / `custom_class`
are skipped. Any falsy-but-not-`None` value (e.g. `{}`) still counts as a test user.

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
EditorUser = Annotated[UserModel, get_current_user("edit:documents")]


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
router = ViewRouter(prefix="/items", dependencies=[auth.requires("read:items")])

router.register_view(ItemViewSet)

app = FastAPI()
app.include_router(router)
configure_app(app)
```

The same dependencies work on individual routes via the standard FastAPI `dependencies=[...]`
argument or as an `Annotated` parameter.

### Per-action dependencies

When different actions need different requirements, set `action_dependencies` on the
view class — e.g. different scopes for reads and writes:

```python
from typing import ClassVar

from fastapi_views.views.generics import AsyncGenericViewSet


class ItemViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    ...
    action_dependencies: ClassVar = {
        "list": [auth.requires("read:items")],
        "retrieve": [auth.requires("read:items")],
        "create": [auth.requires("edit:items")],
        "update": [auth.requires("edit:items")],
        "partial_update": [auth.requires("edit:items")],
        "destroy": [auth.requires("delete:items")],
    }
```

Bulk views support the same attribute with the `bulk_create`, `bulk_update`,
`update_many` and `bulk_delete` actions. Per-action dependencies compose with `dependencies=[...]`
passed to `ViewRouter(...)` or `register_view(...)`, and can be computed dynamically
by overriding `get_dependencies(action)` instead.

### `AutoScopesAuthView` — derive the scope from the action

Spelling out `action_dependencies` for every view gets repetitive when scopes follow the
`action:resource` convention. Mix `AutoScopesAuthView` in and it builds the required scope for
you from the action, using its `action_scopes` mapping:

```python
from typing import ClassVar

from fastapi_views.auth import AutoScopesAuthView
from fastapi_views.views.viewsets import AsyncAPIViewSet


class ItemViewSet(AutoScopesAuthView, AsyncAPIViewSet):
    auth = auth
    resource = "items"
    api_component_name = "Item"
    response_schema = ItemSchema
    ...
```

`list`/`retrieve` now require `read:items`, `create`/`update`/`partial_update` require
`edit:items`, and `destroy` requires `delete:items`.

Two class attributes drive it:

- **`auth`** — the `ScopesAuth` instance to enforce with (required)
- **`resource`** — the resource half of the scope; defaults to `None`, in which case
  `get_name()` is used (i.e. `api_component_name`, falling back to the class name)

The default `action_scopes` mapping is:

| Scope prefix | Actions |
| --- | --- |
| `read` | `list`, `retrieve`, `events` |
| `edit` | `create`, `update`, `partial_update`, `bulk_create`, `bulk_update`, `update_many` |
| `delete` | `destroy`, `bulk_delete` |

Registering a custom action that isn't in the mapping raises `LookupError` at route-build
time — a deliberate fail-fast so a new endpoint can never ship unprotected. Extend the mapping
to cover it:

```python
class ItemViewSet(AutoScopesAuthView, AsyncAPIViewSet):
    auth = auth
    resource = "items"
    action_scopes: ClassVar = {**AutoScopesAuthView.action_scopes, "publish": "edit"}
```

`AutoScopesAuthView` also widens `default_errors` to `(BadRequest, Unauthorized, Forbidden)`, so
`401` and `403` are documented on every generated route. Any `action_dependencies` you declare
are appended after the generated scope dependency.
