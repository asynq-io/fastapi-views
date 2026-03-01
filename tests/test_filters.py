from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest

from fastapi_views.filters.models import Filter
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
