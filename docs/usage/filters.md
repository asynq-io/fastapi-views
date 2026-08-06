# Filters

FastAPI Views ships a Django REST Framework-inspired filter system that handles filtering, sorting, searching, pagination, and field projection. Filters are ordinary Pydantic models, so they integrate naturally with FastAPI's dependency injection and appear correctly in the OpenAPI spec.

A filter never touches your data layer directly. It turns query parameters into a list of small, declarative *operations*, and a **resolver** translates those operations into a query for a specific backend (SQLAlchemy, plain Python objects, …).

Everything in the public API is re-exported from the package root:

```python
from fastapi_views.filters import (
    BaseFilter,
    BasePaginationFilter,
    CursorPaginationFilter,
    FieldsFilter,
    Filter,
    FilterDepends,
    ModelFilter,
    NestedFilter,
    OffsetLimitFilter,
    OrderingFilter,
    PaginationFilter,
    SearchFilter,
)
```

Resolvers are **not** re-exported — the `resolvers` package is empty, so importing filters never pulls in SQLAlchemy. Import them from their submodule:

```python
from fastapi_views.filters.resolvers.objects import ObjectFilterResolver
from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver
```

---

## Query parameters at a glance

| Filter class | Query parameters | Defaults |
|--------------|------------------|----------|
| `ModelFilter` | one parameter per declared field | per field |
| `OrderingFilter` | `?sort` (repeatable) | `None` |
| `SearchFilter` | `?q` | `None` |
| `FieldsFilter` | `?fields` (repeatable) | `None` |
| `PaginationFilter` | `?page`, `?page_size` | `1`, `100` |
| `OffsetLimitFilter` | `?offset`, `?limit` | `0`, `100` |
| `CursorPaginationFilter` | `?cursor`, `?page_size` | `None`, `100` |

`page_size` is capped at `MAX_PAGE_SIZE` (default `500`, read from the `MAX_PAGE_SIZE` environment variable at import time).

---

## Filter classes

### `BaseFilter`

The root of the hierarchy — a Pydantic `BaseModel` plus two building blocks:

- `special_fields: ClassVar[set[str]]` — names that are *not* data filters (pagination, sorting, search, projection). They are collected from the whole MRO in `__init_subclass__`, and excluded from `as_kwargs()`.
- `get_filters()` — returns the list of operations for this filter; the `filters` property is a shortcut for it. `BaseFilter.get_filters()` returns an empty list, subclasses extend it.

```python
from fastapi_views.filters import BaseFilter
from fastapi_views.filters.operations import FilterOperation


class StatusFilter(BaseFilter):
    status: str | None = None

    def get_filters(self):
        filters = super().get_filters()
        if self.status is not None:
            filters.append(
                FilterOperation(field="status", operator="eq", values=self.status)
            )
        return filters
```

### `ModelFilter`

Extends `BaseFilter` and builds the operations automatically from its own fields, so you rarely need to write `get_filters()` yourself. A field name may carry a lookup suffix after the **last** double underscore (`field__operator`); a name with no `__` at all gets the operator `eq`. `None` values are skipped, so every filter field is opt-in.

```python
from fastapi_views.filters import ModelFilter


class ItemFilter(ModelFilter):
    name: str | None = None          # name = ?
    status__ne: str | None = None    # status != ?
    price__lt: int | None = None     # price < ?
    price__ge: int | None = None     # price >= ?
    stock__is_null: bool | None = None  # stock IS NULL / IS NOT NULL
```

`field_names` is the set of fields `ModelFilter` builds operations from (all model fields minus `special_fields`). Values added with `with_kwargs()` are appended as operations too.

Everything before the last `__` is kept as the operation's `field`, which is how lookups reach a related table (see [Nested filters](#nested-filters) and [Filtering across joined tables](#filtering-across-joined-tables)):

```python
class ItemFilter(ModelFilter):
    user__name__eq: str | None = None   # field="user__name", operator="eq"
    user__name__gt: str | None = None   # field="user__name", operator="gt"
```

A nested **equality** lookup therefore has to spell the operator out: `user__name` alone parses as field `user` with operator `name`, which no resolver knows.

### `OrderingFilter`

