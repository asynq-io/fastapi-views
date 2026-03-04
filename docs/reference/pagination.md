# Pagination

Page response models and type aliases used by the filter and generic view systems. Import from `fastapi_views.pagination`.

## Page types

| Class | Used with | Key fields |
|-------|-----------|------------|
| `NumberedPage[T]` | `PaginationFilter` | `items`, `current_page`, `page_size`, `total_pages`, `total_items` |
| `TokenPage[T]` | `TokenPaginationFilter` | `items`, `next_page`, `previous_page` |

Both inherit from `BasePage[T]` which provides the `items: list[T]` field.

`TokenPage` tokens are automatically base64-encoded in JSON responses and decoded on input, so consumers see opaque cursor strings while repository implementations can store plain values.

## Type aliases

| Alias | Type |
|-------|------|
| `PageNumber` | `PositiveInt` |
| `PageSize` | `int` constrained to `(0, MAX_PAGE_SIZE]` |
| `PageToken` | `str` with base64 encode/decode validators |

`MAX_PAGE_SIZE` defaults to `500` and can be overridden via the `MAX_PAGE_SIZE` environment variable.

---

::: fastapi_views.pagination
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
