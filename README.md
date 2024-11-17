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

*FastAPI Class Views and utilities*

---
Documentation: https://asynq-io.github.io/fastapi-views/

Repository: https://github.com/asynq-io/fastapi-views

---

## Installation

```shell
pip install fastapi-views
```

## Usage

```python
from typing import Optional
from uuid import UUID
from fastapi import FastAPI
from fastapi_views import Serializer, ViewRouter
from fastapi_views.views.viewsets import AsyncAPIViewSet


class ItemSchema(Serializer):
    id: UUID
    name: str
    price: int


items = {}


class MyViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    serializer = ItemSchema

    async def list(self):
        return list(items.values())

    async def create(self, item: ItemSchema) -> ItemSchema:
        items[item.id] = item
        return item

    async def retrieve(self, id: UUID) -> Optional[ItemSchema]:
        return items.get(id)

    async def update(self, item: ItemSchema):
        items[item.id] = item

    async def destroy(self, id: UUID) -> None:
        items.pop(id, None)

router = ViewRouter(prefix="/items")
router.register_view(MyViewSet)

app = FastAPI()
app.include_router(router)

```

## Features

- Class Based Views
  - APIViews
  - ViewSets
- Both async and sync function support
- No dependencies on ORM
- OpenAPI operation id simplification
- 'Smart' and fast serialization using Pydantic v2
- Http Problem Details implementation (both models & exception classes)
- Automatic prometheus metrics exporter
- Optional Opentelemetry instrumentation with `correlation_id` in error responses
- CLI for generating OpenAPI documentation file
- Pagination types & schemas