Adds a repeatable `?sort` query parameter. Prefix a field with `-` for descending (`+` is also accepted and stripped). `ordering_fields` whitelists the sortable fields: unknown values fail validation with `422`, and the allowed values are listed in the parameter's OpenAPI description.

```python
from fastapi_views.filters import OrderingFilter


class ItemOrderingFilter(OrderingFilter):
    ordering_fields = {"name", "price", "created_at"}
```

- `?sort=name` — ascending by `name`
- `?sort=-created_at` — descending by `created_at`
- `?sort=price&sort=-name` — multi-column sort

`get_order_by()` (or the `order_by` property) returns a list of `SortOperation`s. Sorting is kept separate from `get_filters()` — resolvers apply it in a separate step.

`ordering_fields` defaults to an empty set, in which case *every* `?sort` value is rejected — always declare it on the subclass.

### `SearchFilter`

Adds a `?q` query parameter (the model field is named `query`, the query parameter is aliased to `q`) and appends a single `LogicalOperation(operator="or", ...)` containing one `ilike` operation per entry in `search_fields`.

```python
from fastapi_views.filters import SearchFilter


class ItemSearchFilter(SearchFilter):
    search_fields = {"name", "description"}
```

`?q=widget` produces `name ILIKE '%widget%' OR description ILIKE '%widget%'`.

### Pagination filters

`BasePaginationFilter` declares `pagination_fields: ClassVar[set[str]]`, which is automatically merged into `special_fields` (so pagination parameters never leak into `as_kwargs()`), and `get_pagination(**kwargs)`, which dumps just those fields — exactly the keyword arguments a paginating repository expects. Extra keyword arguments are forwarded to `model_dump`.

| Class | Fields | Defaults |
|-------|--------|----------|
| `PaginationFilter` | `page: PageNumber`, `page_size: PageSize` | `1`, `100` |
| `OffsetLimitFilter` | `offset: NonNegativeInt`, `limit: PositiveInt` | `0`, `100` |
| `CursorPaginationFilter` | `cursor: Cursor \| None`, `page_size: PageSize` | `None`, `100` |

```python
>>> PaginationFilter(page=3, page_size=20).get_pagination()
{'page': 3, 'page_size': 20}
>>> OffsetLimitFilter().get_pagination()
{'offset': 0, 'limit': 100}
```

`Cursor` values are base64-decoded on the way in and re-encoded on JSON serialization, so clients only ever see opaque tokens. See [Pagination](../reference/pagination.md) for the matching page containers.

### `FieldsFilter`

Adds a repeatable `?fields` query parameter for sparse fieldsets, exposed through `get_fields()` (returns `set[str] | None`). Set `fields_from` to a Pydantic model and the accepted values are narrowed to that model's field names, which also renders as an `enum` in the OpenAPI schema. The narrowing applies to that subclass only — plain `FieldsFilter`s and other subclasses elsewhere in the app keep accepting any string.

```python
from pydantic import BaseModel

from fastapi_views.filters import FieldsFilter


class ItemSchema(BaseModel):
    id: int
    name: str
    price: int
    description: str


class ItemFieldsFilter(FieldsFilter):
    fields_from = ItemSchema
```

`?fields=id&fields=name` yields `{"id", "name"}` (`fields` is a set, so repeat the parameter — it is not comma-separated).

Projection is *not* part of `get_filters()`; it is applied either by a resolver (`apply_fields_filter`) or, in [generic views](generics.md), by the serializer, which restricts the response to the requested fields.

### `Filter` — all-in-one

`Filter` inherits from `PaginationFilter`, `OrderingFilter`, `SearchFilter`, `FieldsFilter` and `ModelFilter`. Use it when you want the full feature set without composing anything manually.

```python
from typing import ClassVar

from fastapi_views.filters import Filter


class ItemFilter(Filter):
    ordering_fields: ClassVar[set[str]] = {"name", "price"}
    search_fields: ClassVar[set[str]] = {"name", "description"}
    fields_from = ItemSchema

    name: str | None = None
    price__lt: int | None = None
```

---

## Lookup suffixes

The suffix after `__` becomes the operation's `operator`; each resolver maps operator names to backend expressions.

