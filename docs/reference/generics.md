# Generic Views

Repository-backed view classes that implement full CRUD logic automatically. Import from `fastapi_views.views.generics`.

Generic views follow the **repository pattern**: you supply a `repository` object that satisfies the `Repository` or `AsyncRepository` protocol, plus schema classes for each operation, and the view wires everything together. Lifecycle hooks (`before_create`, `after_create`, etc.) let you inject custom logic without overriding actions.

For a complete walkthrough see [Generic views](../usage/generics.md).

---

::: fastapi_views.views.generics
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
