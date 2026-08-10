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

Nothing is stored unless the response is worth storing: a view returning `None` (a `404`, or an empty body) is skipped, and the middleware only writes bodies whose status code is below `300` — so errors never poison the cache. (The single exception is the conditional `304` [described below](#a-revalidating-client-warms-the-cache), where the *successful* body built before the downgrade is what gets written.)

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

### Serialization of the cached value

The stored value is serialized with a `pydantic.TypeAdapter` built from the function's **return annotation**, so keep that type JSON-serializable. An annotation that cannot be resolved — a forward reference to a missing name, or no annotation at all — degrades to `Any`, which round-trips any JSON-compatible value safely.

Annotating is still worth it, because the annotation is what **reconstructs** the object on a hit: with `-> ItemSchema` a hit returns an `ItemSchema`, while under the `Any` fallback the same function returns the plain `dict` the JSON decoded to. An explicit `-> None` is honoured literally as `NoneType`, so `@cache` on a function that really returns something else is a genuine mis-annotation (the value is written on the miss and fails validation on the next hit), not a trap you fall into by omission.

Adapters are memoised in a bounded 512-entry cache keyed by the annotation, so repeated decoration of the same type is cheap; an unhashable annotation (e.g. `Annotated[int, {"exotic": True}]`) simply gets a fresh, uncached adapter.

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

`last_modified = True` is the same opt-in for the date validator, but it has nothing to send until you supply the timestamp:

```python
class ItemView(ConditionalMixin, AsyncRetrieveAPIView):
    last_modified = True

    def get_last_modified(self) -> datetime | None:
        return repo.last_change()

    async def retrieve(self, id: UUID) -> ItemSchema:
        return await repo.get(id)
```

!!! warning
    The `get_last_modified()` override is **mandatory** with `last_modified = True`.
    The default returns `None`, so the flag documents the header in OpenAPI but the
    response carries no `Last-Modified` and never downgrades to `304` — silently,
    with no error. `get_last_modified()` is called once per response, after the body
    is built, and may consult `self.request` / the view's state.

### Manual (cheap)

Hashing the body still requires serializing it. If you already have a cheap validator — a `version` column or `updated_at` — compare it **before** building the body and short-circuit. This skips serialization entirely when the client is current.

```python
class ItemView(ConditionalMixin, AsyncRetrieveAPIView):
    conditional_requests = True  # document the 304 in OpenAPI (see below)

    async def retrieve(self, id: UUID) -> ItemSchema | Response:
        item = await repo.get(id)
        return self.check_last_modified(item.updated_at) or item
```

`check_last_modified(dt)` returns a `304` when the client's copy is current, otherwise stamps `Last-Modified` on the upcoming `200` and returns `None` — so `return self.check_last_modified(dt) or item` reads naturally. `check_etag(tag)` is the `ETag` counterpart for versioned models:

```python
async def retrieve(self, id: UUID) -> ItemSchema | Response:
    item = await repo.get(id)
    return self.check_etag(str(item.version)) or item
```

A raw value like `str(item.version)` is automatically quoted to a valid entity-tag (`"7"`); pass `W/"..."` for a weak validator.

### Matching rules

How a request's validators are compared, for both opt-ins:

- **`If-None-Match` wins over `If-Modified-Since`** ([RFC 7232](https://datatracker.ietf.org/doc/html/rfc7232#section-3.3)). When a request carries both, the date is ignored entirely: a non-matching ETag yields `200` even if the client's date is newer, and a matching ETag yields `304` even if the client's date is older.
- `*` in `If-None-Match` always matches; comma-separated lists are supported; `W/"x"` and `"x"` compare equal (the weak prefix is stripped before comparing).
- An unparseable `If-Modified-Since` is treated as absent, so the client gets the full `200`.
- **Naive datetimes are accepted** by `check_last_modified()`, `not_modified()` and `set_last_modified()`: they are assumed to be UTC and truncated to whole seconds, matching the one-second resolution of an HTTP date.

### Safe vs unsafe methods

Validators are stamped on **any** successful (`2xx`) response, but only `GET` and `HEAD` are ever downgraded to `304`:

```python
class ItemView(ConditionalMixin, AsyncCreateAPIView):
    etag = True  # -> ETag on the 201, never a 304
```

A `POST` / `PUT` / `PATCH` view with `etag = True` therefore sends the `ETag` on its `201` (useful — the client can revalidate on the next `GET`) and keeps returning the body even when the client echoes a matching `If-None-Match`. The `304` is likewise omitted from the OpenAPI schema for those methods.

When a downgrade does happen, the `304` carries over the headers a revalidation response is allowed to repeat: `ETag`, `Last-Modified`, `Cache-Control`, `Expires`, `Vary` and `X-Cache`. Everything else (including the body and `Content-Length`) is dropped.

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

### A revalidating client warms the cache

The two mechanisms also cooperate on a **miss**. When the view runs, the body is serialized and only *then* compared against the client's validator, so a request that ends as a `304` has produced a full representation that would otherwise be thrown away. `ConditionalCachedAPIView` hands that pre-downgrade body to the cache, so the entry is written even though the client receives no body:

| Request | Response | Cache after |
|---------|----------|-------------|
| `GET` (cold) | `200`, `X-Cache: MISS` | populated |
| `GET` + matching `If-None-Match` (cold) | `304`, `X-Cache: MISS` | **populated** |
| `GET` (warm) | `200`, `X-Cache: HIT` | unchanged |
| `GET` + matching `If-None-Match` (warm) | `304`, `X-Cache: HIT` | unchanged |

So a fleet of revalidating clients warms the cache for everyone instead of re-running the view on every request. Two details follow from this:

- What is stored is always the **full representation**, never the empty `304`, so a later non-conditional request is served a proper `200` `HIT` without re-running the view.
- The `304` itself still carries the cache headers of the request that produced it — `X-Cache: MISS`, plus `Cache-Control` and `Vary` — because the entry was written by *this* request. The write happens exactly once per miss; `CacheMiddleware` remains the single writer.

!!! warning
    This only works on `ConditionalCachedAPIView`. Hand-rolling
    `class ItemView(ConditionalMixin, CachedAPIView, ...)` does **not** get it:
    `ConditionalMixin.finalize_response()` does not call `super()`, so the body is
    never recorded, the `304` reaching the middleware has no body to persist, and
    the cache stays permanently cold — every revalidation re-runs the view. Prefer
    `ConditionalCachedAPIView`, which overrides `finalize_response()` to record the
    body before delegating to the mixin.

---

## OpenAPI documentation

Validator headers and the `304` response are added to the schema **only when the view actually emits them**, so docs stay honest:

| Flag | Documented on the success status | `304 Not Modified` |
|------|----------------------------------|--------------------|
| `etag = True` | `ETag` | safe methods only |
| `last_modified = True` | `Last-Modified` | safe methods only |
| `conditional_requests = True` | `ETag` **and** `Last-Modified` | safe methods only |
| none of them | nothing | never |

- `conditional_requests = True` exists for the manual pattern: validators produced imperatively can't be introspected, so it documents both of them (and the `304`) without changing runtime behaviour. Combine it with `etag` / `last_modified` freely — the header sets are unioned.
- The `304` entry is described as `Not Modified` and repeats the same header map as the success response. It is added only for `GET` / `HEAD`, so a `POST` view with `etag = True` documents `ETag` on its `201` and no `304` — matching what it actually returns.
- `ETag` is documented as `type: string`; `Last-Modified` as `type: string, format: http-date`.
- The flags are **class-level**, not per-action, so on a viewset they apply to every registered action. `supports_conditional_requests()` reports whether any of them is set.

`CachedAPIView` documents its `X-Cache` (always present), `Cache-Control` and `Vary` headers on `list` / `retrieve` responses automatically, via the exported `CacheHeaders` model. Override `get_response_headers(action)` to document them on other actions, to swap in your own model, or to return `None` for an action that isn't actually cached (as the example below does). When both apply to the same status code, the cache headers and the validators are merged into one header map.

---

## Complete example

```python
--8<-- "examples/cache.py"
```
