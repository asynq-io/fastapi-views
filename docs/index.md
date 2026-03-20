# FastAPI Views

![Tests](https://github.com/asynq-io/fastapi-views/workflows/Tests/badge.svg)
![Build](https://github.com/asynq-io/fastapi-views/workflows/Publish/badge.svg)
![License](https://img.shields.io/github/license/asynq-io/fastapi-views)
![Mypy](https://img.shields.io/badge/mypy-checked-blue)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v1.json)](https://github.com/charliermarsh/ruff)
[![Pydantic v2](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pydantic/pydantic/main/docs/badge/v2.json)](https://docs.pydantic.dev/latest/contributing/#badges)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
![Python](https://img.shields.io/pypi/pyversions/fastapi-views)
![Format](https://img.shields.io/pypi/format/fastapi-views)
![PyPi](https://img.shields.io/pypi/v/fastapi-views)

**Class-based views, CRUD utilities, and production-ready patterns for FastAPI.**

FastAPI Views brings Django REST Framework-style class-based views to FastAPI — without giving up type safety or dependency injection. Define a full CRUD resource by inheriting one class; routes, status codes, and OpenAPI docs are wired up automatically.

## Features

- **Class-based views** — `View`, `APIView`, `ViewSet`, and `GenericViewSet` at three levels of abstraction; mix-in only the actions you need
- **Full CRUD in one class** — `list`, `create`, `retrieve`, `update`, `partial_update`, `destroy` with correct HTTP semantics out of the box (`201 Created`, `204 No Content`, `Location` header, etc.)
- **Generic views with the repository pattern** — plug in any data source (SQLAlchemy, Motor, plain dicts) via a simple protocol; no ORM dependency
- **DRF-style filters** — `ModelFilter`, `OrderingFilter`, `SearchFilter`, `PaginationFilter`, `TokenPaginationFilter`, `FieldsFilter`, and a combined `Filter` class; built-in SQLAlchemy and Python object resolvers
- **RFC 9457 Problem Details** — every error response is machine-readable; built-in classes for the most common cases; custom errors auto-register in the OpenAPI spec
- **Fast Pydantic v2 serialization** — `TypeAdapter` cached per schema type avoids the double validation/model instantiation that FastAPI does by default, reducing per-request overhead
- **Server-Sent Events** — `ServerSentEventsAPIView` and `@sse_route` handle framing, content-type, and Pydantic validation automatically
- **Async and sync support** — every class ships an `Async` and a synchronous variant; sync endpoints run in a thread pool
- **One-call setup** — `configure_app(app)` registers error handlers, Prometheus middleware, and OpenTelemetry instrumentation
- **Prometheus metrics** — `/metrics` endpoint with request count, latency histogram, and in-flight requests (optional extra)
- **OpenTelemetry tracing** — `correlation_id` injected into every error response for easy trace correlation (optional extra)
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
| `prometheus` | Prometheus metrics middleware (`/metrics` endpoint) |
| `uvicorn` | `uvicorn` ASGI server |
| `opentelemetry` | OpenTelemetry tracing instrumentation |
| `cli` | CLI tool for generating static OpenAPI JSON/YAML files |

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
- **`ViewSet` / `APIViewSet`** — combines multiple CRUD actions into one class. Mix and match with provided mixin classes (`ListAPIView`, `CreateAPIView`, etc.) for exactly the surface you need.

### Generic views with the repository pattern

`GenericViewSet` and `AsyncGenericViewSet` implement all CRUD logic for you. Provide a `repository` object that satisfies the `Repository` / `AsyncRepository` protocol and the view handles the rest — including `409 Conflict` on duplicate creates and `404 Not Found` on missing resources. Lifecycle hooks (`before_create`, `after_create`, `before_update`, `after_update`) let you add custom logic without overriding entire actions.

See [Generic Views](usage/generics.md) for a full example.

### Filters, pagination, and sorting

The `Filter` system mirrors Django REST Framework's `FilterSet` API:

- **`ModelFilter`** — filter by model field values (e.g. `?name=Alice`)
- **`OrderingFilter`** — sort by whitelisted fields using `?sort=name` or `?sort=-created_at`
- **`SearchFilter`** — full-text search across multiple fields with `?q=…`
- **`PaginationFilter`** — page-number pagination returning a `NumberedPage`
- **`TokenPaginationFilter`** — cursor-based pagination returning a `TokenPage`
- **`FieldsFilter`** — sparse fieldsets; return only requested fields with `?fields=id,name`
- **`Filter`** — convenience class combining all of the above

Built-in resolvers for SQLAlchemy and plain Python objects translate filter objects into queries with zero glue code.

See [Filters](usage/filters.md) for usage details.

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

### OpenTelemetry integration

When `opentelemetry-sdk` is installed, `configure_app` automatically injects the active trace's `correlation_id` into every error response. This makes it trivial to correlate an error seen by a user with a span in your tracing backend.

See [OpenTelemetry](usage/opentelemetry.md).

### Prometheus metrics

When the `prometheus` extra is installed, `configure_app` mounts a `/metrics` endpoint that exposes standard HTTP request metrics (request count, latency histogram, in-flight requests) compatible with `prometheus_client`.

### `configure_app` — one-call setup

`configure_app(app)` wires up:

- RFC 9457 error handlers for `APIError`, FastAPI's `RequestValidationError`, and unhandled exceptions
- Prometheus middleware (if `starlette-exporter` is installed)
- OpenTelemetry instrumentation (if `opentelemetry-sdk` is installed)

This single call replaces dozens of lines of middleware and exception handler boilerplate.

### ORM-agnostic design

FastAPI Views has **no dependency on any ORM**. Generic views interact with data through the `Repository` protocol, which is trivially satisfied by any object exposing `create`, `get`, `list`, `update_one`, `delete`, and `get_filtered_page` methods. Pair it with SQLAlchemy, Tortoise ORM, MongoDB Motor, or a plain in-memory dict.

### Both async and sync support

Every view class has an `Async` and a synchronous variant (`AsyncListAPIView` / `ListAPIView`, `AsyncAPIViewSet` / `APIViewSet`, etc.). Sync endpoints are run in a thread pool automatically by Starlette, so they are safe to use alongside async code.

### OpenAPI operation ID simplification

Operation IDs in the generated OpenAPI spec follow an `{action}_{component_name}` convention (e.g., `list_item`, `create_item`, `retrieve_item`). This makes generated client and SDK names readable rather than the long, path-derived defaults that FastAPI produces.

### CLI

Generate a static `openapi.json` or `openapi.yaml` file without starting a server:

```shell
# Install the CLI extra
pip install 'fastapi-views[cli]'

# Export the spec
fastapi-views export myapp:app --output openapi.json
```

---

## Project status

FastAPI Views is actively maintained, fully type-checked with mypy, linted with Ruff, and security-scanned with Bandit. It supports Python 3.10 and above.
