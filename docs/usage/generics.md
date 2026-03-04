# Generic views

Generic views go one step further than ViewSets: they implement the actual CRUD logic for you, using the **repository pattern** to stay ORM-agnostic. You provide a `repository` object and a few schema classes, and the framework handles create, retrieve, update, partial update, delete, and paginated listing automatically.

---

## The repository protocol

Generic views communicate with your data layer through a simple protocol. Your repository object must implement the following async methods:

```python
class AsyncRepository(Protocol[M]):
    async def create(self, **kwargs) -> M | None: ...
    async def get(self, **kwargs) -> M | None: ...
    async def list(self, **kwargs) -> Sequence[M]: ...
    async def get_filtered_page(self, filter: BasePaginationFilter) -> Page[M]: ...
    async def update_one(self, values: dict, **kwargs) -> M | None: ...
    async def delete(self, **kwargs) -> None: ...
```

The synchronous `Repository` protocol is identical but without `async`.

Returning `None` from `create` raises `409 Conflict`. Returning `None` from `get` or `update_one` raises `404 Not Found`. You never need to raise these errors yourself.

---

## `AsyncGenericViewSet`

`AsyncGenericViewSet` combines all six CRUD actions into a single class. Configure it with class-level attributes:

| Attribute | Purpose |
|-----------|---------|
| `api_component_name` | Human-readable name used in OpenAPI |
| `primary_key` | Pydantic model whose fields become the URL path parameters |
| `response_schema` | Pydantic model used to serialize responses |
| `create_schema` | Pydantic model for the POST request body |
| `update_schema` | Pydantic model for the PUT request body |
| `partial_update_schema` | Pydantic model for the PATCH request body |
| `filter` | Filter class for the list action (see [Filters](filters.md)) |
| `repository` | Repository instance (sync or async) |

```python
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.generics import AsyncGenericViewSet, Page


# --- Schemas ---

class ItemId(BaseModel):
    id: UUID

class Item(ItemId):
    name: str

class CreateItem(BaseModel):
    name: str


# --- Repository ---

class ItemRepository:
    def __init__(self) -> None:
        self._data: dict[UUID, dict[str, Any]] = {}

    async def create(self, **kwargs: Any) -> dict[str, Any] | None:
        item_id = uuid4()
        kwargs["id"] = item_id
        self._data[item_id] = kwargs
        return kwargs

    async def get(self, **kwargs: Any) -> dict[str, Any] | None:
        return self._data.get(kwargs["id"])

    async def list(self) -> list[dict[str, Any]]:
        return list(self._data.values())

    async def get_filtered_page(self, filter) -> Page[dict[str, Any]]:
        raise NotImplementedError

    async def delete(self, **kwargs: Any) -> None:
        self._data.pop(kwargs["id"], None)

    async def update_one(
        self, values: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        item = self._data.get(kwargs["id"])
        if item is None:
            return None
        item.update(values)
        return item


# --- ViewSet ---

class ItemViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    partial_update_schema = CreateItem
    filter = None
    repository = ItemRepository()


# --- App ---

router = ViewRouter(prefix="/items")
router.register_view(ItemViewSet)

app = FastAPI(title="Example API")
app.include_router(router)
configure_app(app)
```

This registers the following routes:

| Method | Path | Action |
|--------|------|--------|
| GET | `/items` | list |
| POST | `/items` | create |
| GET | `/items/{id}` | retrieve |
| PUT | `/items/{id}` | update |
| PATCH | `/items/{id}` | partial update |
| DELETE | `/items/{id}` | destroy |

---

## Primary key model

The `primary_key` class defines the URL path parameters for detail routes. Any Pydantic model works — the most common pattern is a single `id` field:

```python
class ItemId(BaseModel):
    id: UUID
```

For composite keys, add more fields:

```python
class CompositeKey(BaseModel):
    tenant_id: UUID
    item_id: int
```

The framework calls `primary_key.model_dump()` and passes the result as keyword arguments to every repository method that handles a detail action.

---

## Lifecycle hooks

Every generic create and update action has `before_*` and `after_*` hooks so you can add custom logic without overriding the whole action:

```python
class ItemViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    partial_update_schema = CreateItem
    filter = None
    repository = ItemRepository()

    async def before_create(self, data: dict) -> None:
        # Runs after schema validation, before repository.create()
        data["created_by"] = self.request.state.user_id

    async def after_create(self, obj: Item) -> None:
        # Runs after repository.create() returns successfully
        await send_welcome_email(obj)

    async def before_update(self, data: dict) -> None:
        data["updated_by"] = self.request.state.user_id

    async def after_update(self, obj: Item) -> None:
        await invalidate_cache(obj.id)

    async def before_partial_update(self, data: dict) -> None:
        # data only contains fields that were actually sent in the request
        data["updated_by"] = self.request.state.user_id

    async def after_partial_update(self, obj: Item) -> None:
        await invalidate_cache(obj.id)
```

---

## Filters and pagination

Set the `filter` attribute to a filter class to enable filtering, sorting, searching, and pagination on the list endpoint. When a `PaginationFilter` (or subclass) is used, the list endpoint returns a `NumberedPage` instead of a plain list. With `TokenPaginationFilter`, it returns a `TokenPage`.

```python
from fastapi_views.filters.models import PaginationFilter

class ItemViewSet(AsyncGenericViewSet):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = CreateItem
    partial_update_schema = CreateItem
    filter = PaginationFilter   # list returns NumberedPage[Item]
    repository = ItemRepository()
```

Set `filter = None` to return a plain list without pagination or filtering.

See [Filters](filters.md) for how to build custom filter classes.

---

## Individual generic views

Use individual generic view classes when you do not need the full CRUD surface:

| Class | Action |
|-------|--------|
| `AsyncGenericListAPIView` | list |
| `AsyncGenericCreateAPIView` | create |
| `AsyncGenericRetrieveAPIView` | retrieve |
| `AsyncGenericUpdateAPIView` | update |
| `AsyncGenericPartialUpdateAPIView` | partial update |
| `AsyncGenericDestroyAPIView` | destroy |

```python
from abc import ABC
from fastapi_views.views.generics import (
    AsyncGenericListAPIView,
    AsyncGenericRetrieveAPIView,
)

class ItemReadViewSet(AsyncGenericListAPIView, AsyncGenericRetrieveAPIView, ABC):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    filter = None
    repository = ItemRepository()
```

All have synchronous counterparts without the `Async` prefix (e.g., `GenericViewSet`, `GenericListAPIView`).

---

## Complete example

```python
--8<-- "examples/generics.py"
```
