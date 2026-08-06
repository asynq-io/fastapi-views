# Caching & Conditional Requests

FastAPI Views ships two **independent** HTTP mechanisms that compose cleanly:

- **Server-side caching** — store a serialized response and serve it again without re-running the view (`CachedAPIView` + `@use_cache`), or cache the result of any async function (`@cache`).
- **Conditional requests** — let a client that already has a copy revalidate cheaply and receive `304 Not Modified` instead of the body (`ConditionalMixin`).

They are orthogonal: you can use either alone, or both together via `ConditionalCachedAPIView`.

| Want | Use |
|------|-----|
| Revalidation (`ETag` / `Last-Modified` / `304`), no server cache | `ConditionalMixin` + a view |
| Server cache (`X-Cache`, `Cache-Control`), no revalidation | `CachedAPIView` |
| Both | `ConditionalCachedAPIView` |
| Cache a plain async function's return value | `@cache("key", ttl=...)` |

Everything is exported from `fastapi_views.cache`: `Cache`, `cache`, `CacheControl`, `CacheHeaders`, `CacheMiddleware`, `CachedAPIView`, `ConditionalCachedAPIView`, `use_cache`.

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

`InMemoryCache(default_ttl=None)` keeps entries in a process-local dict (with per-key expiry); `default_ttl` applies whenever a write passes no `ttl`. It is fine for tests and single-process apps.

For production use the Redis backend — `pip install "fastapi-views[cache]"`, which pulls in `redis`:

```python
from redis.asyncio import Redis

from fastapi_views.cache.backends.redis import RedisCache

app.add_middleware(CacheMiddleware, backend=RedisCache(Redis.from_url("redis://localhost")))
```

`RedisCache(client)` takes an already-configured `redis.asyncio.Redis` client (so pooling, TLS and auth stay yours to configure); `ttl` is passed through as Redis' `ex`, and `pop` uses `GETDEL`.

A backend implements the `CacheBackend` interface (`get` / `set` / `delete` / `pop`, with keys and values being `str | bytes`), so you can plug in your own.

### Installing the backend later

`backend` on `CacheMiddleware` is optional; passing it simply registers it on the shared `cache` singleton. Omit it when the client is only created at startup and register the backend yourself:

```python
from contextlib import asynccontextmanager

from fastapi_views.cache import cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Redis.from_url("redis://localhost")
    cache.init_backend(RedisCache(client))
    yield
    await client.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CacheMiddleware)
```

The middleware itself is still required for `@use_cache` views: it injects the cache headers and writes the response body to the backend. Using `cache` as a [function decorator](#caching-any-async-function) or calling it directly needs only a backend.

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

`@use_cache(ttl=None, *, cache_control=None)` — `ttl` is the backend expiry in seconds (`None` means "until the backend evicts it"); `cache_control` overrides the header (a raw string or a `CacheControl`, see below).

Nothing is stored unless the response is worth storing: a view returning `None` (a `404`, or an empty body) is skipped, and the middleware only writes bodies whose status code is below `300` — so errors never poison the cache.

### Cache key

`build_key()` derives the key from the request path and the **sorted** query string (so ordering is irrelevant), hashed to a short digest. Path parameters are therefore part of the key already — `/items/1` and `/items/2` never collide. To vary it per header (e.g. a tenant), list the header names in `cache_key_headers`; headers absent from the request are simply left out:

```python
class ItemView(CachedAPIView, AsyncListAPIView):
    cache_key_headers = ("X-Tenant-Id",)
```

Override `build_key()` for a fully custom scheme — it takes no arguments and reads `self.request`:

```python
class ItemView(CachedAPIView, AsyncListAPIView):
    def build_key(self) -> str:
        return f"items:{self.request.query_params.get('page', '1')}"
```

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

`CacheControl` is a frozen dataclass and `render()` returns the header value in field-declaration order, so you can build one up front and reuse it. Bool fields render as bare directives (`no-store`), int fields as `name=value` (`max-age=30`); `False` / `None` are omitted.

---

## Caching any async function

Not everything worth caching is a whole response. `cache` — the shared `Cache` instance — is also a decorator for any async function; the return value is stored as JSON and validated back on a hit, so callers keep getting real objects rather than raw bytes:

```python
from fastapi_views.cache import cache


@cache("items:all", ttl=30)
async def load_items() -> list[ItemSchema]:
    return await repo.all()
```

`cache(key, ttl=None)`:

- **`key`** — a `str` / `bytes` key, a **format template**, or a callable.
- **`ttl`** — expiry in seconds, passed straight to the backend.

A template is expanded with the wrapped call's own arguments — `"{name}"` from a keyword argument, `"{0}"` from a positional one:

```python
@cache("{tenant}", ttl=60)
async def load_for(tenant: str) -> list[ItemSchema]: ...

await load_for(tenant="acme")  # cached under "acme"
```

!!! warning
    Templating only kicks in when the key **starts** with a `{placeholder}`:
    `"{tenant}"` and `"{0}:{1}"` are expanded, but `"items:{tenant}"` is stored
    verbatim — braces and all — so every tenant would share one entry.

Use a callable for anything a leading placeholder can't express, such as a prefixed key. It receives exactly the arguments the wrapped function was called with (so on a method, `self` is the first one):

```python
@cache(lambda tenant: f"items:{tenant}", ttl=60)
async def load_for(tenant: str) -> list[ItemSchema]: ...
```

The stored value is serialized with a `pydantic.TypeAdapter` built from the function's **return annotation**, so keep that type JSON-serializable. An annotation that cannot be resolved (a forward reference to a name that doesn't exist) degrades to `Any`.

