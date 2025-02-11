from collections.abc import MutableSequence
from typing import Any, ClassVar, Union

from fastapi import Query
from pydantic import BaseModel, field_validator

from fastapi_views.pagination import PageNumber, PageSize

from .operations import FilterOperation, LogicalOperation, SortOperation
from .types import SearchQuery, Sort


class BaseFilter(BaseModel):
    special_fields: ClassVar[set[str]] = set()

    @property
    def filters(self) -> MutableSequence[Union[FilterOperation, LogicalOperation]]:
        return self.get_filters()

    def get_filters(self) -> MutableSequence[Union[FilterOperation, LogicalOperation]]:
        return []


class ModelFilter(BaseFilter):
    def get_filters(self) -> MutableSequence[Union[FilterOperation, LogicalOperation]]:
        filters = super().get_filters()

        for field_name in self.model_fields:
            if field_name in self.special_fields:
                continue

            value = getattr(self, field_name)
            if value is None:
                continue

            if isinstance(value, BaseFilter):
                model_filters = value.get_filters()
                for operation in model_filters:
                    operation.set_prefix(field_name)

                filters.extend(model_filters)

            else:
                if "__" in field_name:
                    field_name, _, op = field_name.partition("__")
                else:
                    op = "eq"
                operation = FilterOperation(field=field_name, operator=op, values=value)
                filters.append(operation)

        return filters


class PaginationFilter(BaseFilter):
    page: PageNumber = 1
    page_size: PageSize = 100

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.special_fields = cls.special_fields | {"page", "page_size"}

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class OrderingFilter(BaseFilter):
    ordering_fields: ClassVar[set[str]] = set()

    sort: Sort

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.special_fields = cls.special_fields | {"sort"}
        if "sort" in cls.model_fields:
            cls.model_fields["sort"].default = Query(
                None,
                description=f"List of fields to sort by. \
                Prefix with '-' to sort in descending order. \
                Available values: {', '.join(cls.ordering_fields)}",
            )

    @field_validator("sort", mode="after")
    @classmethod
    def validate_sort(cls, value: Sort) -> Sort:
        if value is None:
            return None
        for field in value:
            if field.lstrip("+-") not in cls.ordering_fields:
                msg = f"Unknown sort value '{field}'. Allowed values: {', '.join(cls.ordering_fields)}"
                raise ValueError(msg)
        return value

    @property
    def order_by(self) -> MutableSequence[SortOperation]:
        return self.get_order_by()

    def get_order_by(self) -> MutableSequence[SortOperation]:
        if self.sort is None:
            return []
        order_by = []
        for field_name in self.sort:
            desc = False
            if field_name.startswith("-"):
                desc = True

            operation = SortOperation(field=field_name.lstrip("+-"), desc=desc)
            order_by.append(operation)
        return order_by


class SearchFilter(BaseFilter):
    search_fields: ClassVar[set[str]] = set()
    query: SearchQuery

    def __init_subclass__(cls, **kwargs: Any) -> None:
        cls.special_fields = cls.special_fields | {"query"}
        super().__init_subclass__(**kwargs)

    def get_filters(self) -> MutableSequence[Union[FilterOperation, LogicalOperation]]:
        filters = super().get_filters()

        if self.query:
            search_fields = []

            for field_name in self.search_fields:
                operation = FilterOperation(
                    field=field_name, operator="ilike", values=self.query
                )

                search_fields.append(operation)

            filters.append(LogicalOperation(operator="or", values=search_fields))
        return filters


class Filter(
    PaginationFilter,
    OrderingFilter,
    SearchFilter,
    ModelFilter,
):
    pass


AnyFilter = Union[BaseFilter, SearchFilter, OrderingFilter, PaginationFilter]
