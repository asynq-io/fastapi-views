from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
from uuid import UUID  # noqa: TC003  # resolved at runtime by sqlalchemy/pydantic

import pytest
from sqlalchemy import ForeignKey
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.pool import StaticPool
from sqlargon import Base, Database, SQLAlchemyRepository, set_default_database
from sqlargon.mixins import UUIDModelMixin
from sqlargon.pagination import CursorPage, TotalNumberedPage, TotalOffsetPage
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT

from fastapi_views.filters.models import (
    BaseFilter,
    CursorPaginationFilter,
    FieldsFilter,
    IncludeFilter,
    ModelFilter,
    OffsetLimitFilter,
    OrderingFilter,
    PaginationFilter,
    SearchFilter,
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
    basket_id: Mapped[int | None] = mapped_column(ForeignKey("basket.id"))
    basket: Mapped[Basket | None] = relationship(back_populates="fruits")


class Basket(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    fruits: Mapped[list[Fruit]] = relationship(back_populates="basket")


class FruitRepository(PaginatedRepository[Fruit]):
    default_order_by = Fruit.id.asc()


class FruitOffsetRepository(OffsetPaginatedRepository[Fruit]):
    default_order_by = Fruit.id.asc()


class FruitCursorRepository(CursorPaginatedRepository[Fruit]):
    default_order_by = Fruit.id.asc()


if TYPE_CHECKING:
    # paginated repositories must satisfy the AsyncRepository protocol
    _protocol_check: AsyncRepository[Fruit] = cast("FruitRepository", None)
    # sqlargon implements all four bulk methods, but its create_many takes `items`
    # as positional-or-keyword and its bulk_update accepts only `on_`, so it is not
    # a strictly conforming AsyncBulkRepository: it cannot receive arbitrary
    # `repository_options` on bulk_create / bulk_update.
    _bulk_protocol_check: AsyncBulkRepository[Fruit] = cast(  # type: ignore[assignment]
        "FruitRepository", None
    )


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
            "/test/bulk", json=[{"name": "apple"}, {"name": "banana"}]
        )
        assert created.status_code == HTTP_201_CREATED
        assert [item["name"] for item in created.json()] == ["apple", "banana"]

        item_id = created.json()[0]["id"]
        updated = await client.put(
            "/test/bulk", json=[{"id": item_id, "name": "apricot"}]
        )
        assert updated.status_code == HTTP_204_NO_CONTENT
        renamed = await FruitRepository().get(id=item_id)
        assert renamed is not None
        assert renamed.name == "apricot"

        patched = await client.patch(
            "/test/bulk", params={"name": "banana"}, json={"name": "blueberry"}
        )
        assert patched.status_code == HTTP_200_OK
        assert [item["name"] for item in patched.json()] == ["blueberry"]

        deleted = await client.delete("/test/bulk", params={"name": "apricot"})
        assert deleted.status_code == HTTP_204_NO_CONTENT
        assert await FruitRepository().count() == 1


class FruitWithBasketRepository(PaginatedRepository[Fruit]):
    default_order_by = Fruit.id.asc()
    select_related = ("basket",)


class FruitPerOpRepository(PaginatedRepository[Fruit]):
    default_order_by = Fruit.id.asc()
    select_related: ClassVar[dict[str, tuple[str, ...]]] = {"get": ("basket",)}


class BasketRepository(PaginatedRepository[Basket]):
    default_order_by = Basket.id.asc()
    select_related = ("fruits",)


class FruitIncludeFilter(PaginationFilter, IncludeFilter):
    related_fields: ClassVar[set[str]] = {"basket"}


class FruitFieldsFilter(FieldsFilter):
    pass


class BasketSchema(BaseSchema):
    id: int
    name: str


class FruitWithBasketSchema(BaseSchema):
    id: int
    name: str
    basket: BasketSchema | None = None


BASKET_IDS = {1: 1, 2: 1, 3: 2}


@pytest.fixture
async def seeded_related_db(db: Database) -> Database:
    basket_repo = BasketRepository()
    await basket_repo.create(id=1, name="red")
    await basket_repo.create(id=2, name="green")
    fruit_repo = FruitRepository()
    for pk, name in enumerate(NAMES, start=1):
        await fruit_repo.create(id=pk, name=name, basket_id=BASKET_IDS.get(pk))
    return db


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_select_related_loads_relation_on_get():
    fruit = await FruitWithBasketRepository().get(id=1)
    assert fruit is not None
    assert "basket" not in sa_inspect(fruit).unloaded
    assert fruit.basket is not None
    assert fruit.basket.name == "red"


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_relation_stays_lazy_without_select_related():
    fruit = await FruitRepository().get(id=1)
    assert fruit is not None
    assert "basket" in sa_inspect(fruit).unloaded


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_select_related_loads_relation_on_list():
    fruits = await FruitWithBasketRepository().list()
    assert [fruit.name for fruit in fruits] == NAMES
    assert all("basket" not in sa_inspect(fruit).unloaded for fruit in fruits)


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_select_related_mapping_applies_per_operation():
    fruit = await FruitPerOpRepository().get(id=1)
    assert fruit is not None
    assert "basket" not in sa_inspect(fruit).unloaded

    fruits = await FruitPerOpRepository().list()
    assert all("basket" in sa_inspect(fruit).unloaded for fruit in fruits)


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_select_related_loads_to_many_relation():
    basket = await BasketRepository().get(id=1)
    assert basket is not None
    assert "fruits" not in sa_inspect(basket).unloaded
    assert [fruit.name for fruit in basket.fruits] == ["apple", "banana"]


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_select_related_applies_to_filtered_page():
    page = await FruitWithBasketRepository().get_filtered_page(
        PaginationFilter(page=1, page_size=2)
    )
    assert page.total_items == 5
    assert all("basket" not in sa_inspect(fruit).unloaded for fruit in page.items)


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_include_filter_loads_requested_relation():
    page = await FruitRepository().get_filtered_page(
        FruitIncludeFilter(include={"basket"}, page=1, page_size=10)
    )
    assert all("basket" not in sa_inspect(fruit).unloaded for fruit in page.items)


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_include_filter_defaults_to_lazy():
    page = await FruitRepository().get_filtered_page(
        FruitIncludeFilter(include=None, page=1, page_size=10)
    )
    assert all("basket" in sa_inspect(fruit).unloaded for fruit in page.items)


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_fields_filter_nested_field_loads_relation():
    repo = FruitRepository().with_filter(
        FruitFieldsFilter(fields={"name", "basket__name"})
    )
    fruits = await repo.all()
    assert all("basket" not in sa_inspect(fruit).unloaded for fruit in fruits)


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_generic_list_view_returns_nested_relation():
    class FruitListView(AsyncGenericListAPIView):
        response_schema = FruitWithBasketSchema
        filter = FruitFilter
        repository = FruitWithBasketRepository()

    async with view_client(FruitListView) as client:
        response = await client.get("/test", params={"page": 1, "page_size": 2})
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["items"] == [
            {"id": 1, "name": "apple", "basket": {"id": 1, "name": "red"}},
            {"id": 2, "name": "banana", "basket": {"id": 1, "name": "red"}},
        ]


class ItemModel(UUIDModelMixin, Base):
    name: Mapped[str]
    tags: Mapped[list[TagModel]] = relationship(
        secondary="item_tag_model", back_populates="items"
    )


class ItemTagModel(Base):
    item_id: Mapped[UUID] = mapped_column(ForeignKey("item_model.id"), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("tag_model.id"), primary_key=True)


class TagModel(UUIDModelMixin, Base):
    name: Mapped[str]
    items: Mapped[list[ItemModel]] = relationship(
        secondary="item_tag_model", back_populates="tags"
    )


class ItemRepository(PaginatedRepository[ItemModel]):
    """Generic over ItemModel; tags are reached by relationship path alone."""

    default_order_by = ItemModel.name.asc()
    select_related = ("tags",)


class TagRepository(SQLAlchemyRepository[TagModel]):
    pass


class ItemTagRepository(SQLAlchemyRepository[ItemTagModel]):
    pass


class ItemSearchFilter(PaginationFilter, SearchFilter):
    search_fields: ClassVar[set[str]] = {"tags__name"}


class ItemSortByTagFilter(PaginationFilter, OrderingFilter):
    ordering_fields: ClassVar[set[str]] = {"tags__name"}


class TagSchema(BaseSchema):
    name: str


class ItemSchema(BaseSchema):
    name: str
    tags: list[TagSchema]


ITEM_TAGS = {
    "desk": ("furniture",),
    "laptop": ("electronics", "portable"),
    "phone": ("electronics",),
    "rock": (),
}


@pytest.fixture
async def seeded_tagged_db(db: Database) -> Database:
    tag_repo = TagRepository()
    tags = {
        name: await tag_repo.create(name=name)
        for name in ("electronics", "furniture", "portable")
    }
    item_repo = ItemRepository()
    link_repo = ItemTagRepository()
    for item_name, tag_names in ITEM_TAGS.items():
        item = await item_repo.create(name=item_name)
        assert item is not None
        for tag_name in tag_names:
            tag = tags[tag_name]
            assert tag is not None
            await link_repo.create(item_id=item.id, tag_id=tag.id)
    return db


def test_related_column_is_resolved_through_the_relationship():
    assert ItemRepository().resolve_model_field("tags__name") is TagModel.name


def test_related_predicate_compiles_to_exists_without_a_join():
    (clause,) = ItemRepository().get_filters(ItemSearchFilter(query="a"))
    sql = str(clause)
    assert "EXISTS" in sql
    assert "JOIN" not in sql


def test_sorting_across_a_relationship_is_rejected():
    with pytest.raises(NotImplementedError, match="needs an explicit join"):
        ItemRepository().get_order_by(ItemSortByTagFilter(sort=["tags__name"]))


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_tagged_db")
async def test_search_filter_matches_items_by_related_tag_name():
    page = await ItemRepository().get_filtered_page(
        ItemSearchFilter(query="electronics", page=1, page_size=10)
    )
    assert [item.name for item in page.items] == ["laptop", "phone"]
    assert page.total_items == 2


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_tagged_db")
async def test_search_filter_returns_item_once_when_several_tags_match():
    page = await ItemRepository().get_filtered_page(
        ItemSearchFilter(query="o", page=1, page_size=10)
    )
    assert [item.name for item in page.items] == ["laptop", "phone"]
    assert page.total_items == 2


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_tagged_db")
async def test_search_filter_pages_by_item_not_by_joined_row():
    page = await ItemRepository().get_filtered_page(
        ItemSearchFilter(query="o", page=1, page_size=2)
    )
    assert [item.name for item in page.items] == ["laptop", "phone"]
    assert not page.has_more


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_tagged_db")
async def test_search_filter_without_query_keeps_untagged_items():
    page = await ItemRepository().get_filtered_page(
        ItemSearchFilter(query=None, page=1, page_size=10)
    )
    assert [item.name for item in page.items] == ["desk", "laptop", "phone", "rock"]
    assert page.total_items == 4


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_tagged_db")
async def test_matching_item_still_carries_its_non_matching_tags():
    page = await ItemRepository().get_filtered_page(
        ItemSearchFilter(query="portable", page=1, page_size=10)
    )
    (item,) = page.items
    assert "tags" not in sa_inspect(item).unloaded
    assert sorted(tag.name for tag in item.tags) == ["electronics", "portable"]


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_tagged_db")
async def test_generic_list_view_searches_by_related_tag_name():
    class ItemListView(AsyncGenericListAPIView):
        response_schema = ItemSchema
        filter = ItemSearchFilter
        repository = ItemRepository()

    async with view_client(ItemListView) as client:
        response = await client.get("/test", params={"q": "portable"})
        assert response.status_code == HTTP_200_OK
        data = response.json()
        (item,) = data["items"]
        assert item["name"] == "laptop"
        assert sorted(tag["name"] for tag in item["tags"]) == [
            "electronics",
            "portable",
        ]
        assert data["total_items"] == 1


class FruitByBasketFilter(PaginationFilter, ModelFilter):
    basket__name__eq: str | None = None


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_related_db")
async def test_to_one_relationship_filters_without_a_join():
    (clause,) = FruitRepository().get_filters(
        FruitByBasketFilter(basket__name__eq="red")
    )
    assert "JOIN" not in str(clause)

    page = await FruitRepository().get_filtered_page(
        FruitByBasketFilter(basket__name__eq="red", page=1, page_size=10)
    )
    assert [fruit.name for fruit in page.items] == ["apple", "banana"]


def test_explicit_table_context_still_yields_a_plain_column():
    resolved = FruitRepository().resolve_model_field(
        "basket__name", basket={"table": Basket}
    )
    assert resolved is Basket.name
