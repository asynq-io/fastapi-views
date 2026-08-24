# sqlargon

[Generic views](generics.md) are ORM-agnostic: they only need an object satisfying the `AsyncRepository` protocol. The `fastapi_views.integrations.sqlargon` module ships that object ready-made for [sqlargon](https://github.com/asynq-io/sqlargon), a thin async SQLAlchemy repository layer — so a fully filtered, paginated CRUD resource is three class attributes and no query code.

The integration adds two things on top of `sqlargon.SQLAlchemyRepository`:

- it applies FastAPI Views [filters](filters.md) to the repository's query, and
- it implements `get_filtered_page`, the one repository method generic views need for pagination.

---

## Installation

Install the `sqlargon` extra:

```shell
pip install 'fastapi-views[sqlargon]'
# or
uv add "fastapi-views[sqlargon]"
```

The extra resolves to `sqlargon[pagination]>=1.0.3b1,<2` (it is part of the `all` extra too). The `pagination` sub-extra pulls in [sqlakeyset](https://github.com/djrobstep/sqlakeyset), which `CursorPaginatedRepository` needs — without it that class is simply not importable, while `PaginatedRepository` and `OffsetPaginatedRepository` keep working.

!!! note
    The `1.0.3b1` floor is an intentional prerelease. Both pip and uv allow prereleases for a requirement whose specifier names one, so no flag is normally needed; if your resolver is configured for stable releases only, allow them explicitly (`pip install --pre ...`, `uv add --prerelease=allow ...`).

---

## `FilterableRepository`

`FilterableRepository` combines `sqlargon.SQLAlchemyRepository` with `SQLAlchemyFilterResolver`. Subclassing it with a model sets `filter_model` for you, so the resolver already knows which table to filter:

```python
from sqlargon import Base
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_views.integrations.sqlargon import FilterableRepository


class Fruit(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class FruitRepository(FilterableRepository[Fruit]):
    default_order_by = Fruit.id.asc()
```

It adds a single method, `with_filter`, which returns a **copy** of the repository whose query has the filter applied — filtering, sparse fields, sorting and pagination, each skippable via `exclude`:

```python
rows = await FruitRepository().with_filter(my_filter, exclude={"paginate"}).all()
```

Any extra keyword arguments are forwarded to the resolver as context, e.g. the table mapping needed to filter across a join (see [Filters](filters.md#filtering-across-joined-tables)).

---

## Paginated repositories

Three subclasses implement `get_filtered_page` with a matching pagination strategy. Pick the one that pairs with the `filter` on your view:

| Repository | Pair with filter | List response |
|------------|------------------|---------------|
| `PaginatedRepository` | `PaginationFilter` (`?page`, `?page_size`) | `NumberedPage[schema]` |
| `OffsetPaginatedRepository` | `OffsetLimitFilter` (`?offset`, `?limit`) | `OffsetPage[schema]` |
| `CursorPaginatedRepository` | `CursorPaginationFilter` (`?cursor`, `?page_size`) | `CursorPage[schema]` |

`PaginatedRepository` and `OffsetPaginatedRepository` also report totals, so `total_items` / `total_pages` / `has_more` are populated in the response. `CursorPaginatedRepository` is only importable when `sqlargon[pagination]` is installed, and its query needs a deterministic order — set `default_order_by`.

---

## Relationship preloading

Responses are serialized eagerly, so any relationship your `response_schema` touches must be loaded before the session closes — a lazy relationship raises `MissingGreenlet` at serialization time. Declare the relationships to eager load on the **repository** with `select_related`; views know nothing about loading:

```python
class BookRepository(PaginatedRepository[Book]):
    select_related = ("author",)
```

Paths use `__` for nesting (`author__publisher`). Loader strategy is picked per hop from the relationship type: `joinedload` for to-one, `selectinload` for to-many — collections stay pagination-safe and totals stay correct.

When retrieve should load more than list, use a mapping keyed by repository operation instead of a sequence:

```python
class BookRepository(PaginatedRepository[Book]):
    select_related: ClassVar[dict[str, tuple[str, ...]]] = {
        "get": ("author", "reviews"),
        "list": ("author",),
    }
```

`get` covers `retrieve`; `list` covers both `list` and `get_filtered_page`. For one-off cases, `with_related` returns a repository copy with extra loader options:

```python
book = await BookRepository().with_related("reviews").get(id=1)
```

Two related but distinct mechanisms compose with this default:

- an [`IncludeFilter`](filters.md#includefilter) on the view lets API clients opt into extra relationships per request (`?include=author`), and
- a `FieldsFilter` with nested fields (`?fields=author__name`) eager loads the relationships it projects.

Both are additive on top of `select_related`.

!!! note
    Eager loading is independent of filtering. Loader options never satisfy a
    `WHERE` clause — filtering on a related column still requires an explicit
    `.join(...)` on the repository query, exactly as before.

---

## Wiring it into a generic view

Set `filter` to the matching filter class and `repository` to an instance. Nothing else is needed — the view derives the page container from the filter:

```python
from sqlargon import Base
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_views import ViewRouter
from fastapi_views.filters.models import ModelFilter, PaginationFilter
from fastapi_views.integrations.sqlargon import PaginatedRepository
from fastapi_views.models import BaseSchema
from fastapi_views.views.generics import AsyncGenericViewSet


class Fruit(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class FruitRepository(PaginatedRepository[Fruit]):
    default_order_by = Fruit.id.asc()


class FruitId(BaseSchema):
    id: int


class FruitSchema(FruitId):
    name: str


class CreateFruit(BaseSchema):
    name: str


class FruitFilter(PaginationFilter, ModelFilter):
    name: str | None = None


class FruitViewSet(AsyncGenericViewSet):
    api_component_name = "Fruit"
    primary_key = FruitId
    response_schema = FruitSchema
    create_schema = CreateFruit
    update_schema = CreateFruit
    partial_update_schema = CreateFruit
    filter = FruitFilter
    repository = FruitRepository()


router = ViewRouter(prefix="/fruits")
router.register_view(FruitViewSet)
```

`GET /fruits?name=apple&page=2&page_size=10` now returns a `NumberedPage[FruitSchema]`, and the remaining CRUD actions map onto `create`, `get`, `update_one` and `delete_one`, which `sqlargon.SQLAlchemyRepository` already provides.

!!! note
    A repository instance resolves the default `sqlargon` database eagerly, so
    call `set_default_database(...)` (or let sqlargon build the default from the
    environment) **before** the view class body is evaluated.

---

## Bulk views

`sqlargon.SQLAlchemyRepository` also implements all four bulk methods — `create_many`, `bulk_update`, `update_many` and `delete_many` — so the same repository can back [bulk views](bulk.md):

```python
class FruitBulkViewSet(AsyncBulkAPIViewSet):
    response_schema = FruitSchema
    create_schema = CreateFruit
    bulk_update_schema = FruitSchema   # carries `id`
    update_schema = CreateFruit
    filter = FruitBulkFilter
    repository = FruitRepository()
```

!!! warning
    `sqlargon.SQLAlchemyRepository` is not a *strictly* conforming `AsyncBulkRepository`:
    its `bulk_update(values, *args, on_=None)` declares no `**kwargs`, so **any**
    `repository_options` key other than `on_` raises `TypeError` on `PUT /bulk`. Its
    `create_many` takes `items` as positional-or-keyword, which also fails a static
    conformance check (harmless at runtime).

Be careful with `repository_options` here: bulk views forward it to all four calls, and sqlargon's `update_many` / `delete_many` turn their keyword arguments into `WHERE` criteria, so only column criteria belong there for those actions. `create_many` accepts `ignore_conflicts` (and tolerates extra keywords), while `bulk_update` accepts only `on_`. Override `get_repository_options(action)` to return per-action options rather than one shared dict — that is the way to keep the two filtered actions' criteria separate from `on_`.

---

## Passing resolver context

Generic views forward `get_pagination_kwargs()` to `get_filtered_page`, which passes it on to the resolver as context. Use it when the filter reaches across a relationship:

```python
class FruitViewSet(AsyncGenericViewSet):
    ...

    def get_pagination_kwargs(self) -> dict[str, Any]:
        return {"basket": {"table": Basket}}
```
