from __future__ import annotations

from operator import and_, or_
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Literal

from fastapi_views.filters.models import OrderingFilter, PaginationFilter
from fastapi_views.filters.operations import (
    FilterOperation,
    LogicalOperation,
    Operation,
    SortOperation,
)

from .abc import FilterResolver

if TYPE_CHECKING:
    from fastapi_views.filters.models import AnyFilter


class SQLAlchemyFilterResolver(FilterResolver):
    _cache: dict[str, Any] = {}
    filter_model: Any
    operators: ClassVar[dict[str, Callable[[Any, Any], Any]]] = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "lt": lambda a, b: a < b,
        "le": lambda a, b: a <= b,
        "gt": lambda a, b: a > b,
        "ge": lambda a, b: a >= b,
        "in": lambda a, b: a.in_(b),
        "not_in": lambda a, b: a.not_in_(b),
        "is_null": lambda a, b: a.is_(None) if b else a.is_not(None),
        "like": lambda a, b: a.like(f"%{b}%"),
        "ilike": lambda a, b: a.ilike(f"%{b}%"),
        "and": and_,
        "or": or_,
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
            msg = f"Could not resolve {operation.field} within context {context}"
            raise ValueError(msg)
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

        if isinstance(filter, PaginationFilter) and "paginate" not in excluded:
            queryset = queryset.offset(filter.offset).limit(filter.limit)

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
