---

# fastapi-views

![CI](https://github.com/asynq-io/fastapi-views/workflows/CI/badge.svg)
![Build](https://github.com/asynq-io/fastapi-views/workflows/Publish/badge.svg)
![License](https://img.shields.io/github/license/asynq-io/fastapi-views)
![Python](https://img.shields.io/pypi/pyversions/fastapi-views)
![Format](https://img.shields.io/pypi/format/fastapi-views)
![PyPi](https://img.shields.io/pypi/v/fastapi-views)
![Mypy](https://img.shields.io/badge/mypy-checked-blue)
![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)

*FastAPI Class Views and utilities*

---
Version: 0.3.2

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

from fastapi_views import Serializer
from fastapi_views.views.viewsets import AsyncAPIViewSet


class ItemSchema(Serializer):
    id: UUID
    name: str
    price: int


items = {}


class MyViewSet(AsyncAPIViewSet):
    response_schema = ItemSchema
    
    async def list(self, *args, **kwargs):
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

```

## Installation

```shell
pip install fastapi-views
```
or

```shell
poetry add fastapi-views
```
