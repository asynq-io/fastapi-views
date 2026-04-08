from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, Literal, TypeVar

from fastapi_views.filters.models import (
    BaseFilter,
    BasePaginationFilter,
    FieldsFilter,
    OrderingFilter,
)

Queryset = TypeVar("Queryset")


class FilterResolver(ABC, Generic[Queryset]):
    @abstractmethod
    def apply_base_filter(
        self, queryset: Queryset, filter: BaseFilter, **context: Any
    ) -> Queryset:
        raise NotImplementedError

    @abstractmethod
    def apply_fields_filter(
        self, queryset: Queryset, filter: FieldsFilter, **context: Any
    ) -> Queryset:
        raise NotImplementedError

    @abstractmethod
    def apply_ordering_filter(
        self, queryset: Queryset, filter: OrderingFilter, **context: Any
    ) -> Queryset:
        raise NotImplementedError

    @abstractmethod
    def apply_pagination_filter(
        self, queryset: Queryset, filter: BasePaginationFilter, **context: Any
    ) -> Queryset:
        raise NotImplementedError

    def apply_filter(
        self,
        filter: BaseFilter,
        queryset: Queryset,
        exclude: set[Literal["filter", "fields", "sort", "paginate"]] | None = None,
        **context: Any,
    ) -> Queryset:
        excluded = exclude or set()
        if "filter" not in excluded:
            queryset = self.apply_base_filter(queryset, filter, **context)
        if "fields" not in excluded and isinstance(filter, FieldsFilter):
            queryset = self.apply_fields_filter(queryset, filter, **context)
        if "sort" not in excluded and isinstance(filter, OrderingFilter):
            queryset = self.apply_ordering_filter(queryset, filter, **context)
        if "paginate" not in excluded and isinstance(filter, BasePaginationFilter):
            queryset = self.apply_pagination_filter(queryset, filter, **context)

        return queryset
