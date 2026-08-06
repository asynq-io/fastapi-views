# Generic views

Generic views go one step further than ViewSets: they implement the actual CRUD logic for you, using the **repository pattern** to stay ORM-agnostic. You provide a `repository` object and a few schema classes, and the framework handles create, retrieve, update, partial update, delete, and paginated listing automatically.

---

## The repository protocol

Generic views communicate with your data layer through a simple protocol. Your repository object must implement the methods the actions you enable actually call:

```python
class AsyncRepository(Protocol[M]):
    async def create(self, **kwargs: Any) -> M | None: ...
    async def get(self, *args: Any, **kwargs: Any) -> M | None: ...
    async def get_filtered_page(
        self, filter: BasePaginationFilter, **kwargs: Any
    ) -> Page[M]: ...
    async def list(self, *args: Any, **kwargs: Any) -> Sequence[M]: ...
    async def delete_one(self, *args: Any, **kwargs: Any) -> M | None: ...
    async def update_one(
        self, values: dict[str, Any], *args: Any, **kwargs: Any
    ) -> M | None: ...
```

The synchronous `Repository` protocol is identical but without `async`. Both are `Protocol`s, so nothing needs to be subclassed — any object with matching methods works.

Each action maps to exactly one repository call:

| Action | Repository call |
|--------|-----------------|
| list (no pagination filter) | `list(*args, **kwargs)` |
| list (pagination filter) | `get_filtered_page(filter, **kwargs)` |
| create | `create(**data)` |
| retrieve | `get(*args, **kwargs)` |
| update / partial update | `update_one(values, *args, **kwargs)` |
| destroy | `delete_one(*args, **kwargs)` |

`get_filtered_page` returns anything satisfying the `Page` protocol — an object exposing an `items` sequence. The built-in [pagination](../reference/pagination.md) containers (`NumberedPage`, `OffsetPage`, `CursorPage`) all qualify.

Returning `None` from `create` raises `409 Conflict`. Returning `None` from `get` or `update_one` raises `404 Not Found`. You never need to raise these errors yourself. The return value of `delete_one` is ignored — destroy responds `204 No Content` with an empty body.

Both behaviours are opt-out:

| Attribute | Default | Effect |
|-----------|---------|--------|
| `raise_conflict_create_none` | `True` | `create` returning `None` raises `409 Conflict` |
| `raise_on_none` | `True` | `retrieve` / `update` / `partial_update` returning `None` raises `404 Not Found` |

---

## `AsyncGenericViewSet`

`AsyncGenericViewSet` combines all six CRUD actions into a single class. Configure it with class-level attributes:

| Attribute | Purpose |
|-----------|---------|
| `repository` | Repository instance (sync or async) |
| `response_schema` | Pydantic model used to serialize responses |
| `primary_key` | Pydantic model whose fields become the URL path parameters |
| `create_schema` | Pydantic model for the POST request body |
| `update_schema` | Pydantic model for the PUT request body |
| `partial_update_schema` | Pydantic model for the PATCH request body |
| `filter` | Filter class for the list action, or `None` (see [Filters](filters.md)) |
| `api_component_name` | Human-readable name used in OpenAPI |
| `detail_route` | Path suffix for detail actions, default `"/{id}"` |
| `action_dependencies` | Route-level dependencies applied per action, e.g. auth scopes (see [Auth](auth.md)) |

