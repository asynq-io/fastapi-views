from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.pool import StaticPool
from sqlargon import Base, Database, set_default_database
from sqlargon.pagination import CursorPage, TotalNumberedPage, TotalOffsetPage
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT

from fastapi_views.filters.models import (
    BaseFilter,
    CursorPaginationFilter,
    ModelFilter,
    OffsetLimitFilter,
    PaginationFilter,
)
from fastapi_views.integrations.sqlargon import (
    CursorPaginatedRepository,
    OffsetPaginatedRepository,
    PaginatedRepository,
)
from fastapi_views.models import BaseSchema
from fastapi_views.views.bulk import AsyncBulkAPIViewSet
from fastapi_views.views.generics import AsyncGenericListAPIView

from .utils import view_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from typing import cast

    from fastapi_views.views.bulk import AsyncBulkRepository
    from fastapi_views.views.generics import AsyncRepository


class Fruit(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class FruitRepository(PaginatedRepository[Fruit]):
    default_order_by = Fruit.__table__.c.id


class FruitOffsetRepository(OffsetPaginatedRepository[Fruit]):
    default_order_by = Fruit.__table__.c.id


class FruitCursorRepository(CursorPaginatedRepository[Fruit]):
    default_order_by = Fruit.__table__.c.id


if TYPE_CHECKING:
    # paginated repositories must satisfy the AsyncRepository protocol
    _protocol_check: AsyncRepository[Fruit] = cast("FruitRepository", None)
    # bulk repositories must satisfy the AsyncBulkRepository protocol
    _bulk_protocol_check: AsyncBulkRepository[Fruit] = cast("FruitRepository", None)


class FruitFilter(PaginationFilter, ModelFilter):
    name: str | None = None


class FruitBulkFilter(BaseFilter):
    name: str | None = None


class FruitSchema(BaseSchema):
    id: int
    name: str


class FruitCreateSchema(BaseSchema):
    name: str


NAMES = ["apple", "banana", "cherry", "date", "elderberry"]


@pytest.fixture
async def db() -> AsyncGenerator[Database, None]:
    database = Database("sqlite+aiosqlite://", poolclass=StaticPool)
    set_default_database(database)
    await database.create_all()
    yield database
    await database.dispose()
    set_default_database(None)


@pytest.fixture
async def seeded_db(db: Database) -> Database:
    repo = FruitRepository()
    for pk, name in enumerate(NAMES, start=1):
        await repo.create(id=pk, name=name)
    return db


def test_filterable_repository_sets_filter_model():
    assert FruitRepository.filter_model is Fruit
    assert FruitOffsetRepository.filter_model is Fruit
    assert FruitCursorRepository.filter_model is Fruit


@pytest.mark.anyio
@pytest.mark.usefixtures("db")
async def test_repository_crud_roundtrip():
    repo = FruitRepository()
    created = await repo.create(id=1, name="apple")
    assert created is not None
    assert created.name == "apple"

    fetched = await repo.get(id=1)
    assert fetched is not None

    updated = await repo.update_one({"name": "apricot"}, id=1)
    assert updated is not None
    assert updated.name == "apricot"

    deleted = await repo.delete_one(id=1)
    assert deleted is not None
    assert await repo.get(id=1) is None


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_paginated_repository_returns_total_numbered_page():
    page = await FruitRepository().get_filtered_page(
        PaginationFilter(page=2, page_size=2)
    )
    assert isinstance(page, TotalNumberedPage)
    assert [fruit.name for fruit in page.items] == ["cherry", "date"]
    assert page.current_page == 2
    assert page.page_size == 2
    assert page.total_items == 5
    assert page.total_pages == 3
    assert page.has_more


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_paginated_repository_last_page_has_no_more():
    page = await FruitRepository().get_filtered_page(
        PaginationFilter(page=3, page_size=2)
    )
    assert [fruit.name for fruit in page.items] == ["elderberry"]
    assert not page.has_more


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_paginated_repository_applies_model_filter():
    page = await FruitRepository().get_filtered_page(
        FruitFilter(name="apple", page=1, page_size=10)
    )
    assert [fruit.name for fruit in page.items] == ["apple"]
    assert page.total_items == 1
    assert not page.has_more


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_offset_paginated_repository_returns_total_offset_page():
    page = await FruitOffsetRepository().get_filtered_page(
        OffsetLimitFilter(offset=1, limit=2)
    )
    assert isinstance(page, TotalOffsetPage)
    assert [fruit.name for fruit in page.items] == ["banana", "cherry"]
    assert page.offset == 1
    assert page.limit == 2
    assert page.total_items == 5
    assert page.has_more


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_cursor_paginated_repository_pages_forward():
    repo = FruitCursorRepository()
    first = await repo.get_filtered_page(CursorPaginationFilter(page_size=2))
    assert isinstance(first, CursorPage)
    assert [fruit.name for fruit in first.items] == ["apple", "banana"]
    assert first.has_next
    assert not first.has_previous

    second = await repo.get_filtered_page(
        CursorPaginationFilter(cursor=first.next_page, page_size=2)
    )
    assert [fruit.name for fruit in second.items] == ["cherry", "date"]
    assert second.has_previous


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_generic_list_view_returns_numbered_page():
    class FruitListView(AsyncGenericListAPIView):
        response_schema = FruitSchema
        filter = FruitFilter
        repository = FruitRepository()

    async with view_client(FruitListView) as client:
        response = await client.get("/test", params={"page": 1, "page_size": 2})
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["items"] == [
            {"id": 1, "name": "apple"},
            {"id": 2, "name": "banana"},
        ]
        assert data["current_page"] == 1
        assert data["total_items"] == 5
        assert data["has_more"] is True


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_generic_list_view_filters_by_model_field():
    class FruitListView(AsyncGenericListAPIView):
        response_schema = FruitSchema
        filter = FruitFilter
        repository = FruitRepository()

    async with view_client(FruitListView) as client:
        response = await client.get("/test", params={"name": "cherry"})
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["items"] == [{"id": 3, "name": "cherry"}]
        assert data["total_items"] == 1


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_generic_list_view_cursor_pagination_roundtrip():
    class FruitCursorListView(AsyncGenericListAPIView):
        response_schema = FruitSchema
        filter = CursorPaginationFilter
        repository = FruitCursorRepository()

    async with view_client(FruitCursorListView) as client:
        response = await client.get("/test", params={"page_size": 2})
        assert response.status_code == HTTP_200_OK
        first = response.json()
        assert [item["name"] for item in first["items"]] == ["apple", "banana"]
        assert first["next_page"] is not None

        response = await client.get(
            "/test", params={"cursor": first["next_page"], "page_size": 2}
        )
        assert response.status_code == HTTP_200_OK
        second = response.json()
        assert [item["name"] for item in second["items"]] == ["cherry", "date"]
        assert second["previous_page"] is not None


@pytest.mark.anyio
@pytest.mark.usefixtures("db")
async def test_bulk_repository_create_returns_created_rows():
    created = await FruitRepository().create_many(
        [{"id": 1, "name": "apple"}, {"id": 2, "name": "banana"}]
    )
    assert [(fruit.id, fruit.name) for fruit in created] == [
        (1, "apple"),
        (2, "banana"),
    ]


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_bulk_repository_bulk_update_matches_on_primary_key():
    await FruitRepository().bulk_update(
        [{"id": 1, "name": "apricot"}, {"id": 2, "name": "blueberry"}]
    )
    assert [fruit.name for fruit in await FruitRepository().list()] == [
        "apricot",
        "blueberry",
        "cherry",
        "date",
        "elderberry",
    ]


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_bulk_repository_bulk_update_with_empty_items_is_a_noop():
    assert await FruitRepository().bulk_update([]) is None


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_bulk_repository_update_many_by_criteria():
    updated = await FruitRepository().update_many({"name": "apricot"}, id=1)
    assert [(fruit.id, fruit.name) for fruit in updated] == [(1, "apricot")]
    assert await FruitRepository().get(name="apple") is None


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_bulk_repository_delete_by_criteria():
    repo = FruitRepository()
    await repo.delete_many(name="apple")
    assert await FruitRepository().get(name="apple") is None
    assert await FruitRepository().count() == 4


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_db")
async def test_bulk_repository_delete_stays_chainable():
    deleted = await FruitRepository().delete_one(id=1)
    assert deleted is not None
    await FruitRepository().remove(name="banana")
    assert await FruitRepository().count() == 3


@pytest.mark.anyio
@pytest.mark.usefixtures("db")
async def test_bulk_viewset_end_to_end():
    class FruitBulkViewSet(AsyncBulkAPIViewSet):
        response_schema = FruitSchema
        create_schema = FruitCreateSchema
        bulk_update_schema = FruitSchema
        update_schema = FruitCreateSchema
        filter = FruitBulkFilter
        repository = FruitRepository()

    async with view_client(FruitBulkViewSet) as client:
        created = await client.post(
            "/test/bulk-create", json=[{"name": "apple"}, {"name": "banana"}]
        )
        assert created.status_code == HTTP_201_CREATED
        assert [item["name"] for item in created.json()] == ["apple", "banana"]

        item_id = created.json()[0]["id"]
        updated = await client.put(
            "/test/bulk-update", json=[{"id": item_id, "name": "apricot"}]
        )
        assert updated.status_code == HTTP_204_NO_CONTENT
        renamed = await FruitRepository().get(id=item_id)
        assert renamed is not None
        assert renamed.name == "apricot"

        patched = await client.patch(
            "/test/bulk-update", params={"name": "banana"}, json={"name": "blueberry"}
        )
        assert patched.status_code == HTTP_200_OK
        assert [item["name"] for item in patched.json()] == ["blueberry"]

        deleted = await client.delete("/test/bulk-delete", params={"name": "apricot"})
        assert deleted.status_code == HTTP_204_NO_CONTENT
        assert await FruitRepository().count() == 1
