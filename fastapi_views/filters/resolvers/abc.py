from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from fastapi_views.filters.models import AnyFilter
    from fastapi_views.filters.operations import Operation

Queryset = TypeVar("Queryset")


class FilterResolver(ABC, Generic[Queryset]):
    @abstractmethod
    def resolve(self, operation: Operation, **context: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def apply_filter(
        self, filter: AnyFilter, queryset: Queryset, **context: Any
    ) -> Queryset:
        raise NotImplementedError
