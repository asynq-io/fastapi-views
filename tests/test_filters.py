from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from fastapi_views.filters.dependencies import FilterDepends, NestedFilter
from fastapi_views.filters.models import (
    BaseFilter,
    FieldsFilter,
    Filter,
    ModelFilter,
    OrderingFilter,
    PaginationFilter,
)
from fastapi_views.filters.operations import (
    FieldOperation,
    FilterOperation,
    LogicalOperation,
)
from fastapi_views.filters.resolvers.objects import ObjectFilterResolver


@dataclass
class User:
    name: str
    age: int


class UserFilter(Filter):
    ordering_fields: ClassVar[set[str]] = {"name", "age"}
    search_fields: ClassVar[set[str]] = {"name"}

    name: str | None = None
    age: str | None = None


@pytest.fixture
def users():
    return [User("John", 25), User("Jane", 30), User("Alice", 35)]


@pytest.fixture
def resolver():
    return ObjectFilterResolver()


def get_user_filter(**kwargs):
    kwargs.setdefault("query", None)
    kwargs.setdefault("sort", None)
    kwargs.setdefault("fields", None)
    kwargs.setdefault("page", 1)
    kwargs.setdefault("page_size", 10)
    return UserFilter(**kwargs)


def test_model_filter(users, resolver: ObjectFilterResolver):
    user_filter = get_user_filter(name="John")
    filtered_users = resolver.apply_filter(user_filter, users)
    assert len(filtered_users) == 1


def test_order_by_filter(users, resolver):
    filter_ = get_user_filter(sort=["name", "-age"])
    ordered_users = resolver.apply_filter(filter_, users)
    assert ordered_users == [User("Alice", 35), User("Jane", 30), User("John", 25)]


def test_search_users(users, resolver):
    filter_ = get_user_filter(query="J", sort=["name"])
    filtered_users = resolver.apply_filter(filter_, users)
    assert filtered_users == [User("Jane", 30), User("John", 25)]


def test_field_operation_set_prefix():
    op = FieldOperation(field="name")
    op.set_prefix("user")
    assert op.field == "user__name"


def test_logical_operation_set_prefix():
    inner1 = FilterOperation(field="first_name", operator="eq", values="Alice")
    inner2 = FilterOperation(field="last_name", operator="eq", values="Smith")
    logical = LogicalOperation(operator="or", values=[inner1, inner2])
    logical.set_prefix("person")
    assert inner1.field == "person__first_name"
    assert inner2.field == "person__last_name"


def test_model_filter_nested_base_filter():
    class AddressFilter(BaseFilter):
        city: str | None = None

        def get_filters(self):
            filters = super().get_filters()
            if self.city is not None:
                filters.append(
                    FilterOperation(field="city", operator="eq", values=self.city)
                )
            return filters

    class PersonFilter(ModelFilter):
        address: AddressFilter | None = None

    f = PersonFilter(address=AddressFilter(city="London"))
    result = f.get_filters()
    assert len(result) == 1
    assert result[0].field == "address__city"


def test_model_filter_double_underscore_field():
    class AgeFilter(ModelFilter):
        age__gt: int | None = None

    age_value = 18
    f = AgeFilter(age__gt=age_value)
    result = f.get_filters()
    assert len(result) == 1
    assert result[0].field == "age"
    assert result[0].operator == "gt"
    assert result[0].values == age_value


def test_model_filter_get_filters_includes_kwargs():
    class NameFilter(ModelFilter):
        pass

    f = NameFilter()
    f.with_kwargs(name="alice")
    result = f.get_filters()
    assert len(result) == 1
    assert result[0].field == "name"
    assert result[0].values == "alice"


def test_ordering_filter_invalid_sort():
    class MyFilter(OrderingFilter):
        ordering_fields: ClassVar[set[str]] = {"name", "age"}

    with pytest.raises(ValidationError, match="Unknown sort value"):
        MyFilter(sort=["invalid_field"])


def test_fields_filter_with_fields_from():
    class MyModel(BaseModel):
        name: str
        age: int

    class MyFieldsFilter(FieldsFilter):
        fields_from = MyModel

    f = MyFieldsFilter(fields={"name"})
    assert f.get_fields() == {"name"}


def test_fields_filter_get_fields_none():
    f = FieldsFilter(fields=None)
    assert f.get_fields() is None


def test_filter_depends_validation_error():
    filter_wrapper = FilterDepends(PaginationFilter).dependency

    with pytest.raises(RequestValidationError):
        filter_wrapper(page=-1)


def test_nested_filter_with_prefix():
    class MyFilter(BaseFilter):
        name: str | None = None

    wrapper_cls = NestedFilter(MyFilter, prefix="user").dependency
    instance = wrapper_cls(user__name="Alice")
    assert instance.name == "Alice"


def test_nested_filter_without_prefix():
    class SimpleFilter(BaseFilter):
        name: str | None = None

    wrapper_cls = NestedFilter(SimpleFilter).dependency
    instance = wrapper_cls(name="Bob")
    assert instance.name == "Bob"


def test_base_filter_as_kwargs():
    class MyFilter(BaseFilter):
        name: str | None = None
        age: int | None = None

    f = MyFilter(name="Alice", age=None)
    assert f.as_kwargs() == {"name": "Alice"}


def test_apply_fields_filter_removes_fields(users, resolver):
    filter_ = get_user_filter(fields={"age"})
    result = resolver.apply_filter(filter_, users)
    for obj in result:
        assert "age" not in obj.__dict__
