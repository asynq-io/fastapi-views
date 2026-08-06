from __future__ import annotations

import copy
import operator
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from fastapi_views.filters.models import (
    BaseFilter,
    BasePaginationFilter,
    FieldsFilter,
    OffsetLimitFilter,
    OrderingFilter,
    PaginationFilter,
)
from fastapi_views.filters.operations import (
    LogicalOperation,
    SortOperation,
)

from .abc import FilterResolver

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from fastapi_views.filters.operations import (
        Operation,
    )


Objects = list[Any]


class ObjectFilterResolver(FilterResolver[Objects]):
    operators: ClassVar[dict[str, Callable[[Any, Any], bool]]] = {
        "is_null": lambda a, b: (
            operator.is_(a, None) if b else operator.is_not(a, None)
        ),
        "like": operator.contains,
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
                *[self.resolve(f, **context) for f in operation.values],
                op=fn,
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

    def _project(self, obj: Any, fields: set[str]) -> Any:
        if isinstance(obj, Mapping):
            return {key: value for key, value in obj.items() if key in fields}
        if getattr(obj, "__dict__", None) is None:
            return obj
        projected = copy.copy(obj)
        for key in [key for key in projected.__dict__ if key not in fields]:
            del projected.__dict__[key]
        return projected

    def apply_fields_filter(
        self, queryset: Objects, filter: FieldsFilter, **_: Any
    ) -> Objects:
        fields = filter.get_fields()
        if not fields:
            return queryset
        return [self._project(obj, fields) for obj in queryset]

    def apply_base_filter(
        self, queryset: Objects, filter: BaseFilter, **context: Any
    ) -> Objects:
        f = self._apply(*[self.resolve(op, **context) for op in filter.filters], op=all)
        return [obj for obj in queryset if f(obj)]

    def apply_ordering_filter(
        self, queryset: Objects, filter: OrderingFilter, **context: Any
    ) -> Objects:
        for order_by in filter.order_by:
            resolved = self.resolve(order_by, **context)
            queryset = sorted(queryset, **resolved)
        return queryset

    def apply_pagination_filter(
        self, queryset: Objects, filter: BasePaginationFilter, **_: Any
    ) -> Objects:
        if isinstance(filter, OffsetLimitFilter):
            return queryset[filter.offset : filter.offset + filter.limit]
        if isinstance(filter, PaginationFilter):
            offset = (filter.page - 1) * filter.page_size
            return queryset[offset : offset + filter.page_size]
        raise NotImplementedError
