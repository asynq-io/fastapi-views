from __future__ import annotations

from typing import ClassVar

import pytest

from fastapi_views.filters.models import (
    ModelFilter,
    OrderingFilter,
    PaginationFilter,
    SearchFilter,
    TokenPaginationFilter,
)
from fastapi_views.filters.operations import (
    FilterOperation,
    LogicalOperation,
    SortOperation,
)
from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver


class MockExpression:
    """Represents a compiled SQLAlchemy-like expression."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __or__(self, other: object) -> MockExpression:
        v = other.value if isinstance(other, MockExpression) else str(other)
        return MockExpression(f"({self.value} OR {v})")

    def __and__(self, other: object) -> MockExpression:
        v = other.value if isinstance(other, MockExpression) else str(other)
        return MockExpression(f"({self.value} AND {v})")

    def __repr__(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


class MockColumn:
    """Mimics a SQLAlchemy Column, returning MockExpression objects."""

    def __init__(self, name: str) -> None:
        self.name = name

    # Comparison operators
    def __eq__(self, other: object) -> MockExpression:  # type: ignore[override]
        return MockExpression(f"{self.name} = {other}")

    def __ne__(self, other: object) -> MockExpression:  # type: ignore[override]
        return MockExpression(f"{self.name} != {other}")

    def __lt__(self, other: object) -> MockExpression:
        return MockExpression(f"{self.name} < {other}")

    def __le__(self, other: object) -> MockExpression:
        return MockExpression(f"{self.name} <= {other}")

    def __gt__(self, other: object) -> MockExpression:
        return MockExpression(f"{self.name} > {other}")

    def __ge__(self, other: object) -> MockExpression:
        return MockExpression(f"{self.name} >= {other}")

    # Logical
    def __and__(self, other: object) -> MockExpression:
        return MockExpression(f"({self.name} AND {other})")

    def __or__(self, other: object) -> MockExpression:
        return MockExpression(f"({self.name} OR {other})")

    # Method operators (used via Column protocol unbound methods)
    def in_(self, values: object) -> MockExpression:
        return MockExpression(f"{self.name} IN ({values})")

    def not_in_(self, values: object) -> MockExpression:
        return MockExpression(f"{self.name} NOT IN ({values})")

    def is_(self, value: object) -> MockExpression:
        return MockExpression(f"{self.name} IS {value}")

    def is_not(self, value: object) -> MockExpression:
        return MockExpression(f"{self.name} IS NOT {value}")

    def like(self, value: str) -> MockExpression:
        return MockExpression(f"{self.name} LIKE {value}")

    def ilike(self, value: str) -> MockExpression:
        return MockExpression(f"{self.name} ILIKE {value}")

    def desc(self) -> MockExpression:
        return MockExpression(f"{self.name} DESC")

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return self.name


class MockMapper:
    def __init__(self, cls: type) -> None:
        self.class_ = cls


class MockModel:
    __tablename__ = "items"
    name = MockColumn("name")
    age = MockColumn("age")


class OtherModel:
    __tablename__ = "users"
    username = MockColumn("username")


class AnotherModel:
    __tablename__ = "other"
    name = MockColumn("other_name")


class MockRegistry:
    mappers: ClassVar[list] = [MockMapper(MockModel), MockMapper(OtherModel)]


class MockFilterModel:
    __tablename__ = "items"
    name = MockColumn("name")
    age = MockColumn("age")
    registry = MockRegistry()


class MockQueryset:
    def __init__(self) -> None:
        self._filters: list = []
        self._order_by: list = []
        self._offset_val: int | None = None
        self._limit_val: int | None = None

    def filter(self, *args: object) -> MockQueryset:
        self._filters.extend(args)
        return self

    def order_by(self, *args: object) -> MockQueryset:
        self._order_by.extend(args)
        return self

    def offset(self, val: int) -> MockQueryset:
        self._offset_val = val
        return self

    def limit(self, val: int) -> MockQueryset:
        self._limit_val = val
        return self


class ItemFilter(ModelFilter):
    name: str | None = None
    age: str | None = None


class SearchableFilter(SearchFilter, OrderingFilter):
    ordering_fields: ClassVar[set[str]] = {"name", "age"}
    search_fields: ClassVar[set[str]] = {"name", "age"}


@pytest.fixture
def resolver() -> SQLAlchemyFilterResolver:
    SQLAlchemyFilterResolver._cache.clear()
    r = SQLAlchemyFilterResolver()
    r.filter_model = MockFilterModel
    return r


@pytest.fixture
def qs() -> MockQueryset:
    return MockQueryset()


def test_resolve_eq(resolver: SQLAlchemyFilterResolver) -> None:
    op = FilterOperation(field="name", operator="eq", values="Alice")
    result = resolver.resolve(op)
    assert "name = Alice" in str(result)


def test_resolve_ne(resolver: SQLAlchemyFilterResolver) -> None:
    op = FilterOperation(field="name", operator="ne", values="Alice")
    result = resolver.resolve(op)
    assert "name != Alice" in str(result)


def test_resolve_lt(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(FilterOperation(field="age", operator="lt", values=30))
    assert "< 30" in str(result)


def test_resolve_le(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(FilterOperation(field="age", operator="le", values=30))
    assert "<= 30" in str(result)


def test_resolve_gt(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(FilterOperation(field="age", operator="gt", values=18))
    assert "> 18" in str(result)


def test_resolve_ge(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(FilterOperation(field="age", operator="ge", values=18))
    assert ">= 18" in str(result)


def test_resolve_in(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(
        FilterOperation(field="name", operator="in", values=["A", "B"])
    )
    assert "IN" in str(result)


def test_resolve_not_in(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(
        FilterOperation(field="name", operator="not_in", values=["A"])
    )
    assert "NOT IN" in str(result)


def test_resolve_is_null_true(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(
        FilterOperation(field="name", operator="is_null", values=True)
    )
    assert "IS" in str(result)
    assert "None" in str(result)


def test_resolve_is_null_false(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(
        FilterOperation(field="name", operator="is_null", values=False)
    )
    assert "IS NOT" in str(result)


def test_resolve_like(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(
        FilterOperation(field="name", operator="like", values="Al")
    )
    assert "LIKE" in str(result)


def test_resolve_ilike(resolver: SQLAlchemyFilterResolver) -> None:
    result = resolver.resolve(
        FilterOperation(field="name", operator="ilike", values="al")
    )
    assert "ILIKE" in str(result)


def test_resolve_sort_asc(resolver: SQLAlchemyFilterResolver) -> None:
    op = SortOperation(field="name", desc=False)
    result = resolver.resolve(op)
    # asc returns the column itself
    assert result is MockFilterModel.name


def test_resolve_sort_desc(resolver: SQLAlchemyFilterResolver) -> None:
    op = SortOperation(field="name", desc=True)
    result = resolver.resolve(op)
    assert "DESC" in str(result)


def test_resolve_logical_or(resolver: SQLAlchemyFilterResolver) -> None:
    op1 = FilterOperation(field="name", operator="eq", values="Alice")
    op2 = FilterOperation(field="name", operator="eq", values="Bob")
    logical = LogicalOperation(operator="or", values=[op1, op2])
    result = resolver.resolve(logical)
    assert "OR" in str(result)


def test_resolve_logical_and(resolver: SQLAlchemyFilterResolver) -> None:
    op1 = FilterOperation(field="name", operator="eq", values="Alice")
    op2 = FilterOperation(field="age", operator="eq", values=25)
    logical = LogicalOperation(operator="and", values=[op1, op2])
    result = resolver.resolve(logical)
    assert "AND" in str(result)


def test_resolve_model_field_simple(resolver: SQLAlchemyFilterResolver) -> None:
    op = FilterOperation(field="name", operator="eq", values="test")
    result = resolver.resolve_model_field(op)
    assert result is MockFilterModel.name


def test_resolve_model_field_from_table_context(
    resolver: SQLAlchemyFilterResolver,
) -> None:
    op = FilterOperation(field="name", operator="eq", values="test")
    result = resolver.resolve_model_field(op, table=AnotherModel)
    assert result is AnotherModel.name


def test_resolve_model_field_nested_from_context(
    resolver: SQLAlchemyFilterResolver,
) -> None:
    op = FilterOperation(field="related__username", operator="eq", values="alice")
    result = resolver.resolve_model_field(op, related={"table": OtherModel})
    assert result is OtherModel.username


def test_resolve_model_field_nested_from_registry(
    resolver: SQLAlchemyFilterResolver,
) -> None:
    SQLAlchemyFilterResolver._cache.clear()
    op = FilterOperation(field="items__name", operator="eq", values="test")
    result = resolver.resolve_model_field(op)
    assert result is MockModel.name


def test_get_model_cls_from_registry(resolver: SQLAlchemyFilterResolver) -> None:
    SQLAlchemyFilterResolver._cache.clear()
    result = resolver._get_model_cls("users")
    assert result is OtherModel
    assert "users" in SQLAlchemyFilterResolver._cache


def test_get_model_cls_from_cache(resolver: SQLAlchemyFilterResolver) -> None:
    SQLAlchemyFilterResolver._cache.clear()
    SQLAlchemyFilterResolver._cache["cached_model"] = MockModel
    result = resolver._get_model_cls("cached_model")
    assert result is MockModel


def test_get_model_cls_not_found(resolver: SQLAlchemyFilterResolver) -> None:
    SQLAlchemyFilterResolver._cache.clear()
    result = resolver._get_model_cls("nonexistent_table")
    assert result is None


def test_get_model_cls_registry_lookup_cached(
    resolver: SQLAlchemyFilterResolver,
) -> None:
    SQLAlchemyFilterResolver._cache.clear()
    resolver._get_model_cls("items")  # First: populates cache
    cached_result = resolver._get_model_cls("items")  # Second: from cache
    assert cached_result is MockModel


def test_get_filters_single(resolver: SQLAlchemyFilterResolver) -> None:
    f = ItemFilter(name="Alice")
    filters = resolver.get_filters(f)
    assert len(filters) == 1
    assert "name = Alice" in str(filters[0])


def test_get_filters_multiple(resolver: SQLAlchemyFilterResolver) -> None:
    f = ItemFilter(name="Alice", age="25")
    filters = resolver.get_filters(f)
    expected_filter_count = 2
    assert len(filters) == expected_filter_count


def test_get_filters_empty(resolver: SQLAlchemyFilterResolver) -> None:
    f = ItemFilter()
    filters = resolver.get_filters(f)
    assert filters == []


def test_get_order_by_asc(resolver: SQLAlchemyFilterResolver) -> None:
    f = SearchableFilter(sort=["name"], query=None)
    order_by = resolver.get_order_by(f)
    assert len(order_by) == 1
    assert order_by[0] is MockFilterModel.name


def test_get_order_by_desc(resolver: SQLAlchemyFilterResolver) -> None:
    f = SearchableFilter(sort=["-age"], query=None)
    order_by = resolver.get_order_by(f)
    assert len(order_by) == 1
    assert "DESC" in str(order_by[0])


def test_get_order_by_with_extra(resolver: SQLAlchemyFilterResolver) -> None:
    f = SearchableFilter(sort=["name"], query=None)
    extra_col = MockColumn("extra")
    order_by = resolver.get_order_by(f, extra=[extra_col])
    expected_order_by_count = 2
    assert len(order_by) == expected_order_by_count
    assert order_by[-1] is extra_col


def test_apply_filter_no_conditions(
    resolver: SQLAlchemyFilterResolver, qs: MockQueryset
) -> None:
    f = ItemFilter()
    result = resolver.apply_filter(f, qs)
    assert result is qs
    assert result._filters == []


def test_apply_filter_with_field(
    resolver: SQLAlchemyFilterResolver, qs: MockQueryset
) -> None:
    f = ItemFilter(name="Alice")
    result = resolver.apply_filter(f, qs)
    assert len(result._filters) == 1
    assert "name = Alice" in str(result._filters[0])


def test_apply_filter_pagination(
    resolver: SQLAlchemyFilterResolver, qs: MockQueryset
) -> None:
    page_size = 10
    expected_offset = 20
    f = PaginationFilter(page=3, page_size=page_size)
    result = resolver.apply_filter(f, qs)
    assert result._offset_val == expected_offset
    assert result._limit_val == page_size


def test_apply_filter_ordering(
    resolver: SQLAlchemyFilterResolver, qs: MockQueryset
) -> None:
    expected_order_by_count = 2
    f = SearchableFilter(sort=["name", "-age"], query=None)
    result = resolver.apply_filter(f, qs)
    assert len(result._order_by) == expected_order_by_count


def test_apply_filter_exclude_filter(
    resolver: SQLAlchemyFilterResolver, qs: MockQueryset
) -> None:
    f = ItemFilter(name="Alice")
    result = resolver.apply_filter(f, qs, exclude={"filter"})
    assert result._filters == []


def test_apply_filter_exclude_sort(
    resolver: SQLAlchemyFilterResolver, qs: MockQueryset
) -> None:
    f = SearchableFilter(sort=["name"], query=None)
    result = resolver.apply_filter(f, qs, exclude={"sort"})
    assert result._order_by == []


def test_apply_filter_exclude_paginate(
    resolver: SQLAlchemyFilterResolver, qs: MockQueryset
) -> None:
    f = PaginationFilter(page=2, page_size=10)
    result = resolver.apply_filter(f, qs, exclude={"paginate"})
    assert result._offset_val is None
    assert result._limit_val is None


def test_apply_filter_token_pagination_raises(
    resolver: SQLAlchemyFilterResolver,
    qs: MockQueryset,
) -> None:
    f = TokenPaginationFilter(page_size=10)
    with pytest.raises(NotImplementedError):
        resolver.apply_filter(f, qs)


def test_apply_token_pagination_raises(
    resolver: SQLAlchemyFilterResolver,
    qs: MockQueryset,
) -> None:
    with pytest.raises(NotImplementedError):
        resolver.apply_token_pagination(qs, "some_token", 10)


def test_apply_token_pagination_no_token_raises(
    resolver: SQLAlchemyFilterResolver,
    qs: MockQueryset,
) -> None:
    with pytest.raises(NotImplementedError):
        resolver.apply_token_pagination(qs, None, 10)
