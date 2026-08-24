from collections.abc import MutableSequence
from typing import Any, ClassVar, Literal

from fastapi import Query
from pydantic import (
    BaseModel,
    NonNegativeInt,
    PositiveInt,
    PrivateAttr,
    field_validator,
)

from fastapi_views.pagination import Cursor, PageNumber, PageSize

from .operations import FilterOperation, LogicalOperation, SortOperation
from .types import (
    AnyFields,
    Includes,
    SearchQuery,
    Sort,
    set_query_param,
    unwrap_query_params,
)


class BaseFilter(BaseModel):
    special_fields: ClassVar[set[str]] = set()
    _kwargs: dict[str, Any] = PrivateAttr({})

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        parent_special_fields: set[str] = set()

        for base in cls.__mro__[1:]:
            special_fields: set[str] = getattr(base, "special_fields", set())
            parent_special_fields |= special_fields

        # rebind instead of |= to avoid mutating the set inherited from a parent
        cls.special_fields = cls.special_fields | parent_special_fields

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        for field in cls.model_fields.values():
            unwrap_query_params(field)

    @property
    def filters(self) -> MutableSequence[FilterOperation | LogicalOperation]:
        return self.get_filters()

    def get_filters(self) -> MutableSequence[FilterOperation | LogicalOperation]:
        return []

    def as_kwargs(self) -> dict[str, Any]:
        return (
            self.model_dump(exclude=self.special_fields, exclude_none=True)
            | self._kwargs
        )

    def with_kwargs(self, **kwargs: Any) -> None:
        self._kwargs.update(kwargs)


class ModelFilter(BaseFilter):
    def _get_operations(
        self, field_name: str, value: Any
    ) -> MutableSequence[FilterOperation | LogicalOperation]:
        if value is None:
            return []

        if isinstance(value, BaseFilter):
            model_filters = value.get_filters()
            for operation in model_filters:
                operation.set_prefix(field_name)
            return model_filters
        if "__" in field_name:
            field_name, _, op = field_name.rpartition("__")
        else:
            op = "eq"
        return [FilterOperation(field=field_name, operator=op, values=value)]

    @property
    def field_names(self) -> set[str]:
        return set(type(self).model_fields) - self.special_fields

    def get_filters(self) -> MutableSequence[FilterOperation | LogicalOperation]:
        filters = super().get_filters()

        for field_name in self.field_names:
            value = getattr(self, field_name)
            filters.extend(self._get_operations(field_name, value))

        for field_name, value in self._kwargs.items():
            filters.extend(self._get_operations(field_name, value))
        return filters


class BasePaginationFilter(BaseFilter):
    pagination_fields: ClassVar[set[str]] = set()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.special_fields |= cls.pagination_fields

    def get_pagination(self, **kwargs: Any) -> dict[str, Any]:
        return self.model_dump(include=self.pagination_fields, **kwargs)


class OffsetLimitFilter(BasePaginationFilter):
    pagination_fields = {"offset", "limit"}

    offset: NonNegativeInt = 0
    limit: PositiveInt = 100


class PaginationFilter(BasePaginationFilter):
    pagination_fields = {"page", "page_size"}

    page: PageNumber = 1
    page_size: PageSize = 100


class CursorPaginationFilter(BasePaginationFilter):
    pagination_fields = {"cursor", "page_size"}

    cursor: Cursor | None = None
    page_size: PageSize = 100


class OrderingFilter(BaseFilter):
    special_fields = {"sort"}

    ordering_fields: ClassVar[set[str]] = set()

    sort: Sort

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        field = cls.model_fields.get("sort")
        if field is not None and cls.ordering_fields:
            set_query_param(
                field,
                Query(
                    description=f"List of fields to sort by. \
                Prefix with '-' to sort in descending order. \
                Available values: {', '.join(cls.ordering_fields)}",
                ),
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

    def get_filters(self) -> MutableSequence[FilterOperation | LogicalOperation]:
        filters = super().get_filters()

        if self.query:
            search_fields = []

            for field_name in self.search_fields:
                operation = FilterOperation(
                    field=field_name,
                    operator="ilike",
                    values=self.query,
                )

                search_fields.append(operation)

            filters.append(LogicalOperation(operator="or", values=search_fields))
        return filters


class FieldsFilter(BaseFilter):
    special_fields = {"fields"}
    fields_from: ClassVar[type[BaseModel] | None] = None

    fields: AnyFields

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        if cls.fields_from:
            fields = tuple(cls.fields_from.model_fields)
            cls.model_fields["fields"].annotation = set[Literal[fields]]  # type: ignore[valid-type]
            cls.model_rebuild(force=True, _parent_namespace_depth=0)

    def get_fields(self) -> set[str] | None:
        return self.fields


class IncludeFilter(BaseFilter):
    """Filter allowing clients to opt into loading related resources."""

    special_fields = {"include"}
    related_fields: ClassVar[set[str]] = set()

    include: Includes

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        field = cls.model_fields.get("include")
        if field is not None and cls.related_fields:
            set_query_param(
                field,
                Query(
                    description=f"List of related resources to include in response. \
                Available values: {', '.join(cls.related_fields)}",
                ),
            )

    @field_validator("include", mode="after")
    @classmethod
    def validate_include(cls, value: set[str] | None) -> set[str] | None:
        if value is None:
            return None
        for field in value:
            if field not in cls.related_fields:
                msg = f"Unknown include value '{field}'. Allowed values: {', '.join(cls.related_fields)}"
                raise ValueError(msg)
        return value

    def get_related(self) -> set[str] | None:
        return self.include


class Filter(
    PaginationFilter,
    OrderingFilter,
    SearchFilter,
    ModelFilter,
    FieldsFilter,
    IncludeFilter,
):
    """Main filter class that implements all the functionalities:
    pagination, ordering, search, fields and custom attributes filter
    """
