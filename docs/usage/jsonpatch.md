# JSON Patch

JSON Patch views handle `PATCH` requests carrying an [RFC 6902](https://datatracker.ietf.org/doc/html/rfc6902) JSON Patch document (`application/json-patch+json`) — a list of operations applied to the resource — instead of a plain partial body. This lets clients express changes a flat body cannot, such as appending to an array or conditionally testing a value before replacing it.

This feature requires the `jsonpatch` extra:

```bash
pip install fastapi-views[jsonpatch]
```

---

## How a patch is applied

1. The current object is fetched from the repository and projected onto `partial_update_schema`, then dumped in JSON mode (operations compare against raw JSON values, so e.g. datetimes are matched as strings).
2. The patch operations are applied to that document.
3. The patched document is validated against `partial_update_schema` again, so a patch can never produce an invalid resource. Because the values written back come from that validated model, they are **coerced to their Python types** — `{"op": "replace", "path": "/updated_at", "value": "2026-02-01T00:00:00Z"}` reaches the repository as a `datetime`.
4. Only the **changed** fields are sent to `repository.update_one`. If nothing changed, the repository is not called at all and the fetched object is returned.

A field is "changed" if its value differs between the original and patched documents. Removing a field that has a schema default therefore writes the default back rather than dropping the column: `{"op": "remove", "path": "/tags"}` on `tags: list[str] = []` sends `{"tags": []}`.

Failure modes (in an app set up with `configure_app`, which remaps FastAPI's default `422` validation errors to `400`):

| Case | Response |
|------|----------|
| Invalid patch (malformed document, bad pointer, failed `test`, invalid result, unknown field) | `400 Bad Request` |
| Object not found, or deleted between the fetch and the update | `404 Not Found` |

Without `configure_app`'s error handlers a *malformed* patch document surfaces as FastAPI's raw `422`, since the rejection happens during request validation rather than in the view.

---

## `AsyncGenericJsonPatchAPIView`

Configure it with the same class-level attributes as other [generic views](generics.md); the repository only needs `get` and `update_one`:

```python
from fastapi_views.views.jsonpatch import AsyncGenericJsonPatchAPIView


class ItemJsonPatchView(AsyncGenericJsonPatchAPIView):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    partial_update_schema = Item
    repository = ItemRepository()
```

This registers `PATCH /items/{id}` accepting a JSON Patch document, advertised in OpenAPI under the `application/json-patch+json` request content type:

```json
[
    {"op": "test", "path": "/name", "value": "old name"},
    {"op": "replace", "path": "/name", "value": "new name"},
    {"op": "add", "path": "/tags/-", "value": "new-tag"}
]
```

`partial_update_schema` does double duty: it defines the document the operations are applied to *and* bounds what a patch may touch, so it is usually the full resource schema rather than a partial one.

A synchronous `GenericJsonPatchAPIView` is also available. Both expose `before_partial_update(data)` and `after_partial_update(model)` hooks, mirroring the plain partial-update views — `before_partial_update` receives the changed-fields dict and is skipped entirely when the patch is a no-op.

---

## Patch documents and operations

`fastapi_views.models.jsonpatch` holds the model and types behind the request body:

| Symbol | Description |
|--------|-------------|
| `JsonPatchModel` | `RootModel[JsonPatch]` validating a whole patch document; `.apply(doc, *, in_place=False)` returns the patched document |
| `JsonPatchModel.__content_type__` | `"application/json-patch+json"` — the media type declared on the route |
| `PatchOperation` | A single operation, discriminated on `op` |
| `JsonPatch` | `list[PatchOperation]` |
| `apply(doc, operations, *, in_place=False)` | Standalone helper applying operations to any document |

All six RFC 6902 operations are supported — `add`, `remove`, `replace`, `move`, `copy` and `test` — with `move` and `copy` taking a `from` pointer instead of a `value`. Anything else is rejected during validation.

`apply` leaves the input untouched by default and returns a patched copy; pass `in_place=True` to mutate it. Root-path operations always produce a new document, so use the return value rather than relying on mutation:

```python
from fastapi_views.models.jsonpatch import apply

apply({"a": 1}, [{"op": "replace", "path": "/a", "value": 2}])  # -> {"a": 2}
```

---

## Reusing the patch logic

`JsonPatchViewMixin` carries the whole apply-and-diff step in `apply_patch(obj, operations)`, which returns the changed, schema-validated fields. Mix it into any view that already has a `partial_update_schema` to apply a patch outside the generic flow:

```python
from fastapi_views.models.jsonpatch import JsonPatchModel
from fastapi_views.views.jsonpatch import JsonPatchViewMixin


class ItemPatcher(JsonPatchViewMixin):
    partial_update_schema = Item


changed = ItemPatcher().apply_patch(item, JsonPatchModel([{"op": "remove", "path": "/tags"}]))
```

It raises `BadRequest` for a failed patch, a document that no longer validates, or a patch touching fields outside the schema. A `ValidationError` from projecting the *source* object propagates as-is — that signals a bad object, not a bad request.

---

## Complete example

```python
--8<-- "examples/json_patch.py"
```
