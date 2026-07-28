# Bulk actions

Bulk views add collection endpoints that accept many items in one request. They are **opt-in** — deliberately kept out of the standard viewsets — so you mix them in only where a resource should support batch operations.

Every bulk operation is **all-or-nothing**: the view delegates the whole batch to a single repository call, which is expected to run inside one transaction, so a single bad item rolls the entire batch back.

---

## The bulk repository protocol

Bulk views talk to your data layer through `AsyncBulkRepository` (or the sync `BulkRepository`), a standalone protocol requiring exactly the three methods the bulk views call:

```python
class AsyncBulkRepository(Protocol[M]):
    async def bulk_create(self, items: Sequence[Mapping[str, Any]], **options: Any) -> Sequence[M]: ...
    async def bulk_update(self, items: Sequence[Mapping[str, Any]], **options: Any) -> Sequence[M]: ...
    async def delete(self, *args: Any, **kwargs: Any) -> None: ...  # used by bulk-delete
```

`bulk_create` / `bulk_update` receive a list of plain dicts (validated request bodies), plus any `repository_options` declared on the view. Bulk **delete** does not need a dedicated method — it resolves a filter to keyword arguments and calls `delete`.

---

## `AsyncBulkAPIViewSet`

`AsyncBulkAPIViewSet` bundles all three bulk actions. Configure it with class-level attributes:

| Attribute | Purpose |
|-----------|---------|
| `api_component_name` | Human-readable name used in OpenAPI |
| `response_schema` | Pydantic model used to serialize responses |
| `create_schema` | Per-item schema for the bulk-create body |
| `bulk_update_schema` | Per-item schema for the bulk-update body — **must carry the primary key** |
| `filter` | Filter class selecting rows for bulk-delete |
| `repository` | Repository instance implementing the bulk contract |

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    api_component_name = "Item"
    response_schema = Item
    create_schema = CreateItem
    bulk_update_schema = UpdateItem   # carries `id`
    filter = ItemFilter
    repository = ItemRepository()
```

This registers:

| Method | Path | Body | Action |
|--------|------|------|--------|
| POST | `/items/bulk-create` | `[CreateItem, ...]` | create many → `[Item, ...]` |
| PUT | `/items/bulk-update` | `[UpdateItem, ...]` | update many → `[Item, ...]` |
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
    bulk_delete_route = "/batch"
    ...
```

---

## Delete by filter

Bulk-delete selects rows with a **filter**, not a hard-coded id list — delete-by-id is just a filter with an `id__in` field, and you can swap it for any criteria. The filter's fields become query parameters:

```python
class ItemFilter(BaseFilter):
    name: str | None = None

# DELETE /items/bulk-delete?name=widget  ->  repository.delete(name="widget")
```

Set `filter = None` to allow an unfiltered delete of everything matched by `get_kwargs`.

---

## Returning created / updated objects

Like the singular create and update views, bulk-create and bulk-update return the affected objects by default. Set `return_on_create` / `return_on_update` to `False` to respond with an empty body (the status code is preserved):

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    return_on_create = False   # POST /bulk-create -> 201 with empty body
    return_on_update = False   # PUT  /bulk-update -> 200 with empty body
    ...
```

---

## Lifecycle hooks

Each bulk action has `before_*` / `after_*` hooks:

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    ...
    async def before_bulk_create(self, data: list[dict]) -> None: ...
    async def after_bulk_create(self, objects) -> None: ...
    async def before_bulk_update(self, data: list[dict]) -> None: ...
    async def after_bulk_update(self, objects) -> None: ...
    async def before_bulk_delete(self, filter) -> None: ...
    async def after_bulk_delete(self, filter) -> None: ...
```

---

## Individual bulk views

Use a single bulk view when you do not want all three actions. All share the same `AsyncBulkRepository` / `BulkRepository` protocol:

| Class | Action |
|-------|--------|
| `AsyncGenericBulkCreateAPIView` | bulk-create |
| `AsyncGenericBulkUpdateAPIView` | bulk-update |
| `AsyncGenericBulkDestroyAPIView` | bulk-delete |

All have synchronous counterparts without the `Async` prefix (e.g., `BulkAPIViewSet`, `GenericBulkCreateAPIView`).

---

## Complete example

```python
--8<-- "examples/bulk.py"
```
