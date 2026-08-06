# ViewSets

A ViewSet bundles multiple related CRUD actions into a single class. Instead of writing five separate functions and wiring them to five separate routes, you write one class with five methods and register it once.

---

## `AsyncAPIViewSet`

`AsyncAPIViewSet` is the main async ViewSet. It combines all five standard CRUD actions:

| Method | Action | HTTP | Path | Status |
|--------|--------|------|------|--------|
| `list` | List all resources | GET | `/items` | 200 |
| `create` | Create a new resource | POST | `/items` | 201 |
| `retrieve` | Fetch a single resource | GET | `/items/{id}` | 200 |
| `update` | Replace a resource | PUT | `/items/{id}` | 200 |
| `destroy` | Delete a resource | DELETE | `/items/{id}` | 204 |

(Paths shown for a router registered with `prefix="/items"`; the detail suffix comes from `detail_route`, `"/{id}"` by default.)

```python
from typing import ClassVar, Optional
from uuid import UUID

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.viewsets import AsyncAPIViewSet


class UpdateItemSchema(BaseModel):
    name: str
    price: int


class ItemSchema(BaseModel):
    id: UUID
    name: str
    price: int


class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    items: ClassVar[dict[UUID, ItemSchema]] = {}

    async def list(self) -> list[ItemSchema]:
        return list(self.items.values())

    async def create(self, item: ItemSchema) -> ItemSchema:
        self.items[item.id] = item
        return item

    async def retrieve(self, id: UUID) -> Optional[ItemSchema]:
        return self.items.get(id)  # None → 404 Not Found automatically

    async def update(self, id: UUID, item: UpdateItemSchema) -> ItemSchema:
        self.items[id] = ItemSchema(id=id, **item.model_dump())
        return self.items[id]

    async def destroy(self, id: UUID) -> None:
        self.items.pop(id, None)


router = ViewRouter(prefix="/items")
router.register_view(ItemViewSet)

app = FastAPI(title="Items API")
app.include_router(router)
configure_app(app)
```

### `api_component_name`

This string is used to:

1. Build human-readable route names shown in the OpenAPI UI (e.g., "List Item", "Create Item").
2. Build stable OpenAPI operation IDs (e.g., `list_item`, `create_item`, `retrieve_item`).

Setting it explicitly is recommended so that generated clients get predictable method names.

### `response_schema`

The Pydantic model used to serialize and validate every response body. The `list` action automatically wraps this in `list[response_schema]` (set `response_schema_as_list = False` to opt out, e.g. when `list` returns an envelope).

Override the `get_response_schema(action)` classmethod when a single action needs a different schema.

---

## Partial ViewSets

You do not need to expose all five actions. Use a pre-built combination class or compose your own from individual mixins.

### Pre-built combinations

| Class | Actions |
|-------|---------|
| `AsyncReadOnlyAPIViewSet` | `list`, `retrieve` |
| `AsyncListCreateAPIViewSet` | `list`, `create` |
| `AsyncRetrieveUpdateAPIViewSet` | `retrieve`, `update` |
| `AsyncRetrieveUpdateDestroyAPIViewSet` | `retrieve`, `update`, `destroy` |
| `AsyncListRetrieveUpdateDestroyAPIViewSet` | `list`, `retrieve`, `update`, `destroy` |
| `AsyncListCreateDestroyAPIViewSet` | `list`, `create`, `destroy` |

All have synchronous counterparts without the `Async` prefix.

```python
from fastapi_views.views.viewsets import AsyncReadOnlyAPIViewSet

class ItemReadOnlyViewSet(AsyncReadOnlyAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema

    async def list(self) -> list[ItemSchema]:
        return list(items.values())

    async def retrieve(self, id: UUID) -> Optional[ItemSchema]:
        return items.get(id)
```

### Custom combination with `partial_update`

`AsyncAPIViewSet` does not include `partial_update` (PATCH) by default. To add it, inherit from the individual mixins directly:

```python
from abc import ABC
from fastapi_views.views.api import (
    AsyncListAPIView,
    AsyncCreateAPIView,
    AsyncRetrieveAPIView,
    AsyncPartialUpdateAPIView,
    AsyncDestroyAPIView,
)

class MyViewSet(
    AsyncListAPIView,
    AsyncCreateAPIView,
    AsyncRetrieveAPIView,
    AsyncPartialUpdateAPIView,
    AsyncDestroyAPIView,
    ABC,
):
    api_component_name = "Item"
    response_schema = ItemSchema

    async def list(self) -> list[ItemSchema]: ...
    async def create(self, item: ItemSchema) -> ItemSchema: ...
    async def retrieve(self, id: UUID) -> Optional[ItemSchema]: ...
    async def partial_update(self, id: UUID, item: ItemSchema) -> ItemSchema: ...
    async def destroy(self, id: UUID) -> None: ...
```

---

## Adding custom routes

Use the `@get`, `@post`, `@put`, `@patch`, or `@delete` decorators inside any ViewSet to add non-standard endpoints. These work alongside the standard CRUD actions:

```python
from collections.abc import Sequence
from uuid import uuid4
from fastapi_views.views.functools import get, post

class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    items: ClassVar[dict[UUID, ItemSchema]] = {}

    async def list(self) -> list[ItemSchema]:
        return list(self.items.values())

    # ... other standard actions ...

    @get("/search")
    async def search(self, name: str) -> Sequence[ItemSchema]:
        return [i for i in self.items.values() if name.lower() in i.name.lower()]

    @post("/{id}/duplicate")
    async def duplicate(self, id: UUID) -> ItemSchema:
        original = self.items[id]
        new_item = ItemSchema(
            id=uuid4(),
            name=f"Copy of {original.name}",
            price=original.price,
        )
        self.items[new_item.id] = new_item
        return new_item
```

