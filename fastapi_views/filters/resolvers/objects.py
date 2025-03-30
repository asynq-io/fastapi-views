from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from fastapi_views.filters.models import OrderingFilter, PaginationFilter
from fastapi_views.filters.operations import (
    LogicalOperation,
    SortOperation,
)

from .abc import FilterResolver

if TYPE_CHECKING:
    from collections.abc import Iterable

    from fastapi_views.filters.models import AnyFilter
    from fastapi_views.filters.operations import (
        Operation,
    )


class ObjectFilterResolver(FilterResolver[list[Any]]):
    operators: ClassVar[dict[str, Callable[[Any, Any], bool]]] = {
        "is_null": lambda a, b: operator.is_(a, None)
        if b
        else operator.is_not(a, None),
        "like": lambda a, b: operator.contains(a, b),
        "ilike": lambda a, b: operator.contains(a.lower(), b.lower()),
    }

    def __init__(self, getter: Callable[[str], Any] = operator.attrgetter) -> None:
        self.getter = getter

    def _apply(self, *fields: Any, op: Callable[[Iterable[object]], bool]) -> Any:
        def wrapped(obj: Any) -> Any:
            return op(f(obj) for f in fields)

        return wrapped

    def resolve(self, operation: Operation, **context: Any) -> Any:
        if isinstance(operation, LogicalOperation):
            fn = all if operation.operator == "and" else any
            return self._apply(
                *[self.resolve(f, **context) for f in operation.values], op=fn
            )

        getter = self.getter(operation.field)
        if isinstance(operation, SortOperation):
            return {"key": getter, "reverse": operation.desc}

        op_name = operation.operator
        if op_name in self.operators:
            op = self.operators[op_name]
        else:
            op = getattr(operator, op_name)

        def resolved(obj: Any) -> Any:
            return op(getter(obj), operation.values)

        return resolved

    def apply_filter(
        self, filter: AnyFilter, queryset: list[Any], **context: Any
    ) -> list[Any]:
        f = self._apply(*[self.resolve(op) for op in filter.filters], op=all)

        queryset = [obj for obj in queryset if f(obj)]
        if isinstance(filter, OrderingFilter):
            for order_by in filter.order_by:
                resolved = self.resolve(order_by)
                queryset.sort(**resolved)
        if isinstance(filter, PaginationFilter):
            queryset = queryset[filter.offset : filter.offset + filter.limit]

        return queryset
