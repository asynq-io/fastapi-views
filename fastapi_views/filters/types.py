from typing import Annotated, Optional, TypeVar

from fastapi import Query
from pydantic import Field

T = TypeVar("T")

QueryField = Annotated[Optional[T], Field(Query(None))]

SearchQuery = Annotated[
    Optional[str], Field(Query(None, alias="q", description="Search query"))
]
Sort = Annotated[
    Optional[list[str]],
    Field(
        Query(
            None,
            description="List of fields to sort by. Prefix with '-' to sort in descending order",
        ),
    ),
]

Fields = Annotated[
    Optional[set[T]],
    Field(Query(None, description="List of fields to include in response")),
]
AnyFields = Fields[str]
