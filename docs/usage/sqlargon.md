# sqlargon

[Generic views](generics.md) are ORM-agnostic: they only need an object satisfying the `AsyncRepository` protocol. The `fastapi_views.integrations.sqlargon` module ships that object ready-made for [sqlargon](https://github.com/asynq-io/sqlargon), a thin async SQLAlchemy repository layer — so a fully filtered, paginated CRUD resource is three class attributes and no query code.

The integration adds two things on top of `sqlargon.SQLAlchemyRepository`:

- it applies FastAPI Views [filters](filters.md) to the repository's query, and
- it implements `get_filtered_page`, the one repository method generic views need for pagination.

---

## Installation

`sqlargon` is not pulled in by any extra, so install it alongside FastAPI Views:

```shell
pip install fastapi-views sqlargon
```

Cursor pagination additionally needs `sqlakeyset`:

```shell
pip install "sqlargon[pagination]"
```

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
    default_order_by = Fruit.__table__.c.id


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

`sqlargon.SQLAlchemyRepository` also implements `create_many`, `bulk_update`, `update_many` and `delete_many` — exactly the `AsyncBulkRepository` protocol — so the same repository can back [bulk views](bulk.md):

```python
class FruitBulkViewSet(AsyncBulkAPIViewSet):
    response_schema = FruitSchema
    create_schema = CreateFruit
    bulk_update_schema = FruitSchema   # carries `id`
    update_schema = CreateFruit
    filter = FruitBulkFilter
    repository = FruitRepository()
```

---

## Passing resolver context

Generic views forward `get_pagination_kwargs()` to `get_filtered_page`, which passes it on to the resolver as context. Use it when the filter reaches across a relationship:

```python
class FruitViewSet(AsyncGenericViewSet):
    ...

    def get_pagination_kwargs(self) -> dict[str, Any]:
        return {"basket": {"table": Basket}}
```
