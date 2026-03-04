# API Views

Core view base classes. Import these directly from `fastapi_views.views` or from `fastapi_views.views.api`.

`View` is the lowest level — it only handles route registration. `APIView` adds Pydantic serialization and error handling. The `*APIView` mixin classes each implement a single CRUD action and can be combined freely.

For a complete walkthrough see [Basic usage](../usage/basic.md).

---

::: fastapi_views.views.api
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
