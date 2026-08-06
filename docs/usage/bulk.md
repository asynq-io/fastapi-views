# Bulk actions

Bulk views add collection endpoints that accept many items in one request. They are **opt-in** — deliberately kept out of the standard viewsets — so you mix them in only where a resource should support batch operations.

Every bulk operation is **all-or-nothing**: the view delegates the whole batch to a single repository call, which is expected to run inside one transaction, so a single bad item rolls the entire batch back.

---

## The bulk repository protocol

Bulk views talk to your data layer through `AsyncBulkRepository` (or the sync `BulkRepository`), a standalone protocol requiring exactly the methods the bulk views call:

```python
class AsyncBulkRepository(Protocol[M_co]):
    async def create_many(self, items: Sequence[Mapping[str, Any]], /, **kwargs: Any) -> Sequence[M_co]: ...
    async def update_many(self, values: Mapping[str, Any], /, *args: Any, **kwargs: Any) -> Sequence[M_co]: ...
    async def bulk_update(self, items: Sequence[Mapping[str, Any]], /, **kwargs: Any) -> None: ...
    async def delete_many(self, *args: Any, **kwargs: Any) -> None: ...
```

All four methods declare `**kwargs`, because all four receive the view's
[`repository_options`](#repository-options) as keyword arguments.

!!! important
    The leading parameter (`items` / `values`) is **positional-only**. An implementation
    must declare it positional-only too — `async def create_many(self, items, /, **kwargs)` —
    to type-check as conforming: since the protocol's `**kwargs` allows a keyword literally
    named `items`, a positional-*or*-keyword parameter is rejected even though it works at
    runtime.

All bulk actions live on a **single route** — `/bulk` — and are told apart by the HTTP method:

| Method | Action | Repository call | Success |
|--------|--------|-----------------|---------|
| `POST` | `bulk_create` | `create_many` | `201 Created` |
| `PUT` | `bulk_update` | `bulk_update` (per item) | `204 No Content` |
| `PATCH` | `update_many` | `update_many` (filtered) | `200 OK` |
| `DELETE` | `bulk_delete` | `delete_many` (filtered) | `204 No Content` |

There are two update strategies, mapping to two different repository methods:

- **Per-item bulk update** (`PUT /bulk`) sends a list of items, each carrying its own primary key and values, and calls `bulk_update`. It is meant for an `executemany`-style statement, which cannot return rows — so the route responds with `204 No Content`.
- **Filtered update** (`PATCH /bulk`) sends one set of values and selects rows with a **filter** (the same mechanism as bulk-delete), calling `update_many(values, *args, **kwargs)` with the filter resolved to criteria. The statement can use `RETURNING`, so the route responds with the updated objects.

How each action builds its repository call:

- **`create_many` / `bulk_update`** receive a list of plain dicts — each validated item dumped with `model_dump()` and merged with `get_kwargs(action)` — followed by the view's [`repository_options`](#repository-options) as keyword arguments.
- **`update_many`** receives the values dumped with `model_dump(exclude_unset=True)`, so only fields the client actually sent are applied, followed by the resolved filter criteria merged with `repository_options`.
- **`delete_many`** receives the resolved filter criteria merged with `repository_options`.

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
| `filter` | Filter class selecting rows for update-many and bulk-delete — **required**, set it to `None` to opt out |
| `repository` | Repository instance implementing the bulk contract |
| `bulk_route` | Path all four actions share (default `"/bulk"`) |
| `return_on_create` / `return_on_update` | Whether `POST` / `PATCH` respond with a body (default `True`) |
| `repository_options` | Extra keyword arguments forwarded to every bulk repository call |

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
| POST | `/items/bulk` | `[CreateItem, ...]` | create many → `[Item, ...]` |
| PUT | `/items/bulk` | `[UpdateItem, ...]` | update each item by its key → `204` |
| PATCH | `/items/bulk` | `ItemValues` (+ filter query) | update matching rows → `[Item, ...]` |
| DELETE | `/items/bulk` | — (filter query) | delete matching rows → `204` |

Each operation also documents the usual error responses: `400` everywhere, `409 Conflict` on `POST`/`PUT`/`PATCH`, and `404 Not Found` on `PUT`.

Mix it in alongside a regular viewset to get both standard CRUD and bulk endpoints on the same resource:

```python
class ItemViewSet(AsyncBulkAPIViewSet, AsyncGenericViewSet):
    ...
    # GET/POST /items, GET/PUT/PATCH/DELETE /items/{id}
    # POST/PUT/PATCH/DELETE /items/bulk
```

The bulk actions reuse the same `repository` attribute, so it has to satisfy both the plain `AsyncRepository` protocol and the bulk one.

---

## Configurable route

All bulk actions share one path, set by `bulk_route`:

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    bulk_route = "/batch"   # POST/PUT/PATCH/DELETE /items/batch
    ...
```

---

## Selecting rows with a filter

Update-many and bulk-delete select rows with a **filter**, not a hard-coded id list — acting by id is just a filter with an `id__in` field, and you can swap it for any criteria. The filter's fields become query parameters:

```python
class ItemFilter(BaseFilter):
    name: str | None = None

# PATCH  /items/bulk?name=widget  ->  repository.update_many(values, name="widget")
# DELETE /items/bulk?name=widget  ->  repository.delete_many(name="widget")
```

`filter` is a required attribute on the filtered views — set it to `None` to act on everything matched by `get_kwargs` (handy for tenant-scoped views):

```python
class TenantBulkDeleteView(AsyncGenericBulkDestroyAPIView):
    filter = None
    repository = ItemRepository()

    def get_kwargs(self, _action=None, /):
        return {"tenant_id": current_tenant()}   # DELETE /items/bulk -> delete_many(tenant_id=...)
```

Three overridable methods control how a filter becomes a repository call:

- `resolve_filter(filter)` returns the `(args, kwargs)` passed to the repository — by default `(), filter.as_kwargs()`. Override it to translate the filter into positional criteria (e.g. SQLAlchemy expressions).
- `get_filter_args(filter, action=None)` merges `get_kwargs(action)` into the filter via `filter.with_kwargs(...)` and then delegates to `resolve_filter`. When `filter = None`, it short-circuits and returns `get_kwargs(action)` alone.
- `merge_repository_options(kwargs, action=None)` adds `get_repository_options(action)` to the keyword arguments `get_filter_args` produced, and is what the filtered actions actually pass to the repository. See [Repository options](#repository-options) for the collision rule.

---

## Repository options

`repository_options` is a class-level dict of extra keyword arguments forwarded to **all four** bulk repository calls — use it for driver-level knobs your repository accepts:

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    repository_options: ClassVar[dict[str, Any]] = {"batch_size": 500}
    ...

# repository.create_many(data, batch_size=500)
# repository.bulk_update(data, batch_size=500)
# repository.update_many(values, name="widget", batch_size=500)     # PATCH /bulk?name=widget
# repository.delete_many(name="widget", batch_size=500)             # DELETE /bulk?name=widget
```

`create_many` and `bulk_update` receive the options as their only keyword arguments. The filtered actions build their keyword arguments from the resolved filter first, so their options share one keyword space with the filter criteria — `merge_repository_options(kwargs, action)` combines the two and raises `TypeError` when a key appears in both, rather than silently dropping a criterion and widening the set of rows a `PATCH` or `DELETE` touches:

```python
class BrokenView(AsyncGenericBulkDestroyAPIView):
    filter = ItemFilter                                          # has a `name` field
    repository_options: ClassVar[dict[str, Any]] = {"name": "x"}  # collides
```

The check is per request: because filter fields are usually optional, an option shadowing a field the client did not send is inert (`DELETE /items/bulk` above resolves to `delete_many(name="x")`), and the same view fails only once a request carries `?name=`. Override `merge_repository_options` to pick a precedence instead:

```python
class OptionsWinView(AsyncGenericBulkDestroyAPIView):
    def merge_repository_options(self, kwargs, action=None):
        return kwargs | self.get_repository_options(action)
```

Override `get_repository_options(action)` to vary the options per action — it receives the action name (`"bulk_create"`, `"bulk_update"`, `"update_many"`, `"bulk_delete"`).

---

## Returning created / updated objects

Bulk-create and update-many return the affected objects by default. Set `return_on_create` / `return_on_update` to `False` to respond with an empty body (the status code is preserved):

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    return_on_create = False   # POST  /bulk -> 201 with empty body
    return_on_update = False   # PATCH /bulk -> 200 with empty body
    ...
```

Per-item bulk update (`PUT /bulk`) always responds `204 No Content` — its `executemany`-style repository call cannot return rows.

---

## Lifecycle hooks

Each bulk action has `before_*` / `after_*` hooks:

```python
class ItemViewSet(AsyncBulkAPIViewSet):
    ...
    async def before_bulk_create(self, data: list[dict]) -> None: ...
    async def after_bulk_create(self, objs) -> None: ...
    async def before_bulk_update(self, data: list[dict]) -> None: ...
    async def after_bulk_update(self) -> None: ...
    async def before_update_many(self, values: dict) -> None: ...
    async def after_update_many(self, objs) -> None: ...
    async def before_bulk_delete(self) -> None: ...
    async def after_bulk_delete(self) -> None: ...
```

The `before_*` hooks see the data that is about to be sent to the repository and run before the call; the `after_*` hooks run after it and before the response is built. `after_bulk_update` and both delete hooks take no payload, because their repository calls do not return rows. The two hooks that do receive objects — `after_bulk_create` and `after_update_many` — name that parameter `objs`, on both the sync and the async views, so overrides keep the same signature everywhere. On the synchronous views the same hooks are plain `def` methods.

---

## Individual bulk views

Use a single bulk view when you do not want all four actions. All share the same `AsyncBulkRepository` / `BulkRepository` protocol:

| Class | Method | Required attributes |
|-------|--------|---------------------|
| `AsyncGenericBulkCreateAPIView` | `POST` | `create_schema`, `response_schema` |
| `AsyncGenericBulkUpdateAPIView` | `PUT` | `bulk_update_schema` |
| `AsyncGenericUpdateManyAPIView` | `PATCH` | `update_schema`, `filter`, `response_schema` |
| `AsyncGenericBulkDestroyAPIView` | `DELETE` | `filter` |

Combining any subset registers those methods on the shared `bulk_route`, so only the verbs you mix in exist.

All have synchronous counterparts without the `Async` prefix (`BulkAPIViewSet`, `GenericBulkCreateAPIView`, `GenericBulkUpdateAPIView`, `GenericUpdateManyAPIView`, `GenericBulkDestroyAPIView`).

The repository attribute is typed by `WithAsyncBulkRepositoryMixin[M]` / `WithBulkRepositoryMixin[M]`, which the generic views already mix in.

---

## Bypassing the repository layer

Below the generic views sit the abstract ones, which register the same route and status code but leave the action body to you. Implement the action method with whatever signature you need — its parameters become the endpoint's parameters:

```python
from fastapi_views.views.bulk import AsyncBulkCreateAPIView


class ItemImportView(AsyncBulkCreateAPIView):
    response_schema = Item

    async def bulk_create(self, items: list[CreateItem]) -> list[Item]:
        return await my_importer.run(items)   # POST /items/bulk -> 201, [Item, ...]
```

| Class | Method | Abstract method |
|-------|--------|-----------------|
| `AsyncBulkCreateAPIView` / `BulkCreateAPIView` | `POST` | `bulk_create` |
| `AsyncBulkUpdateAPIView` / `BulkUpdateAPIView` | `PUT` | `bulk_update` |
| `AsyncUpdateManyAPIView` / `UpdateManyAPIView` | `PATCH` | `update_many` |
| `AsyncBulkDestroyAPIView` / `BulkDestroyAPIView` | `DELETE` | `bulk_delete` |

`return_on_create` and `return_on_update` apply here too; the `PUT` and `DELETE` views always return an empty body.

---

## Complete example

```python
--8<-- "examples/bulk.py"
```
