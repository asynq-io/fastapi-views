from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import ClassVar

import pytest
from fastapi import FastAPI, params
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from fastapi_views.filters.dependencies import FilterDepends, NestedFilter
from fastapi_views.filters.models import (
    BaseFilter,
    FieldsFilter,
    Filter,
    IncludeFilter,
    ModelFilter,
    OrderingFilter,
    PaginationFilter,
    SearchFilter,
)
from fastapi_views.filters.operations import (
    FieldOperation,
    FilterOperation,
    LogicalOperation,
)
from fastapi_views.filters.resolvers.objects import ObjectFilterResolver
from fastapi_views.filters.types import (
    QueryField,  # noqa: TC001  # resolved at runtime by pydantic
)


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


def test_include_filter_valid_values():
    class MyIncludeFilter(IncludeFilter):
        related_fields: ClassVar[set[str]] = {"author", "author__publisher"}

    f = MyIncludeFilter(include={"author", "author__publisher"})
    assert f.get_related() == {"author", "author__publisher"}


def test_include_filter_invalid_value():
    class MyIncludeFilter(IncludeFilter):
        related_fields: ClassVar[set[str]] = {"author"}

    with pytest.raises(ValidationError, match="Unknown include value"):
        MyIncludeFilter(include={"publisher"})


def test_include_filter_get_related_none():
    f = IncludeFilter(include=None)
    assert f.get_related() is None


def test_include_filter_excluded_from_kwargs():
    class MyIncludeFilter(IncludeFilter):
        related_fields: ClassVar[set[str]] = {"author"}

        name: str | None = None

    f = MyIncludeFilter(include={"author"}, name="x")
    assert f.as_kwargs() == {"name": "x"}


def test_include_filter_description_lists_related_fields():
    class MyIncludeFilter(IncludeFilter):
        related_fields: ClassVar[set[str]] = {"author"}

    query = next(
        meta
        for meta in MyIncludeFilter.model_fields["include"].metadata
        if isinstance(meta, params.Query)
    )
    assert "author" in (query.description or "")


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


def test_apply_fields_filter_keeps_only_requested_fields(users, resolver):
    filter_ = get_user_filter(fields={"age"})
    result = resolver.apply_filter(filter_, users)
    assert result
    for obj in result:
        assert set(obj.__dict__) == {"age"}


def test_apply_fields_filter_does_not_mutate_input(users, resolver):
    filter_ = get_user_filter(fields={"age"})
    resolver.apply_filter(filter_, users)
    for obj in users:
        assert set(obj.__dict__) == {"name", "age"}


def test_apply_fields_filter_without_fields_returns_queryset(users, resolver):
    filter_ = get_user_filter()
    assert resolver.apply_fields_filter(users, filter_) is users


def test_apply_fields_filter_supports_mappings():
    resolver = ObjectFilterResolver(getter=operator.itemgetter)
    rows = [{"name": "John", "age": 25}, {"name": "Jane", "age": 30}]
    result = resolver.apply_fields_filter(rows, FieldsFilter(fields={"name"}))
    assert result == [{"name": "John"}, {"name": "Jane"}]
    assert rows == [{"name": "John", "age": 25}, {"name": "Jane", "age": 30}]


def test_apply_fields_filter_ignores_objects_without_dict(resolver):
    queryset = [("John", 25)]
    assert resolver.apply_fields_filter(queryset, FieldsFilter(fields={"name"})) == [
        ("John", 25)
    ]


def test_query_backed_defaults_are_none_outside_a_request():
    assert OrderingFilter().sort is None
    assert OrderingFilter().order_by == []
    assert FieldsFilter().fields is None
    assert FieldsFilter().get_fields() is None
    assert SearchFilter().query is None
    assert SearchFilter().get_filters() == []


def test_filter_can_be_instantiated_without_arguments():
    filter_ = UserFilter()
    assert filter_.sort is None
    assert filter_.query is None
    assert filter_.fields is None
    assert filter_.order_by == []
    assert filter_.filters == []
    assert filter_.as_kwargs() == {}


