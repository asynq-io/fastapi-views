# Caching & Conditional Requests

Server-side response caching and HTTP conditional-request handling. Import from `fastapi_views.cache`, which exports `Cache`, `cache`, `CacheControl`, `CacheHeaders`, `CacheMiddleware`, `CachedAPIView`, `ConditionalCachedAPIView` and `use_cache`.

The Redis backend requires the `cache` extra: `pip install "fastapi-views[cache]"`.

For a walkthrough see [Caching & Conditional Requests](../usage/cache.md).

---

## Views and decorator

::: fastapi_views.cache.view
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

## Conditional requests

`ConditionalMixin` provides the ETag / `Last-Modified` validators and `304` handling reused by `ConditionalCachedAPIView`. It can be combined with any view independently of caching.

::: fastapi_views.views.mixins.ConditionalMixin
    handler: python
    options:
        show_root_heading: true
        members_order: source
        show_signature_annotations: true

---

## Middleware and backends

::: fastapi_views.cache.middleware.CacheMiddleware
    handler: python
    options:
        show_root_heading: true
        show_signature_annotations: true

`fastapi_views.cache.cache` is the shared `Cache` instance the views, the middleware and the `@cache` decorator all use; `CacheMiddleware(backend=...)` (or `cache.init_backend(...)`) installs its backend.

::: fastapi_views.cache.cache.Cache
    handler: python
    options:
        show_root_heading: true
        members_order: source
        show_signature_annotations: true
        members:
            - backend
            - init_backend
            - get
            - set
            - delete
            - pop
            - __call__

Keys and values are `str | bytes` (`KeyT` / `EncodableT` in `fastapi_views.cache.backends`).

::: fastapi_views.cache.backends.abc.CacheBackend
    handler: python
    options:
        show_root_heading: true
        members_order: source
        show_signature_annotations: true

::: fastapi_views.cache.backends.memory.InMemoryCache
    handler: python
    options:
        show_root_heading: true
        show_signature_annotations: true

::: fastapi_views.cache.backends.redis.RedisCache
    handler: python
    options:
        show_root_heading: true
        show_signature_annotations: true