| Suffix | Meaning | `SQLAlchemyFilterResolver` | `ObjectFilterResolver` |
|--------|---------|----------------------------|------------------------|
| *(none)* / `__eq` | `==` | yes | yes |
| `__ne` | `!=` | yes | yes |
| `__lt`, `__le`, `__gt`, `__ge` | `<`, `<=`, `>`, `>=` | yes | yes |
| `__in` | `IN (...)` | yes | no |
| `__not_in` | `NOT IN (...)` | yes | no |
| `__is_null` | `IS NULL` when `True`, `IS NOT NULL` when `False` | yes | yes |
| `__like` | `LIKE '%value%'` | yes | case-sensitive substring |
| `__ilike` | `ILIKE '%value%'` | yes | case-insensitive substring |

Notes:

- Use `le` / `ge`, not `lte` / `gte`.
- The SQLAlchemy resolver wraps `like` / `ilike` values in `%…%` and escapes `\`, `%` and `_`, so user input cannot inject wildcards.
- `ObjectFilterResolver` implements `is_null`, `like` and `ilike` explicitly and falls back to `getattr(operator, name)` for everything else — which is why `in` and `not_in` (no such functions in the stdlib `operator` module) are unsupported there and raise `AttributeError`.
- `and` / `or` are the operators of `LogicalOperation`, used for grouping (as in `SearchFilter`), not as field suffixes.

### List-valued fields

A filter field whose type is a list (e.g. for `__in`) has to be declared with `QueryField` — a bare `list[int] | None = None` makes FastAPI infer a request body instead of a query parameter:

```python
from fastapi_views.filters import ModelFilter
from fastapi_views.filters.types import QueryField


class ItemFilter(ModelFilter):
    id__in: QueryField[list[int]]        # ?id__in=1&id__in=2
    tag__not_in: QueryField[list[str]]   # ?tag__not_in=a&tag__not_in=b
    active: QueryField[bool] = None      # an explicit `= None` is harmless
```

Each `QueryField` becomes its own, independent query parameter — declare as many as you like in one filter.

`QueryField[T]` is `Annotated[T | None, Field(None), QueryParam(Query())]`. The pydantic default is a plain `None` and the `fastapi.Query` travels in the annotation metadata, wrapped in `QueryParam` so pydantic does not absorb it; `BaseFilter.__pydantic_init_subclass__` unwraps it once the field is built, which is what FastAPI then sees. Re-declaring the default (`= None`) is therefore harmless — it neither discards the query parameter nor changes the generated OpenAPI.

Because the default is a real `None`, query-backed fields (`QueryField`, `sort`, `q`, `fields`) also behave sensibly when a filter is constructed by hand rather than by FastAPI — handy in tests, where a filter can be built with no arguments at all:

```python
>>> ItemFilter().id__in is None
True
>>> ItemFilter().filters
[]
>>> OrderingFilter().sort is None, OrderingFilter().order_by
(True, [])
>>> FieldsFilter().get_fields() is None, SearchFilter().query is None
(True, True)
```

---

## Composing custom filters

Combine filter classes with multiple inheritance and pick only the behaviour you need:

```python
from typing import ClassVar

from fastapi_views.filters import (
    ModelFilter,
    OffsetLimitFilter,
    OrderingFilter,
    SearchFilter,
)


class UserFilter(OffsetLimitFilter, OrderingFilter, SearchFilter, ModelFilter):
    ordering_fields: ClassVar[set[str]] = {"name", "email", "created_at"}
    search_fields: ClassVar[set[str]] = {"name", "email"}

    name: str | None = None
    email: str | None = None
    is_active: bool | None = None
```

---

## Nested filters

`NestedFilter` embeds one filter inside another. The nested filter's operations are prefixed with the field name (`prefix__field`) via `set_prefix`, and the `prefix` argument additionally rewrites the *query parameter* names through a Pydantic alias generator:

```python
from typing import Optional

from fastapi_views.filters import Filter, ModelFilter, NestedFilter


class PostFilter(ModelFilter):
    title: Optional[str] = None


class UserFilter(Filter):
    name: Optional[str] = None

    # ?post__title=hello -> FilterOperation(field="post__title", operator="eq")
    post: Optional[PostFilter] = NestedFilter(PostFilter, prefix="post")
