# Filters

FastAPI Views ships a Django REST Framework-inspired filter system that handles filtering, sorting, searching, pagination, and field projection. Filters are ordinary Pydantic models, so they integrate naturally with FastAPI's dependency injection and appear correctly in the OpenAPI spec.

---

## Filter classes

### `BaseFilter`

The root of the filter hierarchy. Every filter is a Pydantic `BaseModel` with a `special_fields` class variable that lists field names that should be excluded from data queries (e.g., pagination parameters that are used for slicing rather than filtering).

```python
from fastapi_views.filters.models import BaseFilter

class StatusFilter(BaseFilter):
    status: str | None = None
```

### `ModelFilter`

Extends `BaseFilter` to automatically build filter operations from model fields. Fields whose names contain `__` are treated as `field__operator` pairs; others default to equality (`eq`).

```python
from fastapi_views.filters.models import ModelFilter

class ItemFilter(ModelFilter):
    name: str | None = None           # WHERE name = ?
    price__lt: int | None = None      # WHERE price < ?
    price__gte: int | None = None     # WHERE price >= ?
    status: str | None = None         # WHERE status = ?
```

Supported operators: `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in`, `not_in`, `is_null`, `like`, `ilike`.

### `OrderingFilter`

Adds a `?sort` query parameter. Prefix a field name with `-` to sort descending. Set `ordering_fields` to whitelist which fields may be sorted.

```python
from fastapi_views.filters.models import OrderingFilter

class ItemOrderingFilter(OrderingFilter):
    ordering_fields = {"name", "price", "created_at"}
```

Example requests:

- `?sort=name` — sort by name ascending
- `?sort=-created_at` — sort by `created_at` descending
- `?sort=price&sort=-name` — multi-column sort

### `SearchFilter`

Adds a `?query` parameter and performs a case-insensitive search across `search_fields` using an `OR` condition.

```python
from fastapi_views.filters.models import SearchFilter

class ItemSearchFilter(SearchFilter):
    search_fields = {"name", "description"}
```

Example: `?q=widget` generates `WHERE name ILIKE '%widget%' OR description ILIKE '%widget%'`.

### `PaginationFilter`

Adds `?page` and `?page_size` query parameters. The list action returns a `NumberedPage` when this filter is active.

```python
from fastapi_views.filters.models import PaginationFilter
```

`page_size` defaults to `100` and is capped at `MAX_PAGE_SIZE` (default 500, configurable via the `MAX_PAGE_SIZE` environment variable).

### `TokenPaginationFilter`

Cursor-based pagination using an opaque `?page_token`. The token is base64-encoded internally. The list action returns a `TokenPage` when this filter is active.

### `FieldsFilter`

Adds a `?fields` query parameter for sparse fieldsets — only the requested fields are included in each response object.

```python
from fastapi_views.filters.models import FieldsFilter
from pydantic import BaseModel

class ItemSchema(BaseModel):
    id: int
    name: str
    price: int
    description: str

class ItemFieldsFilter(FieldsFilter):
    fields_from = ItemSchema  # restricts ?fields values to ItemSchema's fields
```

Example: `?fields=id,name` returns only `id` and `name` in each item.

### `Filter` — all-in-one

`Filter` inherits from `PaginationFilter`, `OrderingFilter`, `SearchFilter`, `FieldsFilter`, and `ModelFilter`. Use it when you want the full feature set without composing anything manually.

```python
from fastapi_views.filters.models import Filter
```

---

## Composing custom filters

Combine filter classes with multiple inheritance:

```python
from fastapi_views.filters.models import (
    ModelFilter,
    OrderingFilter,
    PaginationFilter,
    SearchFilter,
)

class UserFilter(PaginationFilter, OrderingFilter, SearchFilter, ModelFilter):
    name: str | None = None
    email: str | None = None
    is_active: bool | None = None

    ordering_fields = {"name", "email", "created_at"}
    search_fields = {"name", "email"}
```

---

## Nested filters

Use `NestedFilter` to filter on related model fields. Query parameters are prefixed with the nested field name using double underscores (`__`):

```python
from fastapi_views.filters.models import ModelFilter, Filter
from fastapi_views.filters.dependencies import NestedFilter

class PostFilter(ModelFilter):
    title: str | None = None

class UserFilter(Filter):
    name: str | None = None
    email: str | None = None

    # ?post__title=hello filters by post.title = "hello"
    post: PostFilter = NestedFilter(PostFilter, prefix="post")

    search_fields = {"name", "email"}
    ordering_fields = {"name", "created_at"}
```