!!! warning
    Always annotate the return type. A **missing** annotation resolves to `None`,
    and the resulting adapter accepts nothing but `null` — the value is written on
    the miss but fails validation on the next hit.

---

## Reading and invalidating entries

`Cache` is a thin async façade over the backend, and the same methods are available on the shared `cache` singleton or, inside a view, as `self.cache`:

| Method | Purpose |
|--------|---------|
| `await cache.get(key)` | stored value (`str` or `bytes`) or `None` |
| `await cache.set(key, value, ttl=None)` | store a value |
| `await cache.delete(key)` | drop an entry |
| `await cache.pop(key)` | read **and** drop it atomically |
| `cache.init_backend(backend)` | install/replace the backend |

Use `delete` to invalidate on writes — for the function decorator, rebuild the key the same way the decorator does:

```python
class ItemViewSet(CachedAPIView, AsyncAPIViewSet):
    async def update(self, id: UUID, item: ItemSchema) -> ItemSchema:
        saved = await repo.save(item)
        await self.cache.delete("items:all")
        return saved
```

There is no namespace/prefix or bulk-invalidation helper: keys are exactly what `build_key()` or your key template produced, so pick a scheme you can reconstruct (or lean on short `ttl`s). Reading `cache.backend` before a backend is installed raises `ValueError("Cache backend not set")`.

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

`ConditionalCachedAPIView` is `ConditionalMixin` + `CachedAPIView`: because the cached body flows through `finalize_response()`, a cache **hit** can still be downgraded to `304`, so a revalidating client is served neither the recomputation nor the body.

```python
from fastapi_views.cache import ConditionalCachedAPIView, use_cache


class ItemView(ConditionalCachedAPIView, AsyncReadOnlyAPIViewSet):
    cache_key_headers = ("X-Tenant-Id",)
    etag = True                  # hashed from the (possibly cached) body
    conditional_requests = True  # also document retrieve's manual validator

    @use_cache(ttl=30)
    async def list(self) -> list[ItemSchema]:
        return await repo.all()

    async def retrieve(self, id: UUID) -> ItemSchema | Response:
        item = await repo.get(id)
        return self.check_last_modified(item.updated_at) or item
```

The automatic (`etag` / `last_modified`) opt-ins are what make a hit downgradeable, since the validator is derived from the cached body. The manual `check_*` helpers run *inside* the endpoint, which a cache hit skips entirely — so on a cached action, use the automatic form.

---

## OpenAPI documentation

Validator headers and the `304` response are added to the schema **only when the view actually emits them**, so docs stay honest:

- `etag = True` documents `ETag` on the success response and a `304` for safe methods.
- `last_modified = True` does the same for `Last-Modified`.
- For the manual pattern (where validators are produced imperatively and can't be introspected), set `conditional_requests = True` to document both validator headers and the `304`.

`CachedAPIView` documents its `X-Cache` (always present), `Cache-Control` and `Vary` headers on `list` / `retrieve` responses automatically, via the exported `CacheHeaders` model. Override `get_response_headers(action)` to document them on other actions or to swap in your own model.

---

## Complete example

```python
--8<-- "examples/cache.py"
```