def test_query_field_defaults_to_none():
    class TagFilter(ModelFilter):
        tags: QueryField[list[str]]
        age__gt: QueryField[int]

    filter_ = TagFilter()
    assert filter_.tags is None
    assert filter_.age__gt is None
    assert filter_.filters == []


def test_query_field_with_explicit_none_default_keeps_the_query_param():
    class TagFilter(ModelFilter):
        tags: QueryField[list[str]] = None

    app = FastAPI()

    @app.get("/items")
    def list_items(filter: TagFilter = FilterDepends(TagFilter)):  # noqa: ARG001
        return []

    operation = app.openapi()["paths"]["/items"]["get"]
    assert "requestBody" not in operation
    params = {param["name"]: param for param in operation["parameters"]}
    assert set(params) == {"tags"}
    assert params["tags"]["required"] is False


def test_multiple_query_fields_are_independent_parameters():
    class LookupFilter(ModelFilter):
        id__in: QueryField[list[int]]
        tag__not_in: QueryField[list[str]]
        active: QueryField[bool]

    app = FastAPI()

    @app.get("/items")
    def list_items(filter: LookupFilter = FilterDepends(LookupFilter)):  # noqa: ARG001
        return []

    operation = app.openapi()["paths"]["/items"]["get"]
    assert "requestBody" not in operation
    params = {param["name"]: param["schema"] for param in operation["parameters"]}
    assert set(params) == {"id__in", "tag__not_in", "active"}
    assert params["id__in"]["anyOf"][0] == {
        "items": {"type": "integer"},
        "type": "array",
    }
    assert params["tag__not_in"]["anyOf"][0] == {
        "items": {"type": "string"},
        "type": "array",
    }
    assert params["active"]["anyOf"][0] == {"type": "boolean"}


def test_fields_from_does_not_leak_into_the_base_filter():
    class MyModel(BaseModel):
        id: int
        name: str

    class NarrowedFilter(FieldsFilter):
        fields_from = MyModel

    assert NarrowedFilter.model_fields["fields"].annotation is not (
        FieldsFilter.model_fields["fields"].annotation
    )
    assert FieldsFilter(fields={"anything"}).get_fields() == {"anything"}
    with pytest.raises(ValidationError):
        NarrowedFilter(fields={"anything"})


def test_ordering_filter_description_is_not_shared_with_the_base_class():
    class ByName(OrderingFilter):
        ordering_fields: ClassVar[set[str]] = {"name"}

    base_param, sub_param = (
        cls.model_fields["sort"].metadata[0] for cls in (OrderingFilter, ByName)
    )
    assert "Available values" not in base_param.description
    assert "Available values: name" in sub_param.description


def test_query_parameters_of_a_full_filter():
    app = FastAPI()

    @app.get("/users")
    def list_users(filter: UserFilter = FilterDepends(UserFilter)):  # noqa: ARG001
        return []

    operation = app.openapi()["paths"]["/users"]["get"]
    assert "requestBody" not in operation
    params = {param["name"]: param for param in operation["parameters"]}
    assert set(params) == {
        "fields",
        "include",
        "q",
        "sort",
        "page",
        "page_size",
        "name",
        "age",
    }
    assert params["q"]["schema"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert params["fields"]["schema"]["anyOf"][0]["uniqueItems"] is True
    assert "default" not in params["sort"]["schema"]


def test_model_filter_multi_level_lookup():
    class UserAgeFilter(ModelFilter):
        user__name__gt: str | None = None

    result = UserAgeFilter(user__name__gt="a").get_filters()
    assert len(result) == 1
    assert result[0].field == "user__name"
    assert result[0].operator == "gt"


def test_model_filter_multi_level_lookup_from_kwargs():
    class EmptyFilter(ModelFilter):
        pass

    filter_ = EmptyFilter()
    filter_.with_kwargs(company__owner__name__ilike="ab")
    result = filter_.get_filters()
    assert len(result) == 1
    assert result[0].field == "company__owner__name"
    assert result[0].operator == "ilike"
