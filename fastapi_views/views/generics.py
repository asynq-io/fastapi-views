from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Callable, Generic, Protocol, TypeVar

from fastapi import Depends
from pydantic import BaseModel

from fastapi_views.exceptions import Conflict
from fastapi_views.filters.dependencies import FilterDepends
from fastapi_views.filters.models import (
    BaseFilter,
    BasePaginationFilter,
    FieldsFilter,
    PaginationFilter,
    TokenPaginationFilter,
)
from fastapi_views.pagination import NumberedPage, TokenPage
from fastapi_views.views.api import APIView

from .api import (
    AsyncCreateAPIView,
    AsyncDestroyAPIView,
    AsyncListAPIView,
    AsyncPartialUpdateAPIView,
    AsyncRetrieveAPIView,
    AsyncUpdateAPIView,
    CreateAPIView,
    DestroyAPIView,
    ListAPIView,
    PartialUpdateAPIView,
    RetrieveAPIView,
    UpdateAPIView,
)

M_co = TypeVar("M_co", covariant=True)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_views.types import Action


M = TypeVar("M")
PK = TypeVar("PK", bound=BaseModel)


class Id(BaseModel):
    id: int


class Page(Generic[M_co]):
    items: Sequence[M_co]


class Repository(Protocol[M_co]):
    def create(self, **kwargs: Any) -> M_co | None: ...

    def get(self, *args: Any, **kwargs: Any) -> M_co | None: ...

    def get_filtered_page(self, filter: BasePaginationFilter) -> Page[M_co]: ...

    def list(self, *args: Any, **kwargs: Any) -> Sequence[M_co]: ...

    def delete(self, *args: Any, **kwargs: Any) -> None: ...

    def update_one(
        self, values: dict[str, Any], *args: Any, **kwargs: Any
    ) -> M_co | None: ...


class AsyncRepository(Protocol[M_co]):
    async def create(self, **kwargs: Any) -> M_co | None: ...

    async def get(self, *args: Any, **kwargs: Any) -> M_co | None: ...

    async def get_filtered_page(self, filter: BasePaginationFilter) -> Page[M_co]: ...

    async def list(self, *args: Any, **kwargs: Any) -> Sequence[M_co]: ...

    async def delete(self, *args: Any, **kwargs: Any) -> None: ...

    async def update_one(
        self, values: dict[str, Any], *args: Any, **kwargs: Any
    ) -> M_co | None: ...


class WithRepositoryMixin(Generic[M]):
    repository: Repository[M]


class WithAsyncRepositoryMixin(Generic[M]):
    repository: AsyncRepository[M]


class GenericView(APIView):
    @classmethod
    def _patch_schema(cls, func: Callable, action: Action | None = None) -> None:
        name = action or func.__name__
        param = f"{name}_schema"
        schema = getattr(cls, param)
        func.__annotations__[param] = schema


