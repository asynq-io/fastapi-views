# FastAPI Views

![Tests](https://github.com/asynq-io/fastapi-views/workflows/Tests/badge.svg)
![Build](https://github.com/asynq-io/fastapi-views/workflows/Publish/badge.svg)
![License](https://img.shields.io/github/license/asynq-io/fastapi-views)
![Mypy](https://img.shields.io/badge/mypy-checked-blue)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/charliermarsh/ruff)
[![Pydantic v2](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pydantic/pydantic/main/docs/badge/v2.json)](https://docs.pydantic.dev/latest/contributing/#badges)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
![Python](https://img.shields.io/pypi/pyversions/fastapi-views)
![Format](https://img.shields.io/pypi/format/fastapi-views)
![PyPi](https://img.shields.io/pypi/v/fastapi-views)

**Class-based views, CRUD utilities, and production-ready patterns for FastAPI.**

FastAPI Views brings Django REST Framework-style class-based views to FastAPI — without giving up type safety or dependency injection. Define a full CRUD resource by inheriting one class; routes, status codes, and OpenAPI docs are wired up automatically.

## Features

- **Class-based views** — `View`, `APIView`, `APIViewSet`, and `GenericViewSet` at three levels of abstraction; mix-in only the actions you need
- **Full CRUD in one class** — `list`, `create`, `retrieve`, `update`, `partial_update`, `destroy` with correct HTTP semantics out of the box (`201 Created`, `204 No Content`, `Location` header, etc.)
- **Generic views with the repository pattern** — plug in any data source (SQLAlchemy, Motor, plain dicts) via a simple protocol; no ORM dependency
- **Bulk actions** — `AsyncBulkAPIViewSet` adds bulk create, per-item bulk update, filtered update, and filtered delete on a single `/bulk` route
- **JSON Patch** — RFC 6902 `PATCH` support with `application/json-patch+json` request bodies (optional extra)
- **DRF-style filters** — `ModelFilter`, `OrderingFilter`, `SearchFilter`, `PaginationFilter`, `OffsetLimitFilter`, `CursorPaginationFilter`, `FieldsFilter`, and a combined `Filter` class; built-in SQLAlchemy and Python object resolvers
- **RFC 9457 Problem Details** — every error response is machine-readable; built-in classes for the most common cases; custom errors auto-register in the OpenAPI spec
- **Fast Pydantic v2 serialization** — `TypeAdapter` cached per schema type avoids the double validation/model instantiation that FastAPI does by default, reducing per-request overhead
- **Response caching** — `CachedAPIView`, the `@cache` decorator, and `CacheMiddleware`, with in-memory and Redis backends (optional extra)
- **Conditional requests** — `ConditionalMixin` emits `ETag` / `Last-Modified` validators and answers `304 Not Modified` from a cheap version column, without serialising a body
- **Documented response headers** — declare a `ResponseHeaders` model on a view, action, or router and the headers show up in the OpenAPI spec
- **Server-Sent Events** — `ServerSentEventsAPIView` and `@sse_route` handle framing, content-type, and Pydantic validation automatically
- **WebSockets** — `WebSocketAPIView` handles connection lifecycle, per-class connection tracking, broadcast helpers, and Pydantic validation of binary frames; disconnects and failed handshakes are cleaned up without masking the original error
- **Authentication & authorization** — bearer-token auth built on FastAPI's `Security` system: `JWTAuth` (JWKS import, claims validation, token minting), hierarchical OAuth2 scope enforcement via `requires(*scopes)`, header API-key auth (`APIKeyAuth`, `ConstAPIKeyAuth`), and an Auth0 integration (optional extras)
- **Internationalization (i18n)** — per-request locale detection (query param, cookie, `Accept-Language`) with configurable locale fallbacks, pluggable translation managers (JSON files, in-memory, or custom), `str.format`/Jinja2 formatters, and `Translated[str]` model fields; built-in error messages are translatable out of the box (optional extra)
- **Async and sync support** — every class ships an `Async` and a synchronous variant; sync endpoints run in a thread pool
- **One-call setup** — `configure_app(app)` registers error handlers, Prometheus middleware, OpenTelemetry instrumentation, locale detection, optional request logging, and a concurrency limit
- **Prometheus metrics** — `/metrics` endpoint with request count, latency histogram, and in-flight requests (optional extra)
- **OpenTelemetry tracing** — `correlation_id` injected into every error response for easy trace correlation (optional extra)
- **Structured request logging** — opt-in `RequestLoggingMiddleware` backed by `structlog`, enabled with `configure_app(enable_request_logging_middleware=True)` (optional extra)
- **Readable OpenAPI operation IDs** — `list_item`, `create_item`, `retrieve_item` instead of FastAPI's long path-derived defaults
- **CLI** — export a static `openapi.json` / `openapi.yaml` without starting a server

---

## Installation

```shell
pip install fastapi-views
```

### Optional extensions

| Extra | What it adds |
|---|---|
| `uvloop` | `uvloop` event loop for better async performance |
| `uvicorn` | `uvicorn` ASGI server |
| `prometheus` | Prometheus metrics middleware (`/metrics` endpoint) |
| `opentelemetry` | OpenTelemetry tracing instrumentation |
| `cli` | CLI tool for generating static OpenAPI JSON/YAML files |
| `structlog` | Structured request logging via `structlog` |
| `websockets` | `websockets` library for `WebSocketAPIView` |
| `jose` | JWT authentication (`joserfc`) — `JWTAuth` |
| `auth0` | Auth0 token validation (`auth0-api-python`) |
| `i18n` | Internationalization — `babel` and `jinja2` formatters |
| `cache` | Redis cache backend (`redis`) |
| `jsonpatch` | JSON Patch support (`jsonpatch`, `jsonpointer`) |
| `sqlargon` | SQLAlchemy repositories via `sqlargon[pagination]` |
| `standard` | Curated bundle: `uvloop`, `uvicorn`, `starlette-exporter`, `opentelemetry-instrumentation-fastapi`, `typer` |

Install all extras at once:

```shell
pip install 'fastapi-views[all]'
```

---

## Quick start

```python
from typing import ClassVar, Optional
from uuid import UUID

from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.views.viewsets import AsyncAPIViewSet


class ItemSchema(BaseModel):
    id: UUID
    name: str
    price: int


class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema

    # In-memory store — swap for a real repository in production
    items: ClassVar[dict[UUID, ItemSchema]] = {}

    async def list(self) -> list[ItemSchema]:
        return list(self.items.values())

    async def create(self, item: ItemSchema) -> ItemSchema:
        self.items[item.id] = item
        return item

    async def retrieve(self, id: UUID) -> Optional[ItemSchema]:
        return self.items.get(id)

    async def update(self, id: UUID, item: ItemSchema) -> ItemSchema:
        self.items[id] = item
        return item

    async def destroy(self, id: UUID) -> None:
        self.items.pop(id, None)


router = ViewRouter(prefix="/items")
router.register_view(ItemViewSet)

app = FastAPI(title="My API")
app.include_router(router)

configure_app(app)
```

This registers the following routes automatically:

| Method | Path | Action | Status code |
|--------|------|--------|-------------|
| `GET` | `/items` | `list` | 200 |
| `POST` | `/items` | `create` | 201 |
| `GET` | `/items/{id}` | `retrieve` | 200 |
| `PUT` | `/items/{id}` | `update` | 200 |
| `DELETE` | `/items/{id}` | `destroy` | 204 |

---

## Features

### Class-based views

Three levels of abstraction let you choose the right amount of automation:

- **`View`** — low-level base class. You control routing with `@get`, `@post`, `@put`, `@patch`, `@delete` decorators and return `Response` objects directly. Zero magic.
- **`APIView`** — adds Pydantic v2 serialization and error handling. Return plain dicts or model instances; the view serializes them automatically.
- **`APIViewSet` / `AsyncAPIViewSet`** — combines multiple CRUD actions into one class. Mix and match with provided mixin classes (`ListAPIView`, `CreateAPIView`, etc.) for exactly the surface you need.

### Generic views with the repository pattern

`GenericViewSet` and `AsyncGenericViewSet` implement all CRUD logic for you. Provide a `repository` object that satisfies the `Repository` / `AsyncRepository` protocol and the view handles the rest — including `409 Conflict` on duplicate creates and `404 Not Found` on missing resources. Lifecycle hooks (`before_create`, `after_create`, `before_update`, `after_update`) let you add custom logic without overriding entire actions.

See [Generic Views](usage/generics.md) for a full example.

### Filters, pagination, and sorting

The `Filter` system mirrors Django REST Framework's `FilterSet` API:

- **`ModelFilter`** — filter by model field values (e.g. `?name=Alice`)
- **`OrderingFilter`** — sort by whitelisted fields using `?sort=name` or `?sort=-created_at`
- **`SearchFilter`** — full-text search across multiple fields with `?q=…`
- **`PaginationFilter`** — page-number pagination returning a `NumberedPage`
- **`CursorPaginationFilter`** — cursor-based pagination returning a `CursorPage`
- **`FieldsFilter`** — sparse fieldsets; return only requested fields with `?fields=id,name`
- **`Filter`** — convenience class combining all of the above

Built-in resolvers for SQLAlchemy and plain Python objects translate filter objects into queries with zero glue code.

See [Filters](usage/filters.md) for usage details.

### Bulk actions

`AsyncBulkAPIViewSet` (and its sync counterpart) add bulk endpoints on a single `/bulk`
route, distinguished by HTTP method: `POST` creates many, `PUT` updates each item by its own
key, `PATCH` updates every row matching a filter, and `DELETE` removes them. They delegate to
`create_many` / `bulk_update` / `update_many` / `delete_many` on the repository.

See [Bulk actions](usage/bulk.md).

### JSON Patch

RFC 6902 `PATCH` support: accept an `application/json-patch+json` document, apply it to the
current representation, and persist the result. Requires the `jsonpatch` extra.

See [JSON Patch](usage/jsonpatch.md).

### Response caching and conditional requests

`CachedAPIView`, the `@cache` decorator, and `CacheMiddleware` cache rendered responses in an
in-memory or Redis backend (`cache` extra) and emit `Cache-Control` headers.

Independently, `ConditionalMixin` handles HTTP revalidation. Compare a cheap validator you
already have — a version column, an `updated_at` — and skip building the body entirely when
the client is current:

```python
class ItemView(ConditionalMixin, AsyncRetrieveAPIView):
    async def retrieve(self, item_id: int) -> Item | Response:
        item = await self.get_item(item_id)
        return self.check_etag(str(item.version)) or item
```

`check_etag` returns a `304 Not Modified` when `If-None-Match` matches, and otherwise stamps
the `ETag` on the response it is about to send. `check_last_modified` is the
`If-Modified-Since` counterpart.

See [Caching](usage/cache.md).

### RFC 9457 Problem Details error handling

Every error response is an `ErrorDetails` model conforming to [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html):

```json
{
  "type": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.4",
  "title": "Not Found",
  "status": 404,
  "detail": "The requested resource was not found.",
  "instance": "/items/abc",
  "errors": []
}
```

Built-in error classes cover the most common cases: `NotFound`, `BadRequest`, `Conflict`, `Unauthorized`, `Forbidden`, `Throttled`, `UnprocessableEntity`, `InternalServerError`, and `Unavailable`. Creating a custom error class is as simple as subclassing `APIError`:

```python
from fastapi_views.exceptions import APIError
from starlette.status import HTTP_402_PAYMENT_REQUIRED

class PaymentRequired(APIError):
    """Payment is required to access this resource."""
    status = HTTP_402_PAYMENT_REQUIRED
```

The error's Pydantic model is automatically registered in the OpenAPI spec for every route that may raise it.

### Smart serialization

Serialization uses Pydantic v2's `TypeAdapter`, which is cached per schema type. This means the first request to an endpoint pays the reflection cost; subsequent requests reuse the cached serializer. All standard Pydantic options (`by_alias`, `include`, `exclude`, `context`) are supported.

### Server-Sent Events (SSE)

`ServerSentEventsAPIView` and the `@sse_route` decorator make streaming real-time events straightforward. The view handles content-type negotiation, connection headers, and SSE framing automatically. Data is serialized and validated using the same Pydantic pipeline as regular views.

See [Server-Sent Events](usage/sse.md).

### WebSockets

`WebSocketAPIView` manages the full connection lifecycle — accept, per-class connection
tracking, broadcast helpers, and graceful disconnect handling — and validates incoming
frames through the same Pydantic pipeline as the rest of the library.

See [WebSockets](usage/websockets.md).

### Authentication & authorization

A lightweight bearer-token layer built on FastAPI's `Security` system. `AuthBase` turns a
scheme into a reusable `authenticated()` dependency; `ScopesAuth` adds scope enforcement via
`requires(*scopes)`, validated by default with a `HierarchicalScopeValidator`. `JWTAuth`
(requires the `jose` extra) implements `ScopesAuth` on top of `joserfc` — configured with a
`JWTConfig`, it verifies claims, imports or fetches a JWKS (`fetch_jwks`), exposes the public
key set as `jwks`, and can mint tokens (`encode`, `create_access_token`). Auth0 validation
lives in `fastapi_views.integrations.auth0` (`auth0` extra). Also included: header-based
API-key auth (`APIKeyAuth`, and `ConstAPIKeyAuth` for constant-time comparison against a
fixed key), `AutoScopesAuthView` to derive per-action scopes on a view, and
`with_test_user(...)` to bypass auth in tests.

See [Authentication](usage/auth.md).

### Internationalization (i18n)

`LocaleMiddleware` detects the request locale (query param, cookie, then `Accept-Language`)
and exposes it through a `ContextVar`, so `translate` (conventionally aliased `_`) works
anywhere without threading a request around. Translation managers resolve message keys per
locale — `JsonFilesTranslations`, `InMemoryTranslations`, `NoTranslations`, or a custom
subclass — and formatters (`StrFormatter`, or Jinja2 via the `i18n` extra) interpolate
runtime values. Mark response-model fields with `Translated[str]` to translate them on
serialization. Built-in error messages are already translatable.

See [Internationalization](usage/i18n.md).

### OpenTelemetry integration

When `opentelemetry-instrumentation-fastapi` is importable, `configure_app` instruments the
application and `ErrorDetails` gains a `correlation_id` field, populated from the active
span's trace id whenever an error response is built. This makes it trivial to correlate an
error seen by a user with a span in your tracing backend. Without the extra the field is
absent from both the response body and the OpenAPI schema.

See [Observability](usage/opentelemetry.md).

### Prometheus metrics

When the `prometheus` extra is installed, `configure_app` registers a `/metrics` route exposing standard HTTP request metrics (request count, latency histogram, in-flight requests) compatible with `prometheus_client`. Passing a `prometheus_exporter_resource` instead selects OpenTelemetry-based export, which serves the same path and additionally negotiates the response format via `Accept`.

See [Observability](usage/opentelemetry.md) for the differences between the two modes.

### Structured request logging

Pass `enable_request_logging_middleware=True` to `configure_app` (requires the `structlog`
extra) to install `RequestLoggingMiddleware`, which logs a `request` and a `response` event
per request via `structlog` — including request id, client, method, path, filtered headers,
query params, status code, and duration. The log level follows the status code (`ERROR` for
5xx, `WARNING` for 4xx, `INFO` otherwise). Configuring `structlog`'s own output rendering
is left to your application.

### `configure_app` — one-call setup

`configure_app(app)` wires up:

- RFC 9457 error handlers for `APIError`, `HTTPException`, FastAPI's `RequestValidationError`, and unhandled exceptions — plus an OpenAPI post-processor that drops FastAPI's default `422` responses and `ValidationError` schemas
- a GZip middleware (configurable via `gzip_middleware_min_size`) and `RequestLimitMiddleware`, which caps the number of **concurrently handled** requests (`limits`, default `1000`)
- Prometheus middleware (if `starlette-exporter` is installed)
- OpenTelemetry instrumentation (if `opentelemetry-instrumentation-fastapi` is installed); extra keyword arguments are forwarded to the instrumentor
- `LocaleMiddleware` and the global translation source, when a `translation_manager` is passed
- `RequestLoggingMiddleware`, when `enable_request_logging_middleware=True` is passed
- simplified OpenAPI operation IDs

`enable_prometheus_middleware` defaults to `None`, meaning "on unless a
`prometheus_exporter_resource` is given" — so `configure_app(app, prometheus_exporter_resource=r)`
selects exporter mode on its own. Passing `enable_prometheus_middleware=True` *and* a resource
raises `ValueError`, since that explicitly asks for two exporters.

Middlewares end up in this order, outermost to innermost:

```
RequestLoggingMiddleware -> RequestLimitMiddleware -> PrometheusMiddleware
    -> GZipMiddleware -> LocaleMiddleware -> router
```

This single call replaces dozens of lines of middleware and exception handler boilerplate.

### ORM-agnostic design

FastAPI Views has **no dependency on any ORM**. Generic views interact with data through the `Repository` protocol, which is trivially satisfied by any object exposing `create`, `get`, `list`, `update_one`, `delete_one`, and `get_filtered_page` methods. Pair it with SQLAlchemy, Tortoise ORM, MongoDB Motor, or a plain in-memory dict.

### Both async and sync support

Every view class has an `Async` and a synchronous variant (`AsyncListAPIView` / `ListAPIView`, `AsyncAPIViewSet` / `APIViewSet`, etc.). Sync endpoints are run in a thread pool automatically by Starlette, so they are safe to use alongside async code.

### OpenAPI operation ID simplification

Operation IDs in the generated OpenAPI spec follow an `{action}_{component_name}` convention (e.g., `list_item`, `create_item`, `retrieve_item`). This makes generated client and SDK names readable rather than the long, path-derived defaults that FastAPI produces.

### CLI

Generate a static `openapi.json` or `openapi.yaml` file without starting a server:

```shell
# Install the CLI extra
pip install 'fastapi-views[cli]'

# Export the spec (defaults to ./openapi.json)
fastapi-views docs myapp:app --out openapi.json

# ...or as YAML
fastapi-views docs myapp:app --out openapi.yaml --format yaml
```

The application is imported from an `<module>:<attribute>` path, resolved against the
current working directory. `--format yaml` needs PyYAML, which `fastapi-views` deliberately
does not declare — install it in your own project when you want YAML output.

---

## Project status

FastAPI Views is actively maintained, fully type-checked with mypy, linted with Ruff, and security-scanned with Bandit. It supports Python 3.10 and above.
