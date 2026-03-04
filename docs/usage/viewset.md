# ViewSets

A ViewSet bundles multiple related CRUD actions into a single class. Instead of writing five separate functions and wiring them to five separate routes, you write one class with five methods and register it once.

---

## `AsyncAPIViewSet`

`AsyncAPIViewSet` is the main async ViewSet. It combines all five standard CRUD actions:

| Method | Action | HTTP | Path | Status |
|--------|--------|------|------|--------|
| `list` | List all resources | GET | `/` | 200 |
| `create` | Create a new resource | POST | `/` | 201 |
| `retrieve` | Fetch a single resource | GET | `/{id}` | 200 |
| `update` | Replace a resource | PUT | `/{id}` | 200 |
| `destroy` | Delete a resource | DELETE | `/{id}` | 204 |

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

The Pydantic model used to serialize and validate every response body. The `list` action automatically wraps this in `list[response_schema]`.

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
from uuid import uuid4
from fastapi_views.views.functools import get, post

class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    items: ClassVar[dict[UUID, ItemSchema]] = {}

    async def list(self) -> list[ItemSchema]:
        return list(self.items.values())

    # ... other standard actions ...

    @get("/search", response_model=list[ItemSchema])
    async def search(self, name: str) -> list[ItemSchema]:
        return [i for i in self.items.values() if name.lower() in i.name.lower()]

    @post("/{id}/duplicate", status_code=201)
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

---

## Overriding default status codes

Override the default status code for any action using the `@override` decorator:

```python
from fastapi_views.views.functools import override
from starlette.status import HTTP_200_OK

class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema

    @override(status_code=HTTP_200_OK)
    async def create(self, item: ItemSchema) -> ItemSchema:
        # Returns 200 instead of the default 201
        ...
```

---

## Documenting error responses

Declare which errors an action may return by setting `errors` on the class. They are automatically included in the OpenAPI spec for all routes on that ViewSet:

```python
from fastapi_views.exceptions import NotFound, Conflict
from fastapi_views.views.viewsets import AsyncAPIViewSet

class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    errors = (NotFound, Conflict)

    async def retrieve(self, id: UUID) -> Optional[ItemSchema]:
        return items.get(id)
```

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
