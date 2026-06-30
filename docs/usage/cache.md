# Caching & Conditional Requests

FastAPI Views ships two **independent** HTTP mechanisms that compose cleanly:

- **Server-side caching** — store a serialized response and serve it again without re-running the view (`CachedAPIView` + `@use_cache`).
- **Conditional requests** — let a client that already has a copy revalidate cheaply and receive `304 Not Modified` instead of the body (`ConditionalMixin`).

They are orthogonal: you can use either alone, or both together via `ConditionalCachedAPIView`.

| Want | Use |
|------|-----|
| Revalidation (`ETag` / `Last-Modified` / `304`), no server cache | `ConditionalMixin` + a view |
| Server cache (`X-Cache`, `Cache-Control`), no revalidation | `CachedAPIView` |
| Both | `ConditionalCachedAPIView` |

---

## Setup

Caching needs a backend, installed once at the app level with `CacheMiddleware`. Every cached view shares it.

```python
from fastapi import FastAPI

from fastapi_views.cache import CacheMiddleware
from fastapi_views.cache.backends.memory import InMemoryCache

app = FastAPI()
app.add_middleware(CacheMiddleware, backend=InMemoryCache())
```

For production use the Redis backend (requires `redis`):

```python
from redis.asyncio import Redis

from fastapi_views.cache.backends.redis import RedisCache

app.add_middleware(CacheMiddleware, backend=RedisCache(Redis.from_url("redis://localhost")))
```

A backend implements the `CacheBackend` interface (`get` / `set` / `delete` / `pop`), so you can plug in your own.

> `ConditionalMixin` on its own needs **no** middleware or backend — it works purely from request/response headers.

---

## Caching with `@use_cache`

Subclass `CachedAPIView` and decorate an endpoint with `@use_cache`. On a miss the view runs and its serialized body is stored; on a hit the stored body is returned without running the view. Responses carry `X-Cache: HIT|MISS` and, when a `ttl` is set, `Cache-Control: max-age=<ttl>`.

```python
from fastapi_views.cache import CachedAPIView, use_cache
from fastapi_views.views.api import AsyncListAPIView


class ItemView(CachedAPIView, AsyncListAPIView):
    response_schema = ItemSchema

    @use_cache(ttl=30)
    async def list(self) -> list[ItemSchema]:
        return await repo.all()
```

`@use_cache(ttl=None, *, cache_control=None)` — `ttl` is the backend expiry in seconds; `cache_control` overrides the header (a raw string or a `CacheControl`, see below).

### Cache key

The key is derived from the request path and **sorted** query string, so ordering is irrelevant. To vary it per header (e.g. a tenant), list the header names in `cache_key_headers`:

```python
class ItemView(CachedAPIView, AsyncListAPIView):
    cache_key_headers = ("X-Tenant-Id",)
```

Override `build_key()` for a fully custom scheme.

### `Vary` and shared caches

`cache_key_headers` keys the **server-side** cache. Downstream caches (the browser, a shared CDN/proxy) need to key on the same headers, or one client could be served another's response. So every cached response automatically emits a `Vary` header built from `cache_key_headers`, plus any extra request headers you declare in `vary` (headers the server doesn't key on but the response still depends on):

```python
class ItemView(CachedAPIView, AsyncListAPIView):
    cache_key_headers = ("X-Tenant-Id",)   # also emitted as Vary
    vary = ("Accept-Encoding",)            # extra, beyond the key
    # -> Vary: X-Tenant-Id, Accept-Encoding
```

!!! warning
    For per-user or per-tenant data behind a **shared** cache, also mark the
    response `private` (see below) so shared caches don't store it at all —
    `Vary` alone keeps separate copies, `private` keeps it browser-only.

### Cache-Control directives

For anything beyond `max-age` (which `ttl` sets by default), pass a `CacheControl` to compose directives safely instead of hand-writing the string:

```python
from fastapi_views.cache import CacheControl

class ItemView(CachedAPIView, AsyncListAPIView):
    @use_cache(ttl=300, cache_control=CacheControl(private=True, stale_while_revalidate=10))
    async def list(self) -> list[ItemSchema]:
        ...
    # -> Cache-Control: private, max-age=300, stale-while-revalidate=10
```