```

Called without a prefix, `NestedFilter(model)` is equivalent to `FilterDepends(model)` — the nested parameters keep their plain names.

How a `prefix__field` operation is resolved is up to the resolver; see [Filtering across joined tables](#filtering-across-joined-tables).

---

## Using `FilterDepends` in views

`FilterDepends` wraps a filter class as a FastAPI dependency and converts Pydantic `ValidationError` into `RequestValidationError`, so invalid input produces a regular `422 Unprocessable Entity` response instead of a `500`.

```python
from fastapi_views.filters import FilterDepends
from fastapi_views.views.api import AsyncListAPIView


class UserListView(AsyncListAPIView):
    response_schema = UserSchema

    async def list(self, filter: UserFilter = FilterDepends(UserFilter)):
        return await repository.list(**filter.as_kwargs())
```

In [generic views](generics.md), set the `filter` class attribute and `FilterDepends` is applied automatically; the list response container is derived from the filter's pagination base (`PaginationFilter` → `NumberedPage`, `OffsetLimitFilter` → `OffsetPage`, `CursorPaginationFilter` → `CursorPage`, no filter → plain `list`).

---

## Reading a filter

| Member | Returns |
|--------|---------|
| `filters` / `get_filters()` | `list[FilterOperation \| LogicalOperation]` |
| `order_by` / `get_order_by()` | `list[SortOperation]` (`OrderingFilter`) |
| `get_fields()` | `set[str] \| None` (`FieldsFilter`) |
| `get_pagination(**kwargs)` | `dict` of the pagination fields only (`BasePaginationFilter`) |
| `as_kwargs()` | non-`None` fields except `special_fields`, plus `with_kwargs()` values |
| `with_kwargs(**kwargs)` | injects extra values (server-side, not client-controlled) |

`as_kwargs()` is the escape hatch for repositories that take plain keyword arguments rather than a queryset, and it is what generic views use when a filter has no pagination base. `with_kwargs()` is how a view injects values the client must not control — a tenant id, the current user — and those values are honoured by both `as_kwargs()` and `ModelFilter.get_filters()`:

```python
>>> f = UserFilter(name="Alice")
>>> f.as_kwargs()
{'name': 'Alice'}
>>> f.with_kwargs(tenant_id=1)
>>> f.as_kwargs()
{'name': 'Alice', 'tenant_id': 1}
>>> f.filters
[FilterOperation(field='name', operator='eq', values='Alice'),
 FilterOperation(field='tenant_id', operator='eq', values=1)]
```

### Operations

Operations are plain dataclasses in `fastapi_views.filters.operations`:

| Class | Fields |
|-------|--------|
| `FieldOperation` | `field` — base class, provides `set_prefix(prefix)` |
| `FilterOperation` | `field`, `operator`, `values` |
| `SortOperation` | `field`, `desc: bool = False` |
| `LogicalOperation` | `operator` (`"and"` / `"or"`), `values` — a list of operations |

`Operation` is the union of the three concrete types.

---

## Resolvers

A resolver translates a filter into a backend query. All resolvers subclass `FilterResolver[Queryset]` from `fastapi_views.filters.resolvers.abc`, which defines the four steps and the public entry point:

```python
queryset = resolver.apply_filter(filter, queryset, exclude=None, **context)
```

`apply_filter` takes the **filter first**, then the queryset, and runs the applicable steps in order:

| Step | Method | Runs when |
|------|--------|-----------|
| `"filter"` | `apply_base_filter` | always |
| `"fields"` | `apply_fields_filter` | filter is a `FieldsFilter` |
| `"sort"` | `apply_ordering_filter` | filter is an `OrderingFilter` |
| `"paginate"` | `apply_pagination_filter` | filter is a `BasePaginationFilter` |

Pass step names in `exclude` to skip them, and any remaining keyword arguments are forwarded to every step as `context`.

### `ObjectFilterResolver`

Filters a plain `list` in memory — handy for tests, fixtures, and non-SQL sources. It reads values through a *getter factory*, `operator.attrgetter` by default:

```python
import operator
from dataclasses import dataclass

from fastapi_views.filters.resolvers.objects import ObjectFilterResolver


@dataclass
class User:
    name: str
    age: int


users = [User("John", 25), User("Jane", 30), User("Alice", 35)]

