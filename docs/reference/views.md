# API Views

Core view base classes. Import these directly from `fastapi_views.views` or from `fastapi_views.views.api`.

`View` is the lowest level — route registration plus JSON serialization driven by the endpoint's return annotation. `APIView` adds `response_schema`, per-action dependencies, response-header documentation and error handling. The `*APIView` mixin classes each implement a single CRUD action and can be combined freely.

For a complete walkthrough see [Basic usage](../usage/basic.md).

---

::: fastapi_views.views.api
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

## Mixins

Behavioural mixins shared by the view classes above. [`ConditionalMixin`][fastapi_views.views.mixins.ConditionalMixin], which adds `ETag` / `Last-Modified` validators and `304` handling, is documented with [Caching](cache.md).

::: fastapi_views.views.mixins.DependencyMixin
    handler: python
    options:
        show_root_heading: true
        members_order: source
        show_signature_annotations: true

::: fastapi_views.views.mixins.DetailViewMixin
    handler: python
    options:
        show_root_heading: true
        members_order: source
        show_signature_annotations: true

::: fastapi_views.views.mixins.ErrorHandlerMixin
    handler: python
    options:
        show_root_heading: true
        members_order: source
        show_signature_annotations: true
