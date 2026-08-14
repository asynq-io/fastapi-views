# Permissions

FastAPI Views ships a DRF-inspired authorization layer on top of the
[authentication](auth.md) system. It is built from two pieces:

- **your principal model** — the typed identity the auth dependency resolves and
  publishes on `request.scope["principal"]`. You define it (a pydantic model with
  `permissions: list[str]` and whatever typed fields you need); anonymous is `None`.
  No framework base class, no `identity: str`, no `kind` discriminator.
- **permission classes** — sync `has_permission(principal, view)` and
  `has_object_permission(principal, view, obj)` checks, composable with `&` (AND),
  `|` (OR) and `~` (NOT). Classes and instances compose interchangeably.

```python
from fastapi_views.permissions import (
    AllowAny,
    Authenticated,
    CurrentUser,
    HasPermissions,
    IsAdmin,
    IsAdminOrOwner,
    IsAuthenticated,
    IsOwner,
    Principal,
)
```

`Authenticated` is the typed-injection dependency (`Authenticated[User]`);
`IsAuthenticated` is the permission used in `permission_classes`.

---

## Quick start

Register the app-wide auth object with `configure_app`, before or after the
routers that use `permission_classes` — the auth is bound to the app itself, so
either order works and two apps in one process keep their own auth:

```python
from fastapi import FastAPI
from joserfc import jwk

from fastapi_views import configure_app
from fastapi_views.auth.jwt import JWTAuth, JWTConfig

auth = JWTAuth(
    JWTConfig(key=jwk.OctKey.generate_key(256), algorithms=["HS256"]),
    custom_class=make_user,  # builds your User from the decoded claims
)

app = FastAPI()
configure_app(app, auth=auth)  # or set_app_auth(auth) for a process-wide default
```

A view normally declares **only** `permission_classes` and inherits the app-wide
auth; set `auth` on the class to enforce a different one (a separate trust
domain), which takes precedence over both the app-wide and process-wide auth:

```python
from fastapi_views.permissions import IsAuthenticated, HasPermissions
from fastapi_views.views import AsyncAPIViewSet


class DocumentViewSet(AsyncAPIViewSet):
    api_component_name = "Document"
    response_schema = DocumentSchema
    permission_classes = [IsAuthenticated & HasPermissions("read:documents")]
    ...
```

