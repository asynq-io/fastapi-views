"""
FastAPI-Views integration with sqlargon
"""

from typing import Any, Literal

from sqlargon import SQLAlchemyRepository
from sqlargon.orm import Model
from typing_extensions import Self

from fastapi_views.filters import BaseFilter
from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver


class FilterableRepository(
    SQLAlchemyRepository[Model], SQLAlchemyFilterResolver, abstract=True
):
    def __init_subclass__(cls, *, abstract: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(abstract, **kwargs)

        if hasattr(cls, "model"):
            cls.filter_model = cls.model

    def use_filter(
        self,
        filter: BaseFilter,
        exclude: set[Literal["filter", "fields", "sort", "paginate"]] | None = None,
        **context: Any,
    ) -> Self:
        query = self.apply_filter(filter, self.query, exclude=exclude, **context)  # type: ignore[arg-type]
        return self.copy(query)  # type: ignore[arg-type]


class PaginatedRepository(FilterableRepository[Model], abstract=True):
    pass
    # tbd: allow any type of pagination, cursor, page, offset limit etc
