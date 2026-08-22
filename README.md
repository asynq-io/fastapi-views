# fastapi-views

![Tests](https://github.com/asynq-io/fastapi-views/workflows/Tests/badge.svg)
![Build](https://github.com/asynq-io/fastapi-views/workflows/Publish/badge.svg)
![License](https://img.shields.io/github/license/asynq-io/fastapi-views)
![Mypy](https://img.shields.io/badge/mypy-checked-blue)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/charliermarsh/ruff))
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
- **Permissions** — DRF-style `has_permission` / `has_object_permission` checks over your typed principal, composable with `&`, `|`, `~` (`IsAuthenticated & HasPermissions("read:docs")`, `IsAdmin | IsOwner()`); app-level auth, `Authenticated[CustomUser]` injection, and per-endpoint OpenAPI security scopes with a working Swagger Authorize button
- **Internationalization (i18n)** — per-request locale detection (query param, cookie, `Accept-Language`), pluggable translation managers (JSON files, in-memory, or custom), `str.format`/Jinja2 formatters, and `Translated[str]` model fields; built-in error messages are translatable out of the box (optional extra)
- **Async and sync support** — every class ships an `Async` and a synchronous variant; sync endpoints run in a thread pool
- **One-call setup** — `configure_app(app)` registers error handlers, Prometheus middleware, OpenTelemetry instrumentation, locale detection, optional request logging, and a concurrency limit
- **Prometheus metrics** — `/metrics` endpoint with request count, latency histogram, and in-flight requests (optional extra)
- **OpenTelemetry tracing** — `correlation_id` injected into every error response for easy trace correlation (optional extra)
- **Structured request logging** — opt-in `RequestLoggingMiddleware` backed by `structlog`, enabled with `configure_app(enable_request_logging_middleware=True)` (optional extra)
- **Readable OpenAPI operation IDs** — `list_item`, `create_item`, `retrieve_item` instead of FastAPI's long path-derived defaults
- **CLI** — export a static `openapi.json` / `openapi.yaml` without starting a server

---
Documentation: https://asynq-io.github.io/fastapi-views/

Repository: https://github.com/asynq-io/fastapi-views

---

## Installation

```shell
pip install fastapi-views
```

## Optional dependencies
Available extensions: `uvloop`, `uvicorn`, `prometheus`, `opentelemetry`, `cli`, `structlog`, `websockets`, `jose` (JWT auth), `auth0` (Auth0 auth), `i18n`, `cache` (Redis), `jsonpatch`, `sqlargon` (SQLAlchemy repositories), and `standard` (a curated bundle).

```shell
pip install 'fastapi-views[all]'
```

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
