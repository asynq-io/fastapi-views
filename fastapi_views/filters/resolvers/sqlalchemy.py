from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Literal, Protocol

from fastapi_views.filters.models import (
    OrderingFilter,
    PaginationFilter,
    TokenPaginationFilter,
)
from fastapi_views.filters.operations import (
    FilterOperation,
    LogicalOperation,
    Operation,
    SortOperation,
)

from .abc import FilterResolver

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_views.filters.models import AnyFilter


class Column(Protocol):
    """
    This is sqlalchemy.Column protocol, the real Column instance is injected as `self` parameter
    """

    def in_(self, values: Sequence[Any]) -> Any:
        return self.in_(values)

    def not_in_(self, values: Sequence[Any]) -> Any:
        return self.not_in_(values)

    def is_(self, value: Any) -> Any:
        return self.is_(value)

    def is_not(self, value: Any) -> Any:
        return self.is_not(value)

    def like(self, value: str) -> Any:
        return self.like(f"%{value}%")

    def ilike(self, value: str) -> Any:
        return self.ilike(f"%{value}%")

    def is_null(self, value: bool) -> Any:
        return self.is_(None) if value else self.is_not(None)


class SQLAlchemyFilterResolver(FilterResolver):
    _cache: dict[str, Any] = {}
    filter_model: Any
    operators: ClassVar[dict[str, Callable[[Any, Any], Any]]] = {
        "eq": operator.eq,
        "ne": operator.ne,
        "lt": operator.lt,
        "le": operator.le,
        "gt": operator.gt,
        "ge": operator.ge,
        "in": Column.in_,
        "not_in": Column.not_in_,
        "is_null": Column.is_null,
        "like": Column.like,
        "ilike": Column.ilike,
        "and": operator.and_,
        "or": operator.or_,
    }

    def _get_model_cls(self, name: str) -> Any:
        if name in self._cache:
            return self._cache[name]
        for mapper in self.filter_model.registry.mappers:
            model_class = mapper.class_
            if model_class.__tablename__ == name:
                self._cache[name] = model_class
                return model_class
        return None

    def resolve_model_field(
        self, operation: SortOperation | FilterOperation, **context: Any
    ) -> Any:
        name = operation.field
        if "__" in name:
            prefix, _, name = name.partition("__")
            model_class = context.get(prefix, {}).get("table")
            if model_class:
                return getattr(model_class, name)
            model_class = self._get_model_cls(prefix)
            return getattr(model_class, name)
        model = context.get("table", self.filter_model)
        return getattr(model, name)

    def resolve(self, operation: Operation, **context: Any) -> Any:
        if isinstance(operation, LogicalOperation):
            fn = self.operators[operation.operator]
            return fn(*(self.resolve(f, **context) for f in operation.values))

        column = self.resolve_model_field(operation, **context)

        if isinstance(operation, SortOperation):
            return column.desc() if operation.desc else column

        fn = self.operators[operation.operator]
        return fn(column, operation.values)

    def apply_filter(
        self,
        filter: AnyFilter,
        queryset: Any,
        exclude: set[Literal["filter", "sort", "paginate"]] | None = None,
        **context: Any,
    ) -> Any:
        excluded = exclude or set()

        if "filter" not in excluded:
            filters = self.get_filters(filter, **context)
            queryset = queryset.filter(*filters)

        if isinstance(filter, OrderingFilter) and "sort" not in excluded:
            order_by = self.get_order_by(filter, **context)

            queryset = queryset.order_by(*order_by)

        if "paginate" not in excluded:
            if isinstance(filter, PaginationFilter):
                queryset = queryset.offset(filter.offset).limit(filter.limit)
            elif isinstance(filter, TokenPaginationFilter):
                queryset = self.apply_token_pagination(
                    queryset, filter.page_token, filter.page_size
                )

        return queryset

    def get_filters(self, filter: AnyFilter, **context: Any) -> list[Any]:
        return [self.resolve(f, **context) for f in filter.filters]

    def get_order_by(
        self, filter: OrderingFilter, extra: list[Any] | None = None, **context: Any
    ) -> list[Any]:
        order_by = [self.resolve(f, **context) for f in filter.order_by]
        if extra:
            order_by.extend(extra)
        return order_by

    def apply_token_pagination(
        self, queryset: Any, page: str | None, page_size: int
    ) -> Any:
        # warning: sqlalchemy itself does not implement token based pagination,
        # it is up to user to implement it using something like sqlakeyset: https://github.com/djrobstep/sqlakeyset
        raise NotImplementedError
