"""
FastAPI-Views integration with sqlargon
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sqlargon import Model, SQLAlchemyRepository
from sqlargon.pagination import (
    TotalLimitOffsetPagination,
    TotalNumberedPage,
    TotalOffsetPage,
    TotalPageNumberPagination,
)

from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver

if TYPE_CHECKING:
    from typing_extensions import Self

    from fastapi_views.filters import BaseFilter, BasePaginationFilter


class FilterableRepository(
    SQLAlchemyRepository[Model],
    SQLAlchemyFilterResolver,
    abstract=True,
):
    """Repository which can apply fastapi-views filters to its query."""

    def __init_subclass__(cls, *, abstract: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(abstract=abstract, **kwargs)

        if hasattr(cls, "model"):
            cls.filter_model = cls.model

    def with_filter(
        self,
        filter: BaseFilter,
        exclude: set[Literal["filter", "fields", "sort", "paginate"]] | None = None,
        **context: Any,
    ) -> Self:
        query = self.apply_filter(filter, self.query, exclude=exclude, **context)
        return self.copy(query)


class PaginatedRepository(FilterableRepository[Model], abstract=True):
    """Filterable repository paginated with page/page_size and totals.

    Pairs with ``PaginationFilter`` and a ``NumberedPage`` response.
    """

    paginate = TotalPageNumberPagination()

    async def get_filtered_page(
        self, filter: BasePaginationFilter, **kwargs: Any
    ) -> TotalNumberedPage[Model]:
        return await self.with_filter(filter, exclude={"paginate"}, **kwargs).paginate(
            **filter.get_pagination()
        )


class OffsetPaginatedRepository(FilterableRepository[Model], abstract=True):
    """Filterable repository paginated with offset/limit and totals.

    Pairs with ``OffsetLimitFilter`` and an ``OffsetPage`` response.
    """

    paginate = TotalLimitOffsetPagination()

    async def get_filtered_page(
        self, filter: BasePaginationFilter, **kwargs: Any
    ) -> TotalOffsetPage[Model]:
        return await self.with_filter(filter, exclude={"paginate"}, **kwargs).paginate(
            **filter.get_pagination()
        )


try:
    from sqlargon.pagination import CursorPage
    from sqlargon.pagination.cursor import CursorPagination
except ImportError:  # pragma: no cover - requires sqlargon[pagination]
    pass
else:

    class CursorPaginatedRepository(FilterableRepository[Model], abstract=True):
        """Filterable repository paginated with opaque keyset cursors.

        Pairs with ``CursorPaginationFilter`` and a ``CursorPage`` response.
        The repository query requires a deterministic order, e.g. via
        ``default_order_by``.
        """

        paginate = CursorPagination()

        async def get_filtered_page(
            self, filter: BasePaginationFilter, **kwargs: Any
        ) -> CursorPage[Model]:
            return await self.with_filter(
                filter, exclude={"paginate"}, **kwargs
            ).paginate(**filter.get_pagination())
