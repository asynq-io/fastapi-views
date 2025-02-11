from typing import Annotated, TypeVar

from fastapi import Query
from pydantic import Field

T = TypeVar("T")

QueryField = Annotated[T | None, Field(Query(None))]

SearchQuery = Annotated[
    str | None, Field(Query(None, alias="q", description="Search query"))
]
Sort = Annotated[
    list[str] | None,
    Field(
        Query(
            None,
            description="List of fields to sort by. Prefix with '-' to sort in descending order",
        ),
    ),
]
