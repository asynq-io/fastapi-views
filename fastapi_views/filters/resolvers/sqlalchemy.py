from __future__ import annotations

import operator
from contextlib import suppress
from functools import reduce
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
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.orm import defaultload, load_only
except ImportError:

    def load_only(*_: Any, raiseload: bool = False) -> Any:
        raise NotImplementedError

    def defaultload(*_: Any) -> Any:
        raise NotImplementedError

    def sa_inspect(subject: Any, *, raiseerr: bool = True) -> Any:  # type: ignore[no-redef]
        raise NotImplementedError


def _escape_like_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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

    def is_null(self, value: bool) -> Any:  # noqa: FBT001
        return self.is_(None) if value else self.is_not(None)

    def like(self, value: str, escape: str = "\\") -> Any:
        return self.like(f"%{_escape_like_value(value)}%", escape=escape)

    def ilike(self, value: str, escape: str = "\\") -> Any:
        return self.ilike(f"%{_escape_like_value(value)}%", escape=escape)


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
            resolved = [self.resolve(f, **context) for f in operation.values]
            return reduce(fn, resolved)

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

    def _get_related_model_cls(self, model: Any, rel_name: str) -> Any:
        with suppress(Exception):
            mapper = sa_inspect(model)
            rel = mapper.relationships.get(rel_name)
            if rel is not None:
                return rel.mapper.class_
        return None

    def apply_fields_filter(
        self, queryset: _Queryset, filter: FieldsFilter, **context: Any
    ) -> _Queryset:
        fields = filter.get_fields()
        if not fields:
            return queryset

        model = context.get("table", self.filter_model)
        top_level: list[str] = []
        nested: dict[tuple[str, ...], list[str]] = {}

        for field in fields:
            if "__" in field:
                parts = field.split("__")
                path = tuple(parts[:-1])
                nested.setdefault(path, []).append(parts[-1])
            else:
                top_level.append(field)

        options_list = []

        if top_level:
            options_list.append(load_only(*[getattr(model, f) for f in top_level]))

        for path, rel_fields in nested.items():
            current_model = model
            loader = None
            for rel_name in path:
                rel_attr = getattr(current_model, rel_name)
                loader = (
                    defaultload(rel_attr)
                    if loader is None
                    else loader.defaultload(rel_attr)
                )
                current_model = self._get_related_model_cls(current_model, rel_name)
                if current_model is None:
                    loader = None
                    break
            if loader is not None:
                rel_columns = [getattr(current_model, f) for f in rel_fields]
                options_list.append(loader.load_only(*rel_columns))

        return queryset.options(*options_list)

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