`ttl` fills in `max-age` when the `CacheControl` doesn't set it, so `ttl` (server storage) and the client freshness stay in sync by default; set `max_age` explicitly to decouple them. Supported fields: `max_age`, `s_maxage`, `public`, `private`, `no_store`, `no_cache`, `must_revalidate`, `immutable`, `stale_while_revalidate`, `stale_if_error`. A raw string still works as an escape hatch (`cache_control="no-store"`).

---

## Conditional requests with `ConditionalMixin`

`ConditionalMixin` adds `ETag` / `Last-Modified` validators and `304 Not Modified` handling. There are two ways to opt in.

### Automatic

Set `etag = True` (a strong ETag is hashed from the serialized body) and/or `last_modified = True` together with a `get_last_modified()` override. The body is built, then downgraded to `304` if the client's validator still matches.

```python
class ItemView(ConditionalMixin, AsyncRetrieveAPIView):
    etag = True  # ETag hashed from the response body

    async def retrieve(self, id: UUID) -> ItemSchema:
        return await repo.get(id)
```

### Manual (cheap)

Hashing the body still requires serializing it. If you already have a cheap validator — a `version` column or `updated_at` — compare it **before** building the body and short-circuit. This skips serialization entirely when the client is current.

```python
class ItemView(ConditionalMixin, AsyncRetrieveAPIView):
    conditional_requests = True  # document the 304 in OpenAPI (see below)

    async def retrieve(self, id: UUID) -> ItemSchema | Response:
        item = await repo.get(id)
        # Last-Modified
        return self.check_last_modified(item.updated_at) or item
```

`check_last_modified(dt)` returns a `304` when the client's copy is current, otherwise stamps `Last-Modified` on the upcoming `200` and returns `None` — so `return self.check_last_modified(dt) or item` reads naturally. `check_etag(tag)` is the `ETag` counterpart for versioned models:

```python
async def retrieve(self, id: UUID) -> ItemSchema | Response:
    item = await repo.get(id)
    return self.check_etag(str(item.version)) or item
```

A raw value like `str(item.version)` is automatically quoted to a valid entity-tag (`"7"`); pass `W/"..."` for a weak validator.

### Lower-level helpers

If you need finer control:

| Method | Purpose |
|--------|---------|
| `if_none_match` / `if_modified_since` | the parsed request validators |
| `etag_matches(tag)` / `not_modified_since(dt)` | None-safe matchers |
| `not_modified(*, etag=None, last_modified=None)` | build a bare `304` |
| `set_etag(tag)` / `set_last_modified(dt)` | stamp a validator on the response (any 2xx, e.g. a `201`) |

`set_*` is handy on writes — stamp the validator a `POST` returns so the client can revalidate next time:

```python
async def create(self, item: ItemSchema) -> ItemSchema:
    saved = await repo.save(item)
    self.set_last_modified(saved.updated_at)
    return saved
```

---

## Combining both

`ConditionalCachedAPIView` is `ConditionalMixin` + `CachedAPIView`: a cache hit can be downgraded to `304`, so a revalidating client is served neither the recomputation nor the body.

```python
from fastapi_views.cache import ConditionalCachedAPIView, use_cache


class ItemView(ConditionalCachedAPIView, AsyncReadOnlyAPIViewSet):
    cache_key_headers = ("X-Tenant-Id",)
    conditional_requests = True

    @use_cache(ttl=30)
    async def list(self) -> list[ItemSchema]:
        return await repo.all()

    async def retrieve(self, id: UUID) -> ItemSchema | Response:
        item = await repo.get(id)
        return self.check_last_modified(item.updated_at) or item
```

---

## OpenAPI documentation

Validator headers and the `304` response are added to the schema **only when the view actually emits them**, so docs stay honest:

- `etag = True` documents `ETag` on the success response and a `304` for safe methods.
- `last_modified = True` does the same for `Last-Modified`.
- For the manual pattern (where validators are produced imperatively and can't be introspected), set `conditional_requests = True` to document both validator headers and the `304`.

`CachedAPIView` documents its `X-Cache`, `Cache-Control`, and `Vary` headers on `list` / `retrieve` responses automatically.

---

## Complete example

```python
--8<-- "examples/cache.py"
```