class DetailGenericView(GenericView, Generic[PK]):
    primary_key: type[PK]

    @classmethod
    def _patch_pk_param(cls, func: Callable) -> None:
        func.__annotations__["pk"] = Annotated[BaseModel, Depends(cls.primary_key)]

    def get_kwargs(self, action: Action | None = None) -> dict[str, Any]:
        return {}

    def get_primary_key(
        self, primary_key: PK, action: Action | None = None
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (), primary_key.model_dump() | self.get_kwargs(action)


class BaseGenericListAPIView(GenericView):
    if TYPE_CHECKING:
        list: Callable

    response_schema_as_list: bool = False
    filter: type[BaseModel] | None

    @classmethod
    def get_response_schema(cls, action: Action | None = None) -> Any:
        if action == "list":
            container_cls: Any = list
            if cls.filter is not None:
                if issubclass(cls.filter, PaginationFilter):
                    container_cls = NumberedPage
                elif issubclass(cls.filter, TokenPaginationFilter):
                    container_cls = TokenPage
            return container_cls[cls.response_schema]
        return cls.response_schema

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        if not hasattr(cls, "filter"):
            return
        filter_ = cls.filter or BaseFilter

        cls.list.__annotations__["filter"] = Annotated[
            BaseFilter, FilterDepends(filter_)  # type: ignore[type-var, unused-ignore]
        ]

    def _apply_fields_filter(self, filter: BaseFilter) -> None:
        if isinstance(filter, FieldsFilter):
            fields = filter.get_fields()
            if not fields:
                return
            response_schema = self.get_response_schema("list")
            key = "__all__"
            if issubclass(response_schema, (PaginationFilter, TokenPaginationFilter)):
                key = "items"
            self.serializer_options["include"] = {key: fields}


class AsyncGenericListAPIView(
    AsyncListAPIView, BaseGenericListAPIView, WithAsyncRepositoryMixin
):
    """AsyncGenericListAPIView"""

    async def list(self, filter: BaseFilter) -> Sequence[M] | Page[M]:
        self._apply_fields_filter(filter)
        if isinstance(filter, BasePaginationFilter):
            return await self.repository.get_filtered_page(filter)
        return await self.repository.list(
            **filter.model_dump(exclude=filter.special_fields)
        )


class GenericListAPIView(ListAPIView, BaseGenericListAPIView, WithRepositoryMixin):
    """GenericListAPIView"""

    def list(self, filter: BaseFilter) -> Sequence[M] | Page[M]:
        self._apply_fields_filter(filter)
        if isinstance(filter, BasePaginationFilter):
            return self.repository.get_filtered_page(filter)
        return self.repository.list(**filter.model_dump(exclude=filter.special_fields))


class BaseGenericCreateAPIView(GenericView):
    if TYPE_CHECKING:
        create: Callable

    create_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        if not hasattr(cls, "create_schema"):
            return

        cls._patch_schema(cls.create)


class AsyncGenericCreateAPIView(
    BaseGenericCreateAPIView, AsyncCreateAPIView, WithAsyncRepositoryMixin[M]
):
    """AsyncGenericCreateAPIView"""

    async def create(self, create_schema: BaseModel) -> M:
        data = create_schema.model_dump()
        await self.before_create(data)
        obj = await self.repository.create(**data)
        if obj is None:
            msg = f"{self.get_name()} already exists"
            raise Conflict(msg)
        await self.after_create(obj)
        return obj

    async def before_create(self, data: dict[str, Any]) -> None:
        pass

    async def after_create(self, obj: M) -> None:
        pass


class GenericCreateAPIView(
    BaseGenericCreateAPIView, CreateAPIView, WithRepositoryMixin[M]
):
    """GenericCreateAPIView"""

    def create(self, create_schema: BaseModel) -> M:
        data = create_schema.model_dump()
        self.before_create(data)
        obj = self.repository.create(**data)
        if obj is None:
            msg = f"{self.get_name()} already exists"
            raise Conflict(msg)
        self.after_create(obj)
        return obj

    def before_create(self, data: dict[str, Any]) -> None:
        pass

    def after_create(self, obj: M) -> None:
        pass


class BaseGenericRetrieveAPIView(DetailGenericView[PK]):
    if TYPE_CHECKING:
        retrieve: Callable

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        if not hasattr(cls, "primary_key"):
            return
        cls._patch_pk_param(cls.retrieve)


class AsyncGenericRetrieveAPIView(
    BaseGenericRetrieveAPIView[PK], AsyncRetrieveAPIView, WithAsyncRepositoryMixin[M]
):
    """AsyncGenericRetrieveAPIView"""

    async def retrieve(self, pk: PK) -> M | None:
        args, kwargs = self.get_primary_key(pk, action="retrieve")
        return await self.repository.get(*args, **kwargs)


class GenericRetrieveAPIView(
    BaseGenericRetrieveAPIView[PK], RetrieveAPIView, WithRepositoryMixin[M]
):
    """GenericRetrieveAPIView"""

    def retrieve(self, pk: PK) -> M | None:
        args, kwargs = self.get_primary_key(pk, action="retrieve")
        return self.repository.get(*args, **kwargs)


class BaseGenericUpdateAPIView(DetailGenericView[PK]):
    if TYPE_CHECKING:
        update: Callable

    update_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "update_schema"):
            return

        cls._patch_pk_param(cls.update)
        cls._patch_schema(cls.update)


class AsyncGenericUpdateAPIView(
    BaseGenericUpdateAPIView[PK], AsyncUpdateAPIView, WithAsyncRepositoryMixin[M]
):
    """AsyncGenericUpdateAPIView"""

    async def update(self, pk: PK, update_schema: BaseModel) -> M:
        args, kwargs = self.get_primary_key(pk, action="update")
        data = update_schema.model_dump()
        await self.before_update(data)
        obj = await self.repository.update_one(data, *args, **kwargs)
        if obj is None:
            self.raise_not_found_error()
        await self.after_update(obj)
        return obj

    async def before_update(self, data: dict[str, Any]) -> None:
        pass

    async def after_update(self, obj: M) -> None:
        pass


