from collections.abc import MutableSequence
from typing import Any, ClassVar, Literal, Optional, Union

from fastapi import Query
from pydantic import BaseModel, field_validator

from fastapi_views.pagination import PageNumber, PageSize, PageToken

from .operations import FilterOperation, LogicalOperation, SortOperation
from .types import AnyFields, SearchQuery, Sort


class BaseFilter(BaseModel):
    special_fields: ClassVar[set[str]] = set()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        parent_special_fields: set[str] = set()

        for base in cls.__mro__[1:]:
            special_fields: set[str] = getattr(base, "special_fields", set())
            parent_special_fields |= special_fields

        cls.special_fields |= parent_special_fields

    @property
    def filters(self) -> MutableSequence[Union[FilterOperation, LogicalOperation]]:
        return self.get_filters()

    def get_filters(self) -> MutableSequence[Union[FilterOperation, LogicalOperation]]:
        return []


class ModelFilter(BaseFilter):
    def get_filters(self) -> MutableSequence[Union[FilterOperation, LogicalOperation]]:
        filters = super().get_filters()

        for field_name in type(self).model_fields:
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


class BasePaginationFilter(BaseFilter):
    special_fields = {"page_size"}

    page_size: PageSize = 100


class PaginationFilter(BasePaginationFilter):
    special_fields = {"page"}

    page: PageNumber = 1

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class TokenPaginationFilter(BasePaginationFilter):
    special_fields = {"page_token"}

    page_token: Optional[PageToken] = None


class OrderingFilter(BaseFilter):
    special_fields = {"sort"}

    ordering_fields: ClassVar[set[str]] = set()

    sort: Sort

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "sort" in cls.model_fields and cls.ordering_fields:
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
    special_fields = {"query"}
    search_fields: ClassVar[set[str]] = set()
    query: SearchQuery

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


# consider implementing projection at queryset level using new OperationType
# but this will require importing sqlalchemy load_only or leaving abstractmethod
class FieldsFilter(BaseFilter):
    special_fields = {"fields"}
    fields_from: ClassVar[Optional[type[BaseModel]]] = None

    fields: AnyFields

    def __init_subclass__(cls, **kwargs: Any) -> None:
        if cls.fields_from:
            fields = tuple(cls.fields_from.model_fields)
            cls.model_fields["fields"].annotation = set[Literal[fields]]  # type: ignore[valid-type]
        super().__init_subclass__(**kwargs)

    def get_fields(self) -> Optional[set[str]]:
        # consider implementing advanced include/exclude (subfields)
        # using '__ ' syntax later on, for now only top-level fields are supported
        return self.fields


class Filter(
    PaginationFilter,
    OrderingFilter,
    SearchFilter,
    FieldsFilter,
    ModelFilter,
):
    """
    Main filter class that implements all the functionalities:
    pagination, ordering, search, fields and custom attributes filter
    """


AnyFilter = Union[
    BaseFilter, SearchFilter, OrderingFilter, PaginationFilter, FieldsFilter
]
