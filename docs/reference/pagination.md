# Pagination

Page response models and type aliases used by the filter and generic view systems. Import from `fastapi_views.pagination`.

## Page types

All page models inherit from `BasePage[T]`, which provides `items: list[T]` (defaulting to `[]`).

| Class | Paired filter | Fields (in addition to `items`) |
|-------|---------------|---------------------------------|
| `BasePage[T]` | — | — |
| `NumberedPage[T]` | `PaginationFilter` | `current_page: int`, `page_size: int`, `has_more: bool \| None`, `total_pages: int \| None`, `total_items: int \| None` |
| `OffsetPage[T]` | `OffsetLimitFilter` | `offset: int`, `limit: int`, `has_more: bool \| None`, `total_items: int \| None` |
| `CursorPage[T]` | `CursorPaginationFilter` | `cursor: Cursor \| None`, `next_page: Cursor \| None`, `previous_page: Cursor \| None` |

`current_page`, `page_size`, `offset` and `limit` are required; every count / `has_more` field is optional and defaults to `None`, so a repository can skip the extra `COUNT(*)`.

Generic list views pick the container automatically from the view's `filter` class — `PaginationFilter` (and its subclasses, including the combined `Filter`) yields a `NumberedPage`, `OffsetLimitFilter` an `OffsetPage`, `CursorPaginationFilter` a `CursorPage`; with no filter the list action returns a plain `list`. See [Filters](filters.md).

```python
>>> NumberedPage[Item](items=[], current_page=1, page_size=10, total_items=25).model_dump()
{'items': [], 'current_page': 1, 'page_size': 10, 'has_more': None,
 'total_pages': None, 'total_items': 25}
```

## Cursors

`Cursor` is `Annotated[str, ...]` with an `AfterValidator` that base64-decodes incoming values and a `PlainSerializer` that base64-encodes on JSON serialization (`when_used="json"`). Consumers therefore see opaque cursor strings, while repository implementations work with plain values.

| Function | Description |
|----------|-------------|
| `encode_cursor(cursor)` | URL-safe base64 encoding |
| `decode_cursor(cursor)` | URL-safe base64 decoding; returns the input unchanged when it is not valid base64 |

```python
>>> CursorPage[Item](items=[], cursor="abc").model_dump(mode="json")["cursor"]
'YWJj'
>>> CursorPage[Item](items=[], cursor="YWJj").cursor
'abc'
```

The lenient `decode_cursor` fallback means a client that sends an already-plain cursor still works.

## Type aliases

| Alias | Type |
|-------|------|
| `PageNumber` | `PositiveInt` |
| `PageSize` | `Annotated[int, Interval(gt=0, le=MAX_PAGE_SIZE)]` |
| `Cursor` | `str` with base64 decode validator / encode serializer |

`MAX_PAGE_SIZE` is read from the `MAX_PAGE_SIZE` environment variable at import time and defaults to `500`. It caps the `page_size` query parameter of `PaginationFilter` and `CursorPaginationFilter` (both of which default `page_size` to `100`).

---

::: fastapi_views.pagination
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
