# JSON Patch

[RFC 6902](https://www.rfc-editor.org/rfc/rfc6902) `PATCH` support. Requires the `jsonpatch` extra:

```shell
pip install 'fastapi-views[jsonpatch]'
```

The view mixin lives in `fastapi_views.views.jsonpatch`; the request/patch models live in `fastapi_views.models.jsonpatch`. A patch document arrives as `application/json-patch+json`, is applied to the current representation, and the result is persisted through the repository.

For a complete walkthrough see [JSON Patch](../usage/jsonpatch.md).

---

## Views

::: fastapi_views.views.jsonpatch
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

## Models

::: fastapi_views.models.jsonpatch
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