`has_permission` runs before every action. `has_object_permission` runs on `retrieve`,
once the object is fetched — mutating actions have no object in hand, so for those see
[object-level permissions on generic views](#object-level-permissions-on-generic-views).
A failing check raises `401 Unauthorized` when the principal is `None`, otherwise
`403 Forbidden`.

---

## The principal is your model

`Principal` is a typing-only `Protocol` — the structural contract your model
satisfies:

```python
class Principal(Protocol):
    permissions: Sequence[str]
```

You write the model and plug it in via the auth's existing `custom_class`:

```python
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: UUID = Field(alias="sub")
    org_id: UUID | None = None
    permissions: list[str] = Field(default_factory=list)


def make_user(token: dict) -> User:
    return User(
        user_id=UUID(token["sub"]),
        permissions=token.get("scope", "").split(),
    )

auth = JWTAuth(config, custom_class=make_user)
```

`is_authenticated` is **implied by non-`None`** — the model is only built when a
credential verifies — so `IsAuthenticated` is just `principal is not None`. Using
the permission system therefore requires `custom_class` (so the dependency returns an
object with `.permissions`); without it the dependency returns the raw credential and
only the auth's own `authenticated()` / `requires()` apply.

---

## Typed principal injection (`Authenticated[T]`)

Narrow the principal to your own type — e.g. to guarantee `org_id` is present and
typed:

```python
from fastapi_views.permissions import Authenticated


@app.get("/me", dependencies=[Security(auth.resolve_dependency)])
async def me(user: Authenticated[User]) -> dict[str, str]:
    return {"id": str(user.user_id), "org": str(user.org_id)}
```

`Authenticated[User]` expands to `Annotated[User, Depends(resolver)]`. The resolver
reads `request.scope["principal"]`, raises `401` when it is `None`, then coerces it
into `User` in this order:

1. an existing instance of `User` (the auth already returns one via `custom_class`) —
   returned as-is;
2. a `User.from_principal(principal)` classmethod — full control over the mapping;
3. a pydantic model → `User.model_validate(principal)` (use field aliases to map
   claims, e.g. `user_id: UUID = Field(alias="sub")`);
4. the constructor.

A coercion failure surfaces as `403 Forbidden` — the caller authenticated but
doesn't satisfy the required type. A token missing `org_id` therefore can't satisfy
`Authenticated[User]`, which is how you make `org_id` **required**.

!!! note
    With `from __future__ import annotations` (stringified annotations), the typed
    class must be resolvable from the endpoint's module globals — define it at module
    level, not inside the endpoint function. The same applies to the resolved
    principal: declare it where FastAPI builds the route signature.

`CurrentUser` injects the resolved principal as-is (raises `401` when anonymous):

```python
from fastapi_views.permissions import CurrentUser


@app.get("/me", dependencies=[Security(auth.resolve_dependency)])
async def me(principal: CurrentUser) -> dict[str, Any]:
    return {"perms": list(principal.permissions)}
```

On **views** the framework wires the auth dependency for you (see below), so
`Authenticated[User]` / `CurrentUser` in a view method need no extra `dependencies`.

---

## Users and machines (IoT devices)

Discriminate principal types by **type-fit**, not a string tag. Give each a
required field the other lacks, and use a union where both are accepted:

```python
class User(BaseModel):
    user_id: UUID = Field(alias="sub")
    org_id: UUID  # required


class Device(BaseModel):
    device_id: UUID = Field(alias="sub")


@app.get("/actor", dependencies=[Security(auth.resolve_dependency)])
async def actor(principal: Authenticated[User | Device]) -> dict[str, Any]: ...
```

`Authenticated[User]` rejects a token without `org_id` with `403`; `Authenticated[Device]`
rejects one without a fitting shape; the union returns whichever member validates.
Permissions (`HasPermissions`, `IsOwner`, …) read `principal.permissions` / typed
attrs, so they work for every principal type.

---

## Permission classes

Both hooks are **sync** and take the resolved `principal` (your model or `None`),
not the request:

```python
from fastapi_views.permissions import BasePermission


class IsOwner(BasePermission):
    def has_object_permission(self, principal, view, obj) -> bool:
        return getattr(obj, "owner_id", None) == getattr(principal, "user_id", None)
```

Compose with `&`, `|`, `~`:

```python
IsAuthenticated & HasPermissions("read:documents")
HasPermissions("read:docs") & IsOwner("user_id", "owner_id")
IsAdmin | IsOwner()
~IsAuthenticated
```

Both `IsAuthenticated` (a class) and `IsOwner()` (an instance) compose.

### Built-in permissions

| Class | `has_permission` | `has_object_permission` |
| --- | --- | --- |
| `AllowAny` | `True` | `True` |
| `IsAuthenticated` | `principal is not None` | `True` |
| `HasPermissions(*perms)` (alias `HasScopes`) | all `perms` ⊆ `principal.permissions` | `True` |
| `IsOwner(principal_attr, obj_attr)` | `True` | `getattr(obj, obj_attr) == getattr(principal, principal_attr)` |
| `IsAdmin(admin_permission="admin")` | admin perm present | admin perm present |
| `IsAdminOrOwner(...)` | `IsAdmin` | `IsAdmin` ∨ `IsOwner` |
| `IsAuthenticatedOrReadOnly` | authenticated OR `GET`/`HEAD` | `True` |

---

## Using permissions with views

Set `permission_classes` on an `APIView` / viewset; `check_permissions` runs before
each action and `check_object_permissions` runs after the object is fetched:

```python
from typing import ClassVar
from fastapi_views.permissions import IsAdmin, IsAdminOrOwner


class UserViewSet(AsyncAPIViewSet):
    response_schema = UserSchema
    permission_classes: ClassVar = [IsAdmin]

    action_permission_classes: ClassVar = {
        "retrieve": [IsAdminOrOwner("user_id", "owner_id")],
        "update": [IsAdminOrOwner("user_id", "owner_id")],
        "partial_update": [IsAdminOrOwner("user_id", "owner_id")],
    }
```

Override `get_permissions(self)` to branch on `self.action` dynamically.

### Object-level permissions on generic views

The generic views in `fastapi_views.views.generics` write straight through the
repository, so `update` / `partial_update` / `destroy` never hold the row and there is
nothing to pass to `has_object_permission`. `fastapi_views.permissions.views` provides
drop-in subclasses that fetch the target first and authorize it *before* the write:

```python
from typing import ClassVar
from fastapi_views.permissions import IsAdminOrOwner
from fastapi_views.permissions.views import AsyncProtectedGenericViewSet


class DocumentViewSet(AsyncProtectedGenericViewSet):
    api_component_name = "Document"
    primary_key = DocumentId
    response_schema = DocumentSchema
    update_schema = UpdateDocument
    partial_update_schema = UpdateDocument
    repository = document_repository
    permission_classes: ClassVar = [IsAdminOrOwner("admin", "user_id", "owner_id")]
```

| Class | Wraps |
| --- | --- |
| `ProtectedGenericUpdateAPIView` / `AsyncProtectedGenericUpdateAPIView` | `GenericUpdateAPIView` |
| `ProtectedGenericPartialUpdateAPIView` / `Async…` | `GenericPartialUpdateAPIView` |
| `ProtectedGenericDestroyAPIView` / `Async…` | `GenericDestroyAPIView` |
| `ProtectedGenericViewSet` / `AsyncProtectedGenericViewSet` | `GenericViewSet` |

A missing row raises `404 Not Found` (subject to `raise_on_none`) and a failing check
raises `403` / `401` before anything is written. When a view configures no permissions
the extra fetch is skipped, so these views cost the same as the plain generics.

`ObjectPermissionsMixin` / `AsyncObjectPermissionsMixin` expose the
`authorize_object(*args, **kwargs)` hook if you want the same behaviour on a view of
your own.

### OpenAPI security scopes and the Authorize button

For any non-`AllowAny` action the framework wires
`Security(auth.resolve_dependency, scopes=<derived>)` as a route dependency, where the
scopes are aggregated from `HasPermissions(...)` in `permission_classes`. FastAPI then
documents the security scheme and the **per-endpoint required scopes**, and the Swagger
**Authorize** button works:

```python
class DocumentViewSet(AsyncAPIViewSet):
    permission_classes = [IsAuthenticated & HasPermissions("read:documents")]
    # -> OpenAPI: security: [{Bearer: ["read:documents"]}]
```

`401` and `403` are documented automatically on routes that have permissions
configured. `AllowAny`-only routes get no security scheme.

---

## Auth integration

The auth dependency publishes the principal on `request.scope["principal"]` — one
key, one writer. Two dependencies exist on every `AuthBase`:

- `auth.dependency` (via `auth.authenticated()` / `auth.requires(*scopes)`) — the
  **raising** one: `401` on a missing/invalid credential, scope validation for
  `ScopesAuth`. Use it directly on plain routes.
- `auth.resolve_dependency` — the **non-raising** one the permission bridge wires:
  it resolves the principal (or `None`) and lets the permission classes decide
  `401` vs `403`.

`AutoScopesAuthView` derives per-action scopes from `action_scopes` and enforces
them with `requires(scope)` on its `auth`, falling back to the app-wide auth when
the class declares none.

When a view is registered before any auth is known, the route carries a deferred
security dependency that `configure_app(app, auth=auth)` binds to that app — so
the scheme still shows up in OpenAPI, and a route whose app was never configured
fails closed instead of running unprotected.

### Plain routes

For a route that isn't a view, wire the dependency yourself so the principal is
published before `Authenticated[T]` / `CurrentUser` read it:

```python
from fastapi import Security

@app.get("/me", dependencies=[Security(auth.resolve_dependency)])
async def me(user: Authenticated[User]) -> dict[str, str]: ...
```