The return annotation is what gets documented and serialized, so an explicit `response_model=` is only needed when the two differ.

!!! note
    A `list` action shadows the `list` builtin inside the class body, so annotations
    on *later* methods cannot use `list[...]` — use `Sequence[...]` (or a module-level
    alias) as above.

---

## Custom actions with `@action`

`@action` is a higher-level alternative to the raw HTTP decorators, modelled on Django REST Framework. It adds a few conveniences on top of `@route`:

- **Default path** — the path defaults to the hyphenated method name, so `@action(methods=["GET"])` on `stats` becomes `GET /stats`.
- **Detail routes** — `detail=True` nests the route under the view's detail route, e.g. `POST /{id}/publish` (a custom `detail_route = "/{uuid}"` is honoured).
- **Response headers** — `response_headers=` (a `ResponseHeaders` subclass) documents headers on the success response.

The response model is taken from an explicit `response_model=` if given, otherwise from the method's return annotation, and finally from the view's `response_schema`. A `Response` subclass appearing in the annotation is ignored, so `-> Item | Response` still documents `Item`.

Static routes are always registered before parameterized ones, so a collection action like `/stats` is never shadowed by `retrieve`'s `/{id}`.

```python
from uuid import UUID
from fastapi_views.models import ResponseHeaders
from fastapi_views.views.functools import action


class LocationHeaders(ResponseHeaders):
    location: str


class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema

    # ... standard CRUD actions ...

    # GET /items/stats — documented with ItemStats (the return annotation would
    # be used anyway; an explicit response_model wins).
    @action(methods=["GET"], response_model=ItemStats)
    async def stats(self) -> ItemStats:
        ...

    # POST /items/{id}/publish — nested under the detail route, with a
    # documented Location header.
    @action(methods=["POST"], detail=True, response_headers=LocationHeaders)
    async def publish(self, id: UUID) -> ItemSchema:
        self.response.headers["location"] = f"/items/{id}"
        ...
```

A full runnable example lives in [`examples/actions.py`](https://github.com/asynq-io/fastapi-views/blob/main/examples/actions.py):

```python
--8<-- "examples/actions.py"
```

---

## Overriding route options of standard actions

Standard CRUD actions have no decorator of their own, so route options are set with `@override` (an alias of `@annotate`). It accepts any FastAPI route argument — `status_code`, `path`, `summary`, `responses`, `dependencies`, `response_headers`, …:

```python
from fastapi_views.views.functools import override
from starlette.status import HTTP_200_OK

class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema

    @override(status_code=HTTP_200_OK, summary="Upsert an item")
    async def create(self, item: ItemSchema) -> ItemSchema:
        # Returns 200 instead of the default 201
        ...
```

`@override` replaces the metadata of the method it decorates, so use a single call per method rather than stacking it with `@throws` or a route decorator.

---

## Documenting error responses

Declare which errors a ViewSet may return by setting `errors` on the class. They are automatically included in the OpenAPI spec for all routes on that ViewSet:

```python
from fastapi_views.exceptions import Conflict, Forbidden
from fastapi_views.views.viewsets import AsyncAPIViewSet

class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    errors = (Forbidden, Conflict)

    async def retrieve(self, id: UUID) -> Optional[ItemSchema]:
        return items.get(id)
```

On top of `errors`, every route documents `default_errors` (`BadRequest`), and each action adds what it can raise on its own: `NotFound` for `retrieve` / `update`, `Conflict` for `create`. Use `@throws(...)` on a single action to document extra errors for that route only — see [Basic usage](basic.md#documenting-errors-in-openapi).

---

## Per-action dependencies

`action_dependencies` maps action names to route-level dependencies, so each generated route gets only the dependencies that belong to it:

```python
from typing import ClassVar

from fastapi import Depends

class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    action_dependencies: ClassVar = {
        "list": [Depends(require_reader)],
        "create": [Depends(require_editor)],
        "destroy": [Depends(require_admin)],
    }
```

Dependencies passed to `register_view(..., dependencies=[...])` are merged with these (router-level first), and `get_dependencies(action)` can be overridden for dynamic behaviour. See [Authentication](auth.md#per-action-dependencies) for scope enforcement.

---

## Documenting response headers

Besides `response_headers=` on a single `@action`, a ViewSet can declare headers per action by overriding `get_response_headers`:

```python
from fastapi_views.models import ResponseHeaders


class PaginationHeaders(ResponseHeaders):
    x_total_count: int


class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema

    @classmethod
    def get_response_headers(cls, action=None):
        return PaginationHeaders if action == "list" else None
```

`ViewRouter(prefix="/items", response_headers=...)` applies a header model to every route it registers.

---

## Sync ViewSet

Replace every `Async` prefix with the synchronous variant when your handlers are not coroutines:

```python
from fastapi_views.views.viewsets import APIViewSet

class SyncItemViewSet(APIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema

    def list(self) -> list[ItemSchema]:
        return list(items.values())

    def retrieve(self, id: UUID) -> Optional[ItemSchema]:
        return items.get(id)

    def create(self, item: ItemSchema) -> ItemSchema:
        items[item.id] = item
        return item

    def update(self, id: UUID, item: ItemSchema) -> ItemSchema:
        items[id] = item
        return item

    def destroy(self, id: UUID) -> None:
        items.pop(id, None)
```

Starlette runs synchronous endpoint functions in a thread pool, so they are safe to use alongside async middleware and dependencies.

---

## Complete example

```python
--8<-- "examples/viewset.py"
```