class GenericUpdateAPIView(
    BaseGenericUpdateAPIView[PK], UpdateAPIView, WithRepositoryMixin[M]
):
    """GenericUpdateAPIView"""

    def update(self, pk: PK, update_schema: BaseModel) -> M:
        args, kwargs = self.get_primary_key(pk, action="update")
        data = update_schema.model_dump()
        self.before_update(data)
        obj = self.repository.update_one(data, *args, **kwargs)
        if obj is None:
            self.raise_not_found_error()
        self.after_update(obj)
        return obj

    def before_update(self, data: dict[str, Any]) -> None:
        pass

    def after_update(self, obj: M) -> None:
        pass


class BaseGenericPartialUpdateAPIView(DetailGenericView[PK]):
    if TYPE_CHECKING:
        partial_update: Callable

    partial_update_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "partial_update_schema"):
            return

        cls._patch_pk_param(cls.partial_update)
        cls._patch_schema(cls.partial_update)


class AsyncGenericPartialUpdateAPIView(
    BaseGenericPartialUpdateAPIView[PK],
    AsyncPartialUpdateAPIView,
    WithAsyncRepositoryMixin[M],
):
    """AsyncGenericPartialUpdateAPIView"""

    async def partial_update(self, pk: PK, partial_update_schema: BaseModel) -> Any:
        args, kwargs = self.get_primary_key(pk, action="update")
        data = partial_update_schema.model_dump(exclude_unset=True)
        await self.before_partial_update(data)
        obj = await self.repository.update_one(data, *args, **kwargs)
        if obj is None:
            self.raise_not_found_error()
        await self.after_partial_update(obj)
        return obj

    async def before_partial_update(self, data: dict[str, Any]) -> None:
        pass

    async def after_partial_update(self, new_obj: M) -> None:
        pass


class GenericPartialUpdateAPIView(
    BaseGenericPartialUpdateAPIView[PK], PartialUpdateAPIView, WithRepositoryMixin[M]
):
    """GenericPartialUpdateAPIView"""

    def partial_update(self, pk: PK, partial_update_schema: BaseModel) -> Any:
        args, kwargs = self.get_primary_key(pk, action="update")
        data = partial_update_schema.model_dump(exclude_unset=True)
        self.before_partial_update(data)
        obj = self.repository.update_one(data, *args, **kwargs)
        if obj is None:
            self.raise_not_found_error()
        self.after_partial_update(obj)
        return obj

    def before_partial_update(self, data: dict[str, Any]) -> None:
        pass

    def after_partial_update(self, new_obj: M) -> None:
        pass


class BaseGenericDestroyAPIView(DetailGenericView[PK]):
    if TYPE_CHECKING:
        destroy: Callable

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        if not hasattr(cls, "primary_key"):
            return

        cls._patch_pk_param(cls.destroy)


class AsyncGenericDestroyAPIView(
    BaseGenericDestroyAPIView[PK], AsyncDestroyAPIView, WithAsyncRepositoryMixin
):
    """AsyncGenericDestroyAPIView"""

    async def destroy(self, pk: PK) -> Any:
        args, kwargs = self.get_primary_key(pk, action="destroy")
        await self.repository.delete(*args, **kwargs)


class GenericDestroyAPIView(
    BaseGenericDestroyAPIView[PK], DestroyAPIView, WithRepositoryMixin
):
    """GenericDestroyAPIView"""

    def destroy(self, pk: PK) -> Any:
        args, kwargs = self.get_primary_key(pk, action="destroy")
        self.repository.delete(*args, **kwargs)


class AsyncGenericViewSet(
    AsyncGenericListAPIView,
    AsyncGenericRetrieveAPIView,
    AsyncGenericCreateAPIView,
    AsyncGenericUpdateAPIView,
    AsyncGenericPartialUpdateAPIView,
    AsyncGenericDestroyAPIView,
):
    """AsyncGenericViewSet"""


class GenericViewSet(
    GenericListAPIView,
    GenericRetrieveAPIView,
    GenericCreateAPIView,
    GenericUpdateAPIView,
    GenericPartialUpdateAPIView,
    GenericDestroyAPIView,
):
    """GenericViewSet"""
