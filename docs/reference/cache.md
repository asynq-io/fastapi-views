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

`ConditionalMixin` provides the ETag / `Last-Modified` validators and `304` handling reused by `ConditionalCachedAPIView`. It can be combined with any view independently of caching and needs no middleware or backend — it works purely from request and response headers.

When you *do* want caching as well, subclass `ConditionalCachedAPIView` rather than mixing `ConditionalMixin` into `CachedAPIView` by hand: `finalize_response` below does not call `super()`, so a hand-rolled combination loses the cache write on a `304`-downgraded miss.

::: fastapi_views.views.mixins.ConditionalMixin
    handler: python
    options:
        show_root_heading: true
        members_order: source
        show_signature_annotations: true

The validator headers documented in OpenAPI come from this model; `ConditionalMixin` contributes only the ones the view can actually emit.

::: fastapi_views.views.mixins.ConditionalHeaders
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