resolver = ObjectFilterResolver()
result = resolver.apply_filter(my_filter, users)

# for lists of dicts, swap the getter
dict_resolver = ObjectFilterResolver(getter=operator.itemgetter)
result = dict_resolver.apply_filter(my_filter, [{"name": "John", "age": 25}])
```

- Ordering is applied with `sorted()`, one pass per `SortOperation`.
- `PaginationFilter` and `OffsetLimitFilter` are applied by slicing the list; `CursorPaginationFilter` raises `NotImplementedError`.
- `apply_fields_filter` projects each object down to **only** the attributes named in `?fields`, returning a new list of shallow copies — the input objects are left untouched. Mappings are projected into new dicts, and objects without a `__dict__` (tuples, `__slots__` classes) are passed through unchanged. With no `?fields` the queryset is returned as-is. Sparse fieldsets are normally handled at the serialization layer instead — see [generic views](generics.md).

### `SQLAlchemyFilterResolver`

Translates operations into SQLAlchemy `WHERE`, `ORDER BY`, `LIMIT`/`OFFSET` clauses and loader options. SQLAlchemy is an optional dependency: the module imports without it, but every method that needs it raises `NotImplementedError`.

Subclass it and point `filter_model` at the model the filter fields belong to. Since the class needs no constructor arguments, it can be injected with a bare `Depends()`:

```python
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_views.filters import FilterDepends
from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver
from fastapi_views.views.api import AsyncListAPIView


class UserFilterResolver(SQLAlchemyFilterResolver):
    filter_model = UserModel


class UserListView(AsyncListAPIView):
    response_schema = UserSchema

    async def list(
        self,
        filter: UserFilter = FilterDepends(UserFilter),
        resolver: UserFilterResolver = Depends(),
        session: AsyncSession = Depends(get_session),  # your own session dependency
    ):
        queryset = resolver.apply_filter(filter, select(UserModel))
        result = await session.execute(queryset)
        return result.scalars().all()
```

The queryset only has to satisfy the `_Queryset` protocol — `filter()`, `options()`, `order_by()`, `offset()`, `limit()` — which both `Select` and ORM `Query` objects do.

Helper methods are available if you need the raw clauses instead of a modified queryset: `get_filters(filter, **context)` returns the `WHERE` expressions, and `get_order_by(filter, extra=None, **context)` returns the `ORDER BY` expressions with optional extras appended (useful to add a deterministic tie-breaker column).

#### Filtering across joined tables

A `prefix__field` operation — produced by `NestedFilter`, or by a field name such as `post__title__eq` — is resolved in one of two ways:

1. `context[prefix]["table"]`, if you pass it;
2. otherwise a lookup in the model registry by `__tablename__ == prefix`, cached per registry **and** per resolver class in a `WeakKeyDictionary` keyed by the registry (so two declarative bases that happen to share a `__tablename__` never collide, and the cache never keeps a registry alive).

`resolve_model_field` splits off exactly one prefix, at the *first* `__`: `post__title` is column `title` on `post`. Deeper paths (`company__owner__name`) are kept whole by the filter models but not understood by the default implementation — override `resolve_model_field` to walk them.

Because `context` is passed as keyword arguments, the prefix becomes the keyword:

```python
queryset = resolver.apply_filter(
    filter,
    select(UserModel).join(PostModel),
    post={"table": PostModel},
)
```

The reserved `table` key overrides the base model for unprefixed fields:

```python
queryset = resolver.apply_filter(filter, select(PostModel), table=PostModel)
```

#### Field projection

`apply_fields_filter` turns `?fields` into loader options rather than a column list: top-level names become a single `load_only(...)`, and `relation__field` (or `a__b__field`) names become chained `defaultload(...).load_only(...)` options. Relationship names are resolved by inspecting the mapper; unknown paths are skipped.

#### Cursor pagination

`apply_cursor_pagination(queryset, page, page_size, **context)` raises `NotImplementedError` — SQLAlchemy has no built-in keyset pagination. Override it (for example on top of [sqlakeyset](https://github.com/djrobstep/sqlakeyset)), or use a repository that implements it, such as `CursorPaginatedRepository` from the [sqlargon integration](sqlargon.md). Accept `**context` in your override: `apply_pagination_filter` forwards the resolver context to it.

```python
class UserFilterResolver(SQLAlchemyFilterResolver):
    filter_model = UserModel

    def apply_cursor_pagination(self, queryset, page, page_size, **context):
        return my_keyset_paginate(queryset, page, page_size)