---

## Using `FilterDepends` in views

`FilterDepends` wraps a filter class as a FastAPI dependency and converts Pydantic `ValidationError` into a proper `422 Unprocessable Entity` response.

```python
from fastapi_views.filters.dependencies import FilterDepends
from fastapi_views.views.api import AsyncListAPIView

class UserListView(AsyncListAPIView):
    response_schema = UserSchema

    async def list(self, filter: UserFilter = FilterDepends(UserFilter)):
        return await db.list_users(filter)
```

In Generic views, set the `filter` class attribute and `FilterDepends` is applied automatically.

---

## Resolvers

Resolvers translate filter objects into data-layer queries.

### `ObjectFilterResolver`

Works with plain Python lists of objects or dictionaries. Useful for in-memory stores or non-SQL data sources.

```python
from fastapi_views.filters.resolvers.objects import ObjectFilterResolver

resolver = ObjectFilterResolver()

# items is a list of dicts or objects
filtered = resolver.apply_filter(my_filter, items)
```

### `SQLAlchemyFilterResolver`

Translates filter operations into SQLAlchemy `where`, `order_by`, and `limit`/`offset` clauses.

```python
from fastapi import Depends
from sqlalchemy import select
from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver
from fastapi_views.filters.dependencies import FilterDepends
from fastapi_views.views.api import AsyncListAPIView


# Subclass the resolver and set filter_model to your primary SQLAlchemy model.
# This is required so the resolver knows which table to query by default.
class UserFilterResolver(SQLAlchemyFilterResolver):
    filter_model = UserModel


class UserListView(AsyncListAPIView):
    response_schema = UserSchema

    async def list(
        self,
        filter: UserFilter = FilterDepends(UserFilter),
        resolver: UserFilterResolver = Depends(),
    ):
        queryset = select(UserModel)
        queryset = resolver.apply_filter(filter, queryset)
        async with self.get_db() as session:
            result = await session.execute(queryset)
            return result.scalars().all()
```

#### Filtering across joined tables

When filtering across related tables, pass a `context` dict mapping table prefixes to their SQLAlchemy model classes:

```python
queryset = resolver.apply_filter(
    filter,
    select(UserModel).join(PostModel),
    context={"post": {"table": PostModel}},
)
```

#### Skipping stages with `exclude`

The `exclude` parameter lets you skip individual processing stages when you need manual control:

```python
from sqlalchemy import func, select

# Apply filtering and sorting, but handle pagination manually
queryset = resolver.apply_filter(filter, queryset, exclude={"paginate"})
total = await session.scalar(select(func.count()).select_from(queryset.subquery()))
queryset = queryset.offset(filter.offset).limit(filter.limit)
```

---

## Full SQLAlchemy example

```python
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fastapi_views.filters.models import ModelFilter, Filter
from fastapi_views.filters.dependencies import FilterDepends, NestedFilter
from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver
from fastapi_views.views.api import AsyncListAPIView


class Base(DeclarativeBase):
    pass


class PostModel(Base):
    __tablename__ = "post"
    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    title: Mapped[str] = mapped_column(sa.String())
    content: Mapped[str] = mapped_column(sa.String())
    created_at: Mapped[datetime] = mapped_column(sa.DateTime())
    user_id: Mapped[int] = mapped_column(sa.Integer(), sa.ForeignKey("user.id"))


class UserModel(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String())
    email: Mapped[str] = mapped_column(sa.String())
    created_at: Mapped[datetime] = mapped_column(sa.DateTime())


class PostFilter(ModelFilter):
    title: Optional[str] = None


class UserFilter(Filter):
    name: Optional[str] = None
    email: Optional[str] = None

    # ?post__title=hello filters by post.title = "hello"
    post: PostFilter = NestedFilter(PostFilter, prefix="post")

    search_fields = {"name", "email"}
    ordering_fields = {"name", "created_at"}


class UserFilterResolver(SQLAlchemyFilterResolver):
    filter_model = UserModel


class UserListView(AsyncListAPIView):
    response_schema = UserSchema  # your response schema

    async def list(
        self,
        filter: UserFilter = FilterDepends(UserFilter),
        resolver: UserFilterResolver = Depends(),
    ):
        queryset = select(UserModel).join(PostModel)
        # applies WHERE, ORDER BY, LIMIT, and OFFSET
        queryset = resolver.apply_filter(
            filter,
            queryset,
            context={"post": {"table": PostModel}},
        )
        async with self.db_session() as session:
            result = await session.execute(queryset)
            return result.scalars().all()
```
