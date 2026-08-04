# Bulk actions

Bulk views add collection endpoints that accept many items in one request. They are **opt-in** — deliberately kept out of the standard viewsets — so you mix them in only where a resource should support batch operations.

Every bulk operation is **all-or-nothing**: the view delegates the whole batch to a single repository call, which is expected to run inside one transaction, so a single bad item rolls the entire batch back.

---

## The bulk repository protocol

Bulk views talk to your data layer through `AsyncBulkRepository` (or the sync `BulkRepository`), a standalone protocol requiring exactly the methods the bulk views call:

```python
class AsyncBulkRepository(Protocol[M]):
    async def create_many(self, items: Sequence[Mapping[str, Any]]) -> Sequence[M]: ...
    async def update_many(self, values: Mapping[str, Any], /, *args: Any, **kwargs: Any) -> Sequence[M]: ...
    async def bulk_update(self, items: Sequence[Mapping[str, Any]], /) -> None: ...
    async def delete_many(self, *args: Any, **kwargs: Any) -> None: ...
```

There are two update strategies, mapping to two different repository methods:

- **Per-item bulk update** (`PUT /bulk-update`) sends a list of items, each carrying its own primary key and values, and calls `bulk_update`. It is meant for an `executemany`-style statement, which cannot return rows — so the route responds with `204 No Content`.
- **Filtered update** (`PATCH /bulk-update`) sends one set of values and selects rows with a **filter** (the same mechanism as bulk-delete), calling `update_many(values, *args, **kwargs)` with the filter resolved to criteria. The statement can use `RETURNING`, so the route responds with the updated objects.

`create_many` / `bulk_update` receive a list of plain dicts (validated request bodies), plus any `repository_options` declared on the view. Bulk **delete** resolves a filter to keyword arguments and calls `delete_many`.

---

## `AsyncBulkAPIViewSet`

`AsyncBulkAPIViewSet` bundles all four bulk actions. Configure it with class-level attributes:

| Attribute | Purpose |
|-----------|---------|
| `api_component_name` | Human-readable name used in OpenAPI |
| `response_schema` | Pydantic model used to serialize responses |
| `create_schema` | Per-item schema for the bulk-create body |
| `bulk_update_schema` | Per-item schema for the bulk-update body — **must carry the primary key** |
| `update_schema` | Schema of the values applied to every row selected by the filter |
| `filter` | Filter class selecting rows for update-many and bulk-delete |
| `repository` | Repository instance implementing the bulk contract |

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    api_component_name = "Item"
    response_schema = Item
    create_schema = CreateItem
    bulk_update_schema = UpdateItem   # carries `id`
    update_schema = ItemValues
    filter = ItemFilter
    repository = ItemRepository()
```

This registers:

| Method | Path | Body | Action |
|--------|------|------|--------|
| POST | `/items/bulk-create` | `[CreateItem, ...]` | create many → `[Item, ...]` |
| PUT | `/items/bulk-update` | `[UpdateItem, ...]` | update each item by its key → `204` |
| PATCH | `/items/bulk-update` | `ItemValues` (+ filter query) | update matching rows → `[Item, ...]` |
| DELETE | `/items/bulk-delete` | — (filter query) | delete matching rows → `204` |

Mix it in alongside a regular viewset to get both standard CRUD and bulk endpoints:

```python
class ItemViewSet(AsyncBulkAPIViewSet, AsyncAPIViewSet):
    ...
```

---

## Configurable routes

Each route path is overridable per view:

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    bulk_create_route = "/batch"
    bulk_update_route = "/batch"
    update_many_route = "/batch"
    bulk_delete_route = "/batch"
    ...
```

---

## Selecting rows with a filter

Update-many and bulk-delete select rows with a **filter**, not a hard-coded id list — acting by id is just a filter with an `id__in` field, and you can swap it for any criteria. The filter's fields become query parameters:

```python
class ItemFilter(BaseFilter):
    name: str | None = None

# PATCH  /items/bulk-update?name=widget  ->  repository.update_many(values, name="widget")
# DELETE /items/bulk-delete?name=widget  ->  repository.delete_many(name="widget")
```

Set `filter = None` to act on everything matched by `get_kwargs`.

---

## Returning created / updated objects

Bulk-create and update-many return the affected objects by default. Set `return_on_create` / `return_on_update` to `False` to respond with an empty body (the status code is preserved):

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    return_on_create = False   # POST  /bulk-create -> 201 with empty body
    return_on_update = False   # PATCH /bulk-update -> 200 with empty body
    ...
```

Per-item bulk update (`PUT /bulk-update`) always responds `204 No Content` — its `executemany`-style repository call cannot return rows.

---

## Lifecycle hooks

Each bulk action has `before_*` / `after_*` hooks:

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    ...
    async def before_bulk_create(self, data: list[dict]) -> None: ...
    async def after_bulk_create(self, objects) -> None: ...
    async def before_bulk_update(self, data: list[dict]) -> None: ...
    async def after_bulk_update(self) -> None: ...
    async def before_update_many(self, values: dict) -> None: ...
    async def after_update_many(self, objects) -> None: ...
    async def before_bulk_delete(self) -> None: ...
    async def after_bulk_delete(self) -> None: ...
```

---

## Individual bulk views

Use a single bulk view when you do not want all four actions. All share the same `AsyncBulkRepository` / `BulkRepository` protocol:

| Class | Action |
|-------|--------|
| `AsyncGenericBulkCreateAPIView` | bulk-create |
| `AsyncGenericBulkUpdateAPIView` | bulk-update (per-item) |
| `AsyncGenericUpdateManyAPIView` | update-many (filtered) |
| `AsyncGenericBulkDestroyAPIView` | bulk-delete |

All have synchronous counterparts without the `Async` prefix (e.g., `BulkAPIViewSet`, `GenericBulkCreateAPIView`).

---

## Complete example

```python
--8<-- "examples/bulk.py"
```
