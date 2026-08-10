# Generic Views

Repository-backed view classes that implement full CRUD logic automatically. Import from `fastapi_views.views.generics`.

Generic views follow the **repository pattern**: you supply a `repository` object that satisfies the `Repository` or `AsyncRepository` protocol, plus schema classes for each operation, and the view wires everything together. Lifecycle hooks (`before_create`, `after_create`, …) let you inject custom logic without overriding actions.

Each action calls exactly one repository method:

| Action | Repository call | Class attributes used |
|--------|-----------------|-----------------------|
| list | `list(*args, **kwargs)` or `get_filtered_page(filter, **kwargs)` | `response_schema`, `filter` |
| create | `create(**data)` | `response_schema`, `create_schema` |
| retrieve | `get(*args, **kwargs)` | `response_schema`, `primary_key` |
| update | `update_one(values, *args, **kwargs)` | `response_schema`, `primary_key`, `update_schema` |
| partial update | `update_one(values, *args, **kwargs)` | `response_schema`, `primary_key`, `partial_update_schema` |
| destroy | `delete_one(*args, **kwargs)` | `primary_key` |

`get_filtered_page` is used whenever `filter` derives from `BasePaginationFilter`; it must return an object satisfying the `Page` protocol (anything exposing `items`).

The list action's response schema is chosen from `filter`, and from nothing else: `NumberedPage` for a `PaginationFilter`, `OffsetPage` for an `OffsetLimitFilter`, `CursorPage` for a `CursorPaginationFilter`, and a plain `list` otherwise. `BaseGenericListAPIView` defines no `response_schema_as_list` attribute — that switch belongs to the plain `ListAPIView` / `AsyncListAPIView` and is not consulted here. Override `get_response_schema(action)` if you need a different container.

Override points:

| Hook | Purpose |
|------|---------|
| `get_kwargs(action)` | Extra criteria merged into every repository call |
| `get_primary_key(primary_key, action)` | Builds the `(args, kwargs)` of a detail action |
| `resolve_filter(filter)` | Turns a non-paginating filter into `list()` arguments |
| `get_pagination_kwargs()` | Extra keyword arguments for `get_filtered_page` |
| `get_fields_key()` | Where sparse-fieldset projection is applied when serializing |
| `before_create` / `after_create` | Around `create` (likewise for update and partial update) |

For a complete walkthrough see [Generic views](../usage/generics.md), and [sqlargon](../usage/sqlargon.md) for ready-made repositories.

---

::: fastapi_views.views.generics
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
