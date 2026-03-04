# Filters

Filter, sorting, pagination, and field-projection classes. Import filter models from `fastapi_views.filters.models` and dependencies from `fastapi_views.filters.dependencies`.

For a complete walkthrough including resolver usage see [Filters](../usage/filters.md).

## Filter models

::: fastapi_views.filters.models
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

## Dependencies

`FilterDepends` and `NestedFilter` are FastAPI dependency factories used to inject filter instances into view methods.

::: fastapi_views.filters.dependencies
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_signature_annotations: true

---

## Resolvers

Resolvers translate a filter object into a data-layer query. Subclass the appropriate resolver and set `filter_model` before injecting it with `Depends()`.

### `ObjectFilterResolver`

::: fastapi_views.filters.resolvers.objects
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

### `SQLAlchemyFilterResolver`

::: fastapi_views.filters.resolvers.sqlalchemy
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
