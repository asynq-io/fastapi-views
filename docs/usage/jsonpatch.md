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
3. The patched document is validated against `partial_update_schema` again, so a patch can never produce an invalid resource.
4. Only the **changed** fields are sent to `repository.update_one`. If nothing changed, the repository is not called at all and the fetched object is returned.

Failure modes (in an app set up with `configure_app`, which remaps FastAPI's default `422` validation errors to `400`):

| Case | Response |
|------|----------|
| Invalid patch (malformed document, bad pointer, failed `test`, invalid result, unknown field) | `400 Bad Request` |
| Object not found | `404 Not Found` |

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

This registers `PATCH /items/{id}` accepting a JSON Patch document:

```json
[
    {"op": "test", "path": "/name", "value": "old name"},
    {"op": "replace", "path": "/name", "value": "new name"},
    {"op": "add", "path": "/tags/-", "value": "new-tag"}
]
```

A synchronous `GenericJsonPatchAPIView` is also available. Both expose `before_partial_update(data)` and `after_partial_update(model)` hooks, mirroring the plain partial-update views.

See `examples/json_patch.py` for a complete runnable app.
