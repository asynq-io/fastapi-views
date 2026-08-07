from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, TypeVar

from fastapi import Query, params
from pydantic import Field

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

T = TypeVar("T")


@dataclass(frozen=True, eq=False)
class QueryParam:
    """Carries a `fastapi.Query` inside the annotation metadata.

    Pydantic absorbs any `FieldInfo` found in `Annotated[...]` metadata, which
    would leave nothing for FastAPI to detect. Wrapping it keeps the parameter
    definition opaque to pydantic until `unwrap_query_params` puts it back into
    the metadata of the already built field.
    """

    param: params.Query


def unwrap_query_params(field: FieldInfo) -> None:
    if any(isinstance(meta, QueryParam) for meta in field.metadata):
        field.metadata = [
            meta.param if isinstance(meta, QueryParam) else meta
            for meta in field.metadata
        ]


def set_query_param(field: FieldInfo, param: params.Query) -> None:
    field.metadata = [
        param if isinstance(meta, (QueryParam, params.Query)) else meta
        for meta in field.metadata
    ]


QueryField = Annotated[T | None, Field(None), QueryParam(Query())]

SearchQuery = Annotated[
    str | None,
    Field(None),
    QueryParam(Query(alias="q", description="Search query")),
]
Sort = Annotated[
    list[str] | None,
    Field(None),
    QueryParam(
        Query(
            description="List of fields to sort by. Prefix with '-' to sort in descending order",
        ),
    ),
]

Fields = Annotated[
    set[T] | None,
    Field(None),
    QueryParam(Query(description="List of fields to include in response")),
]
AnyFields = Fields[str]
