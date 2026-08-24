"""
FastAPI-Views integration with sqlargon
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from sqlargon import Model, SQLAlchemyRepository
from sqlargon.pagination import (
    TotalLimitOffsetPagination,
    TotalNumberedPage,
    TotalOffsetPage,
    TotalPageNumberPagination,
)

from fastapi_views.filters.resolvers.sqlalchemy import SQLAlchemyFilterResolver

if TYPE_CHECKING:
    from collections.abc import Sequence

    from typing_extensions import Self

    from fastapi_views.filters import BaseFilter, BasePaginationFilter


class FilterableRepository(
    SQLAlchemyRepository[Model],
    SQLAlchemyFilterResolver,
    abstract=True,
):
    """Repository which can apply fastapi-views filters to its query."""

    select_related: ClassVar[Sequence[str] | Mapping[str, Sequence[str]]] = ()
    """Relationship paths to eager load by default.

    Either a sequence applied to every query, or a mapping keyed by
    operation (``"get"``, ``"list"``) when e.g. retrieve should load
    more than list. Paths use ``__`` for nesting, e.g. ``author__publisher``.
    """

    def __init_subclass__(cls, *, abstract: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(abstract=abstract, **kwargs)

        if hasattr(cls, "model"):
            cls.filter_model = cls.model

    def with_filter(
        self,
        filter: BaseFilter,
        exclude: set[Literal["filter", "fields", "sort", "paginate", "related"]]
        | None = None,
        **context: Any,
    ) -> Self:
        query = self.apply_filter(filter, self.query, exclude=exclude, **context)
        return self.copy(query)

    def with_related(self, *paths: str) -> Self:
        """Return a repository copy eager loading the given relationship paths."""
        options = []
        for path in paths:
            loader, _ = self._relationship_loader(self.model, path.split("__"))
            if loader is not None:
                options.append(loader)
        if not options:
            return self
        return self.copy(self.query.options(*options))

    def _default_related(self, operation: str) -> tuple[str, ...]:
        related = self.select_related
        if isinstance(related, Mapping):
            return tuple(related.get(operation, ()))
        return tuple(related)

    async def get(self, *args: Any, **kwargs: Any) -> Model | None:
        repo = self.with_related(*self._default_related("get"))
        return await repo.filter(*args, **kwargs).one_or_none()

    async def list(self, *args: Any, **kwargs: Any) -> Sequence[Model]:
        repo = self.with_related(*self._default_related("list"))
        return await repo.filter(*args, **kwargs).all()


class PaginatedRepository(FilterableRepository[Model], abstract=True):
    """Filterable repository paginated with page/page_size and totals.

    Pairs with ``PaginationFilter`` and a ``NumberedPage`` response.
    """

    paginate = TotalPageNumberPagination()

    async def get_filtered_page(
        self, filter: BasePaginationFilter, **kwargs: Any
    ) -> TotalNumberedPage[Model]:
        repo = self.with_related(*self._default_related("list"))
        return await repo.with_filter(filter, exclude={"paginate"}, **kwargs).paginate(
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
        repo = self.with_related(*self._default_related("list"))
        return await repo.with_filter(filter, exclude={"paginate"}, **kwargs).paginate(
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
            repo = self.with_related(*self._default_related("list"))
            return await repo.with_filter(
                filter, exclude={"paginate"}, **kwargs
            ).paginate(**filter.get_pagination())
