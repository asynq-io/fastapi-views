# ViewSets

Pre-built combinations of the individual `*APIView` mixin classes. Import from `fastapi_views.views.viewsets`.

Each ViewSet bundles a fixed set of CRUD actions. Use `AsyncAPIViewSet` for the full five-action set, or pick a smaller combination (e.g., `AsyncReadOnlyAPIViewSet`, `AsyncListCreateAPIViewSet`) to expose only what your resource needs.

Every class here is abstract: subclass it, set `response_schema` and implement the action methods before registering it (`register_view` raises `TypeError` for a still-abstract view). No pre-built combination includes `partial_update` — compose `AsyncPartialUpdateAPIView` yourself when you need `PATCH`.

For a complete walkthrough see [ViewSets](../usage/viewset.md).

---

::: fastapi_views.views.viewsets
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_source: true
        show_signature_annotations: true
