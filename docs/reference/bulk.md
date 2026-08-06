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

For a complete walkthrough see [Bulk actions](../usage/bulk.md).

---

::: fastapi_views.views.bulk
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
