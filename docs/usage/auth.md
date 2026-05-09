# Authentication

FastAPI Views ships a lightweight JWT authentication layer built on top of FastAPI's
`Security` dependency system.  It handles token extraction, validation, and scope
enforcement with three composable pieces:

- **`TokenValidator`** — validates a raw bearer token and returns decoded claims
- **`Auth`** — wires a validator into reusable FastAPI `Security` dependencies
- **`ScopeValidator`** — controls how token scopes are compared against route requirements

---

## Quick start

```python
from typing import Annotated
from fastapi import FastAPI
from fastapi_views.security import Auth
from fastapi_views.security.user import User
from fastapi_views.security.validators.joserfc import JoserfcTokenValidator
from joserfc import jwk

key = jwk.OctKey.import_key({"kty": "oct", "k": "<base64url-secret>"})
validator = JoserfcTokenValidator(key=key)
auth = Auth(validator, tokenUrl="/token")

app = FastAPI()

@app.get("/me")
async def me(user: Annotated[User, auth.authenticated()]):
    return {"id": user.id, "scopes": user.scopes}
```

`auth.authenticated()` returns a FastAPI `Security` dependency.  When a request
arrives without a valid `Authorization: Bearer <token>` header the response is
`401 Unauthorized`; with an invalid or expired token the validator raises the
appropriate error.

---

## Token validators

### `JoserfcTokenValidator`

Use this for any standard JWT flow (HS256, RS256, ES256, …).  Pass a `joserfc` key or
key-set at construction time, or set it later via `init_key` — useful when the JWKS
must be fetched asynchronously on startup.

```python
from joserfc import jwk, jwt
from fastapi_views.security.validators.joserfc import JoserfcTokenValidator

# HS256 shared secret
key = jwk.OctKey.import_key({"kty": "oct", "k": "<base64url-secret>"})
validator = JoserfcTokenValidator(key=key)

# RS256 — key fetched at startup
validator = JoserfcTokenValidator()

async def lifespan(app):
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://example.com/.well-known/jwks.json")
    validator.init_key(jwk.KeySet.import_key_set(resp.json()))
    yield
```

Pass a custom `JWTClaimsRegistry` to enforce standard claims:

```python
from joserfc.jwt import JWTClaimsRegistry

registry = JWTClaimsRegistry(
    iss={"essential": True, "value": "https://example.com"},
    aud={"essential": True, "values": ["https://api.example.com"]},
)
validator = JoserfcTokenValidator(key=key, claims_registry=registry)
```

### `Auth0TokenValidator`

Delegates verification to the `auth0-api-python` SDK:

```python
from auth0_api_python.api_client import ApiClient
from fastapi_views.security.validators.auth0 import Auth0TokenValidator

api_client = ApiClient(
    domain="your-tenant.auth0.com",
    audience="https://api.example.com",
)
validator = Auth0TokenValidator(api_client=api_client)
auth = Auth(validator, tokenUrl="https://your-tenant.auth0.com/oauth/token")
```

### Custom validator

Subclass `TokenValidator` to integrate any backend:

```python
from typing import Any
from fastapi_views.security.validators import TokenValidator
from fastapi_views.exceptions import Unauthorized

class MyTokenValidator(TokenValidator):
    async def validate(self, token: str) -> dict[str, Any]:
        claims = await my_verify(token)
        if claims is None:
            raise Unauthorized("Invalid token")
        return claims
```

---

## Scope enforcement

### `requires(*scopes)`

Pass all scopes an endpoint requires as positional arguments.  The token must contain
**every** listed scope or the request is rejected with `403 Forbidden`.

```python
from typing import Annotated
from fastapi_views.security.user import User

@app.get("/reports")
async def get_report(user: Annotated[User, auth.requires("reports:read")]):
    ...

@app.post("/reports")
async def create_report(user: Annotated[User, auth.requires("reports:read", "reports:write")]):
    ...
```

A missing scope produces:

```json
{
  "status": 403,
  "title": "insufficient_scopes",
  "detail": "Token is missing required scope: reports:write"
}
```

Scopes must follow the `resource:action` pattern (e.g. `items:read`, `orders:*`).

### `SimpleScopeValidator` (default)

Requires an exact match — the scope string must be present verbatim in the token's
`scope` claim.  This is the default and requires no configuration.

### `AdvancedScopeValidator`

Adds hierarchical action inheritance: `edit` implies `read`, and `*` implies both.

```python
from fastapi_views.security import Auth
from fastapi_views.security.scopes import AdvancedScopeValidator

auth = Auth(validator, scope_validator=AdvancedScopeValidator(), tokenUrl="/token")
```

With this validator a token with `items:edit` satisfies an `items:read` requirement,
and `items:*` satisfies all actions on the `items` resource.

You can supply a custom hierarchy:

```python
AdvancedScopeValidator(scope_hierarhy={
    "read": set(),
    "write": {"read"},
    "admin": {"read", "write"},
})
```

---

## Custom user model

By default the resolved dependency returns a `User` instance populated from the JWT
claims (`sub` → `id`, `scope` → `scopes`).  Pass any Pydantic model as `user_model`
to include additional claims:

```python
from pydantic import Field
from fastapi_views.security.user import User

class MyUser(User):
    org_id: str = Field(validation_alias="org_id")
    roles: list[str] = Field(default_factory=list)

auth = Auth(validator, user_model=MyUser, tokenUrl="/token")
```

---

## Fetching the user from a database

Token claims alone are often not enough — you may need the full database record.
Build a factory that wraps `auth.requires` and returns a `Depends`, then declare
reusable `Annotated` aliases for each access level:

```python
from typing import Annotated
from fastapi import Depends
from fastapi_views.security.user import User

def get_current_user(*scopes: str):
    def _dependency(token_user: Annotated[User, auth.requires(*scopes)]):
        return get_user_from_database(user_id=token_user.id)
    return Depends(_dependency)

# Reusable aliases
CurrentUser = Annotated[UserModel, get_current_user()]
EditorUser  = Annotated[UserModel, get_current_user("documents:edit")]

@app.get("/me")
async def me(user: CurrentUser):
    return {"id": user.id}

@app.put("/documents/{id}")
async def update_document(id: int, user: EditorUser):
    ...
```

---

## Using `Auth` with `ViewRouter`

Protect all routes under a prefix at the router level:

```python
from fastapi import FastAPI
from fastapi_views import ViewRouter, configure_app

router = ViewRouter(
    prefix="/items",
    dependencies=[auth.authenticated()],
)
router.register_view(ItemViewSet)

app = FastAPI()
app.include_router(router)
configure_app(app)
```
