# Caching & Conditional Requests

Server-side response caching and HTTP conditional-request handling. Import from `fastapi_views.cache`.

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

::: fastapi_views.cache.cache.Cache
    handler: python
    options:
        show_root_heading: true
        members_order: source
        show_signature_annotations: true

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
