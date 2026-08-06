# Bulk Views

Opt-in views for batch collection operations. Import from `fastapi_views.views.bulk`.

Bulk views follow the same repository pattern as [generic views](generics.md): supply a repository satisfying the `AsyncBulkRepository` / `BulkRepository` protocol (a standalone protocol requiring only `create_many`, `bulk_update`, `update_many` and `delete_many`), plus the action schemas, and the view wires up **one route** — `bulk_route`, `/bulk` by default — with each action selected by the HTTP method:

| Method | Action | Repository call | Success |
|--------|--------|-----------------|---------|
| `POST` | `bulk_create` | `create_many` | `201` |
| `PUT` | `bulk_update` | `bulk_update` (per item) | `204` |
| `PATCH` | `update_many` | `update_many` (filtered) | `200` |
| `DELETE` | `bulk_delete` | `delete_many` (filtered) | `204` |

Every operation is all-or-nothing (one transaction).

`repository_options` / `get_repository_options(action)` are defined once on `BaseGenericBulkAPIView` and reach **all four** calls. The filtered actions (`PATCH`, `DELETE`) build their keyword arguments from the resolved filter and then add the options through `merge_repository_options(kwargs, action)`, which raises `TypeError` when an option key collides with a resolved filter key; override it to pick a precedence. All four protocol methods declare `**kwargs` so they can receive the options, and each one's leading parameter is positional-only — an implementation must declare it positional-only too in order to type-check as conforming.

The hooks that receive objects — `after_bulk_create(objs)` and `after_update_many(objs)` — use the same parameter name on the sync and async views.

For a complete walkthrough see [Bulk actions](../usage/bulk.md).

---

::: fastapi_views.views.bulk
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