```

#### Skipping stages with `exclude`

`exclude` lets you take over individual stages — most often pagination, when you need a `COUNT(*)` over the filtered set first:

```python
from sqlalchemy import func, select

# filter is an OffsetLimitFilter here
queryset = resolver.apply_filter(filter, select(UserModel), exclude={"paginate"})
total = await session.scalar(select(func.count()).select_from(queryset.subquery()))
queryset = queryset.offset(filter.offset).limit(filter.limit)
```

This is exactly what the sqlargon integration does: `FilterableRepository.with_filter(filter, exclude={"paginate"})` followed by `paginate(**filter.get_pagination())`.

### Custom resolvers

Implement the four abstract methods to support another backend; `apply_filter` and the `exclude` handling come for free.

```python
from typing import Any

from fastapi_views.filters.resolvers.abc import FilterResolver


class MongoFilterResolver(FilterResolver[dict]):
    def apply_base_filter(self, queryset: dict, filter, **context: Any) -> dict:
        ...

    def apply_fields_filter(self, queryset: dict, filter, **context: Any) -> dict:
        ...

    def apply_ordering_filter(self, queryset: dict, filter, **context: Any) -> dict:
        ...

    def apply_pagination_filter(self, queryset: dict, filter, **context: Any) -> dict:
        ...
```

Note that the abstract methods take `(queryset, filter)`, while the public `apply_filter` takes `(filter, queryset)`.

---

## Full SQLAlchemy example

```python
from typing import Any, ClassVar, Optional

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from fastapi_views.filters import Filter, FilterDepends, ModelFilter, NestedFilter
from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver
from fastapi_views.filters.types import QueryField
from fastapi_views.views.api import AsyncListAPIView


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String())
    email: Mapped[Optional[str]] = mapped_column(sa.String(), nullable=True)
    posts: Mapped[list["PostModel"]] = relationship(back_populates="user")


class PostModel(Base):
    __tablename__ = "post"

    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    title: Mapped[str] = mapped_column(sa.String())
    user_id: Mapped[int] = mapped_column(sa.Integer(), sa.ForeignKey("user.id"))
    user: Mapped["UserModel"] = relationship(back_populates="posts")


class PostFilter(ModelFilter):
    title: Optional[str] = None


class UserFilter(Filter):
    ordering_fields: ClassVar[set[str]] = {"name", "id"}
    search_fields: ClassVar[set[str]] = {"name", "email"}

    name: Optional[str] = None
    id__in: QueryField[list[int]]
    email__is_null: Optional[bool] = None
    post: Optional[PostFilter] = NestedFilter(PostFilter, prefix="post")


class UserFilterResolver(SQLAlchemyFilterResolver):
    filter_model = UserModel


class UserListView(AsyncListAPIView):
    response_schema = UserSchema  # your response schema

    async def list(
        self,
        filter: UserFilter = FilterDepends(UserFilter),
        resolver: UserFilterResolver = Depends(),
        session: AsyncSession = Depends(get_session),  # your own session dependency
    ) -> Any:
        # applies WHERE, ORDER BY, LIMIT and OFFSET
        queryset = resolver.apply_filter(
            filter,
            select(UserModel).join(PostModel),
            post={"table": PostModel},
        )
        result = await session.execute(queryset)
        return result.scalars().all()
```

A request to
`?post__title=hello&q=al&sort=-name&id__in=1&id__in=2&page=2&page_size=5`
produces:

```sql
SELECT "user".id, "user".name, "user".email
FROM "user" JOIN post ON "user".id = post.user_id
WHERE post.title = 'hello'
  AND "user".id IN (1, 2)
  AND (lower("user".email) LIKE lower('%al%') ESCAPE '\'
       OR lower("user".name) LIKE lower('%al%') ESCAPE '\')
ORDER BY "user".name DESC
LIMIT 5 OFFSET 5
```

`field_names` and `search_fields` are sets, so the order of the `AND`/`OR` terms is not guaranteed — only their content is.
