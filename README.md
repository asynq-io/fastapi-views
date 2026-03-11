# fastapi-views

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
- **Server-Sent Events** — `ServerSideEventsAPIView` and `@sse_route` handle framing, content-type, and Pydantic validation automatically
- **Async and sync support** — every class ships an `Async` and a synchronous variant; sync endpoints run in a thread pool
- **One-call setup** — `configure_app(app)` registers error handlers, Prometheus middleware, and OpenTelemetry instrumentation
- **Prometheus metrics** — `/metrics` endpoint with request count, latency histogram, and in-flight requests (optional extra)
- **OpenTelemetry tracing** — `correlation_id` injected into every error response for easy trace correlation (optional extra)
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
Avaliable extensions: `uvloop`, `prometheus`, `uvicorn`, `opentelemetry`, `cli`

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
