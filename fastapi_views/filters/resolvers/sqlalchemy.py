from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from typing_extensions import Self

from fastapi_views.filters.models import (
    BaseFilter,
    BasePaginationFilter,
    FieldsFilter,
    OrderingFilter,
    PaginationFilter,
    TokenPaginationFilter,
)
from fastapi_views.filters.operations import (
    LogicalOperation,
    Operation,
    SortOperation,
)

from .abc import FilterResolver

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


try:
    from sqlalchemy.orm import load_only
except ImportError:

    def load_only(*_: Any, raiseload: bool = False) -> Any:
        raise NotImplementedError


class _Queryset(Protocol):
    """Sqlalchemy Queryset protocol"""

    def filter(self, *args: Any) -> Self: ...

    def options(self, *args: Any) -> Self: ...

    def order_by(self, *args: Any) -> Self: ...

    def offset(self, offset: int) -> Self: ...

    def limit(self, limit: int) -> Self: ...


class Column(Protocol):
    """This is sqlalchemy.Column protocol, the real Column instance is injected as `self` parameter"""

    def in_(self, values: Sequence[Any]) -> Any:
        return self.in_(values)

    def not_in_(self, values: Sequence[Any]) -> Any:
        return self.not_in_(values)

    def is_(self, value: Any) -> Any:
        return self.is_(value)  # pragma: no cover

    def is_not(self, value: Any) -> Any:
        return self.is_not(value)  # pragma: no cover

    def like(self, value: str) -> Any:
        return self.like(f"%{value}%")

    def ilike(self, value: str) -> Any:
        return self.ilike(f"%{value}%")

    def is_null(self, value: bool) -> Any:  # noqa: FBT001
        return self.is_(None) if value else self.is_not(None)


class SQLAlchemyFilterResolver(FilterResolver[_Queryset]):
    _cache: ClassVar[dict[str, Any]] = {}
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
        self,
        field: str,
        **context: Any,
    ) -> Any:
        name = field
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

        column = self.resolve_model_field(operation.field, **context)

        if isinstance(operation, SortOperation):
            return column.desc() if operation.desc else column

        fn = self.operators[operation.operator]
        return fn(column, operation.values)

    def apply_base_filter(
        self, queryset: _Queryset, filter: BaseFilter, **context: Any
    ) -> _Queryset:
        filters = self.get_filters(filter, **context)
        return queryset.filter(*filters)

    def apply_fields_filter(
        self, queryset: _Queryset, filter: FieldsFilter, **context: Any
    ) -> _Queryset:
        fields = filter.get_fields()
        if fields:
            columns = [self.resolve_model_field(f, **context) for f in fields]
            queryset = queryset.options(load_only(*columns))
        return queryset

    def apply_ordering_filter(
        self, queryset: _Queryset, filter: OrderingFilter, **context: Any
    ) -> _Queryset:
        order_by = self.get_order_by(filter, **context)
        return queryset.order_by(*order_by)

    def apply_pagination_filter(
        self, queryset: _Queryset, filter: BasePaginationFilter, **context: Any
    ) -> _Queryset:
        if isinstance(filter, PaginationFilter):
            return queryset.offset(filter.offset).limit(filter.limit)
        if isinstance(filter, TokenPaginationFilter):
            return self.apply_token_pagination(
                queryset, filter.page_token, filter.page_size, **context
            )
        raise NotImplementedError

    def get_filters(self, filter: BaseFilter, **context: Any) -> list[Any]:
        return [self.resolve(f, **context) for f in filter.filters]

    def get_order_by(
        self,
        filter: OrderingFilter,
        extra: list[Any] | None = None,
        **context: Any,
    ) -> list[Any]:
        order_by = [self.resolve(f, **context) for f in filter.order_by]
        if extra:
            order_by.extend(extra)
        return order_by

    def apply_token_pagination(
        self,
        queryset: _Queryset,
        page: str | None,
        page_size: int,
    ) -> Any:
        # warning: sqlalchemy itself does not implement token based pagination,
        # it is up to user to implement it using something like sqlakeyset: https://github.com/djrobstep/sqlakeyset
        raise NotImplementedError