Every attribute except `api_component_name`, `detail_route` and `action_dependencies` is **required** — including `filter`, which has no default and must be set explicitly to a filter class or to `None`. Individual views only require the attributes their own actions use: a list-only view needs `repository`, `response_schema` and `filter`, but no `primary_key`.

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

    async def get(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return self._data.get(kwargs["id"])

    async def list(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self._data.values())

    async def get_filtered_page(self, filter, **kwargs) -> Page[dict[str, Any]]:
        raise NotImplementedError

    async def delete_one(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return self._data.pop(kwargs["id"], None)

    async def update_one(
        self, values: dict[str, Any], *args: Any, **kwargs: Any
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

For the common integer case the module ships a ready-made model — `from fastapi_views.views.generics import Id`, which is just `id: int`.

The key model is injected with `Depends(primary_key)`, so its fields are matched against the placeholders in `detail_route`. For composite keys, add more fields **and** widen the route so every field is a path parameter:

```python
class CompositeKey(BaseModel):
    tenant_id: UUID
    item_id: int

class ItemViewSet(AsyncGenericViewSet):
    primary_key = CompositeKey
    detail_route = "/{tenant_id}/{item_id}"
    ...
```

Detail actions build their repository arguments in `get_primary_key(primary_key, action)`, which returns a `(args, kwargs)` tuple — by default no positional arguments and `primary_key.model_dump() | self.get_kwargs(action)` as keyword arguments. Override it when your repository expects the key positionally.

---

## Scoping queries with `get_kwargs`

`get_kwargs(action)` returns extra criteria merged into every repository call, which is how you scope a view to the current tenant, user, or soft-delete state without overriding any action:

```python
class ItemViewSet(AsyncGenericViewSet):
    ...

    def get_kwargs(self, action=None, /) -> dict[str, Any]:
        return {"tenant_id": self.request.state.tenant_id}
```

Where the result lands depends on the action:

| Action | `action` argument | Where the kwargs go |
|--------|-------------------|---------------------|
| create | `"create"` | merged into the validated create payload |
| retrieve / update / partial update / destroy | the action name | merged with the primary key |
| list, `filter = None` | `None` | passed straight to `repository.list()` |
| list, with a filter | `None` | added to the filter via `filter.with_kwargs()` |

---

## Filters and pagination

Set the `filter` attribute to a filter class to enable filtering, sorting, searching, and pagination on the list endpoint. Its fields become query parameters — `FilterDepends` is applied for you.

The filter class also selects the **response container** for the list action:

| `filter` | List response schema |
|----------|----------------------|
| `None`, or a plain `BaseFilter` subclass | `list[response_schema]` |
| a `PaginationFilter` subclass | `NumberedPage[response_schema]` |
| an `OffsetLimitFilter` subclass | `OffsetPage[response_schema]` |
| a `CursorPaginationFilter` subclass | `CursorPage[response_schema]` |

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

Any filter deriving from `BasePaginationFilter` is delegated to `repository.get_filtered_page(filter, ...)`, which is responsible for slicing and for building the page. A non-paginating filter goes to `repository.list(*args, **kwargs)` instead.

Set `filter = None` to return a plain list with no query parameters at all; the repository is then called as `repository.list(**self.get_kwargs())`.

See [Filters](filters.md) for how to build custom filter classes, and [sqlargon](sqlargon.md) for ready-made paginating repositories.

### List hooks

Three small hooks control how a filter reaches the repository:

| Hook | Default | Purpose |
|------|---------|---------|
| `resolve_filter(filter)` | `(), filter.as_kwargs()` | Turns a non-paginating filter into the `(args, kwargs)` passed to `repository.list` |
| `get_pagination_kwargs()` | `{}` | Extra keyword arguments forwarded to `repository.get_filtered_page` |
| `get_fields_key()` | `"items"` for a page container, else `"__all__"` | Where sparse-fieldset projection is applied when serializing |

`get_pagination_kwargs` is the place to pass repository- or resolver-specific context, e.g. the joined-table mapping a SQLAlchemy resolver needs:

```python
class ItemViewSet(AsyncGenericViewSet):
    ...

    def get_pagination_kwargs(self) -> dict[str, Any]:
        return {"owner": {"table": OwnerModel}}
```

When the filter is a `FieldsFilter` and the request carries `?fields=...`, the requested field set is written to `serializer_options["include"]` under `get_fields_key()`, so only those fields are serialized. Override `get_fields_key` if you wrap responses in a custom container whose payload does not live under `items`.

---

## Lifecycle hooks

The create and update actions have `before_*` and `after_*` hooks so you can add custom logic without overriding the whole action. The `before_*` hook receives the mutable data dict — anything you put in it is sent to the repository; the `after_*` hook receives the object the repository returned (which may be `None`):

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

    async def before_create(self, data: dict[str, Any]) -> None:
        # Runs after schema validation and after get_kwargs("create") is merged in,
        # before repository.create()
        data["created_by"] = self.request.state.user_id

    async def after_create(self, obj: Item | None) -> None:
        # Runs after repository.create(), only if no 409 Conflict was raised
        await send_welcome_email(obj)

    async def before_update(self, data: dict[str, Any]) -> None:
        data["updated_by"] = self.request.state.user_id

    async def after_update(self, obj: Item | None) -> None:
        await invalidate_cache(obj.id)

    async def before_partial_update(self, data: dict[str, Any]) -> None:
        # data only contains fields that were actually sent in the request
        data["updated_by"] = self.request.state.user_id

    async def after_partial_update(self, obj: Item | None) -> None:
        await invalidate_cache(obj.id)
```

The hooks are `async` on the async views and plain methods on the sync ones. The list, retrieve and destroy actions have no hooks — override the action itself, or use `get_kwargs`.

---

## Individual generic views

Use individual generic view classes when you do not need the full CRUD surface:

| Class | Action | Extra attributes |
|-------|--------|------------------|
| `AsyncGenericListAPIView` | list | `filter` |
| `AsyncGenericCreateAPIView` | create | `create_schema` |
| `AsyncGenericRetrieveAPIView` | retrieve | `primary_key` |
| `AsyncGenericUpdateAPIView` | update | `primary_key`, `update_schema` |
| `AsyncGenericPartialUpdateAPIView` | partial update | `primary_key`, `partial_update_schema` |
| `AsyncGenericDestroyAPIView` | destroy | `primary_key` |

Combine several of them to build a partial CRUD surface — each contributes its own route:

```python
from fastapi_views.views.generics import (
    AsyncGenericListAPIView,
    AsyncGenericRetrieveAPIView,
)

class ItemReadViewSet(AsyncGenericListAPIView, AsyncGenericRetrieveAPIView):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    filter = None
    repository = ItemRepository()
```

All have synchronous counterparts without the `Async` prefix (e.g., `GenericViewSet`, `GenericListAPIView`). Do not mix sync and async generic views in one class — pick one flavour, matching your repository.

---

## Complete example

```python
--8<-- "examples/generics.py"
```
