# Bulk Views

Opt-in views for batch collection operations. Import from `fastapi_views.views.bulk`.

Bulk views follow the same repository pattern as [generic views](generics.md): supply a repository satisfying the `AsyncBulkRepository` / `BulkRepository` protocol (which extends the regular repository), plus per-item schemas, and the view wires up `POST /bulk-create`, `PUT /bulk-update`, and `DELETE /bulk-delete`. Every operation is all-or-nothing (one transaction).

For a complete walkthrough see [Bulk actions](../usage/bulk.md).

---

::: fastapi_views.views.bulk
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
