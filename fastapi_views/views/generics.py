from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Generic, NoReturn, Protocol, TypeVar

from fastapi import Depends
from pydantic import BaseModel

from fastapi_views.exceptions import Conflict
from fastapi_views.filters.dependencies import FilterDepends
from fastapi_views.filters.models import (
    BaseFilter,
    BasePaginationFilter,
    CursorPaginationFilter,
    FieldsFilter,
    OffsetLimitFilter,
    PaginationFilter,
)
from fastapi_views.pagination import BasePage, CursorPage, NumberedPage, OffsetPage

from .api import (
    APIView,
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
    from collections.abc import Iterable, Sequence

    from fastapi_views.types import Action


M = TypeVar("M")
PK = TypeVar("PK", bound=BaseModel)


class Id(BaseModel):
    id: int


class Page(Protocol[M_co]):
    @property
    def items(self) -> Sequence[M_co]: ...


class Repository(Protocol[M_co]):
    def create(self, **kwargs: Any) -> M_co | None: ...

    def get(self, *args: Any, **kwargs: Any) -> M_co | None: ...

    def get_filtered_page(
        self, filter: BasePaginationFilter, **kwargs: Any
    ) -> Page[M_co]: ...

    def list(self, *args: Any, **kwargs: Any) -> Sequence[M_co]: ...

    def delete_one(self, *args: Any, **kwargs: Any) -> M_co | None: ...

    def update_one(
        self,
        values: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> M_co | None: ...


class AsyncRepository(Protocol[M_co]):
    async def create(self, **kwargs: Any) -> M_co | None: ...

    async def get(self, *args: Any, **kwargs: Any) -> M_co | None: ...

    async def get_filtered_page(
        self, filter: BasePaginationFilter, **kwargs: Any
    ) -> Page[M_co]: ...

    async def list(self, *args: Any, **kwargs: Any) -> Sequence[M_co]: ...

    async def delete_one(self, *args: Any, **kwargs: Any) -> M_co | None: ...

    async def update_one(
        self,
        values: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> M_co | None: ...


class WithRepositoryMixin(Generic[M]):
    repository: Repository[M]


class WithAsyncRepositoryMixin(Generic[M]):
    repository: AsyncRepository[M]


class GenericView(APIView):
    def get_kwargs(self, _action: Action | None = None, /) -> dict[str, Any]:
        return {}


class DetailGenericView(GenericView, Generic[PK]):
    primary_key: type[PK]
    detail_response_schema: type[BaseModel] | None = None

    @classmethod
    def get_response_schema(
        cls, action: Action | None = None
    ) -> type[BaseModel] | None:
        if action == "retrieve" and cls.detail_response_schema is not None:
            return cls.detail_response_schema
        return super().get_response_schema(action)

    @classmethod
    def _pk_annotation(cls) -> Any:
        return Annotated[BaseModel, Depends(cls.primary_key)]

    def get_primary_key(
        self,
        primary_key: PK,
        action: Action | None = None,
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (), primary_key.model_dump() | self.get_kwargs(action)


class _NoFilter(BaseFilter):
    pass


def _nested_include(fields: Iterable[str]) -> dict[str, Any]:
    include: dict[str, Any] = {}
    for field in fields:
        *path, leaf = field.split("__")
        node = include
        for part in path:
            child = node.get(part)
            if child is True:
                break
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        else:
            node[leaf] = True
    return include


class BaseGenericListAPIView(GenericView):
    filter: type[BaseModel] | None

    @classmethod
    def get_response_schema(cls, action: Action | None = None) -> Any:
        if action == "list":
            container_cls: Any = list
            if cls.filter is not None:
                if issubclass(cls.filter, PaginationFilter):
                    container_cls = NumberedPage
                elif issubclass(cls.filter, OffsetLimitFilter):
                    container_cls = OffsetPage
                elif issubclass(cls.filter, CursorPaginationFilter):
                    container_cls = CursorPage
            return container_cls[cls.response_schema]
        return super().get_response_schema(action)

    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "list":
            filter_ = cls.filter or _NoFilter
            return {
                "filter": Annotated[
                    BaseFilter,
                    FilterDepends(filter_),  # type: ignore[type-var, unused-ignore]
                ]
            }
        return super().get_extra_annotations(action)

    def _apply_fields_filter(self, filter: BaseFilter) -> None:
        if isinstance(filter, FieldsFilter):
            if not (fields := filter.get_fields()):
                return
            include: dict[str, Any] = _nested_include(fields)
            key = self.get_fields_key()
            if key != "__all__":
                include = {"__all__": include}
            self.serializer_options["include"] = {key: include}

    def get_fields_key(self) -> str:
        response_schema = self.get_response_schema("list")
        return "items" if issubclass(response_schema, BasePage) else "__all__"

    def get_pagination_kwargs(self) -> dict[str, Any]:
        return {}

    def resolve_filter(
        self, filter: BaseFilter
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (), filter.as_kwargs()


class AsyncGenericListAPIView(
    BaseGenericListAPIView,
    AsyncListAPIView,
    WithAsyncRepositoryMixin[M],
):
    """AsyncGenericListAPIView"""

    async def list(self, filter: BaseFilter) -> Sequence[M] | Page[M]:
        self._apply_fields_filter(filter)
        filter.with_kwargs(**self.get_kwargs())

        await self.before_list(filter)
        if isinstance(filter, BasePaginationFilter):
            objects: Page[M] | Sequence[M] = await self.repository.get_filtered_page(
                filter, **self.get_pagination_kwargs()
            )
        else:
            args, kwargs = self.resolve_filter(filter)
            objects = await self.repository.list(*args, **kwargs)
        await self.after_list(objects)

        return objects

    async def before_list(self, filter: BaseFilter) -> None:
        pass

    async def after_list(self, objs: Sequence[M] | Page[M]) -> None:
        pass


class GenericListAPIView(BaseGenericListAPIView, ListAPIView, WithRepositoryMixin[M]):
    """GenericListAPIView"""

    def list(self, filter: BaseFilter) -> Sequence[M] | Page[M]:
        self._apply_fields_filter(filter)
        filter.with_kwargs(**self.get_kwargs())
        self.before_list(filter)

        if isinstance(filter, BasePaginationFilter):
            objects: Page[M] | Sequence[M] = self.repository.get_filtered_page(
                filter, **self.get_pagination_kwargs()
            )
        else:
            args, kwargs = self.resolve_filter(filter)
            objects = self.repository.list(*args, **kwargs)
        self.after_list(objects)
        return objects

    def before_list(self, filter: BaseFilter) -> None:
        pass

    def after_list(self, objs: Sequence[M] | Page[M]) -> None:
        pass


class BaseGenericCreateAPIView(GenericView):
    create_schema: type[BaseModel]
    raise_conflict_create_none: bool = True

    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "create":
            return {"create_schema": cls.create_schema}
        return {}

    def raise_conflict(self) -> NoReturn:
        msg = f"{self.get_name()} already exists"
        raise Conflict(msg)


class AsyncGenericCreateAPIView(
    BaseGenericCreateAPIView,
    AsyncCreateAPIView,
    WithAsyncRepositoryMixin[M],
):
    """AsyncGenericCreateAPIView"""

    async def create(self, create_schema: BaseModel) -> M | None:
        data = create_schema.model_dump()
        kwargs = self.get_kwargs("create")
        data.update(kwargs)
        await self.before_create(data)
        obj = await self.repository.create(**data)

        if obj is None and self.raise_conflict_create_none:
            self.raise_conflict()
        await self.after_create(obj)
        return obj

    async def before_create(self, data: dict[str, Any]) -> None:
        pass

    async def after_create(self, obj: M | None) -> None:
        pass


class GenericCreateAPIView(
    BaseGenericCreateAPIView,
    CreateAPIView,
    WithRepositoryMixin[M],
):
    """GenericCreateAPIView"""

    def create(self, create_schema: BaseModel) -> M | None:
        data = create_schema.model_dump()
        kwargs = self.get_kwargs("create")
        data.update(kwargs)
        self.before_create(data)
        obj = self.repository.create(**data)
        if obj is None and self.raise_conflict_create_none:
            self.raise_conflict()
        self.after_create(obj)
        return obj

    def before_create(self, data: dict[str, Any]) -> None:
        pass

    def after_create(self, obj: M | None) -> None:
        pass


class BaseGenericRetrieveAPIView(DetailGenericView[PK]):
    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "retrieve":
            return {"pk": cls._pk_annotation()}
        return {}


class AsyncGenericRetrieveAPIView(
    BaseGenericRetrieveAPIView[PK],
    AsyncRetrieveAPIView,
    WithAsyncRepositoryMixin[M],
):
    """AsyncGenericRetrieveAPIView"""

    async def retrieve(self, pk: PK) -> M | None:
        args, kwargs = self.get_primary_key(pk, action="retrieve")
        await self.before_retrieve(pk)
        obj = await self.repository.get(*args, **kwargs)
        await self.after_retrieve(obj)
        return obj

    async def before_retrieve(self, pk: PK) -> None:
        pass

    async def after_retrieve(self, obj: M | None) -> None:
        pass


class GenericRetrieveAPIView(
    BaseGenericRetrieveAPIView[PK],
    RetrieveAPIView,
    WithRepositoryMixin[M],
):
    """GenericRetrieveAPIView"""

    def retrieve(self, pk: PK) -> M | None:
        args, kwargs = self.get_primary_key(pk, action="retrieve")
        self.before_retrieve(pk)
        obj = self.repository.get(*args, **kwargs)
        self.after_retrieve(obj)
        return obj

    def before_retrieve(self, pk: PK) -> None:
        pass

    def after_retrieve(self, obj: M | None) -> None:
        pass


class BaseGenericUpdateAPIView(DetailGenericView[PK]):
    update_schema: type[BaseModel]

    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "update":
            return {"pk": cls._pk_annotation(), "update_schema": cls.update_schema}
        return {}


class AsyncGenericUpdateAPIView(
    BaseGenericUpdateAPIView[PK],
    AsyncUpdateAPIView,
    WithAsyncRepositoryMixin[M],
):
    """AsyncGenericUpdateAPIView"""

    async def update(self, pk: PK, update_schema: BaseModel) -> M | None:
        args, kwargs = self.get_primary_key(pk, action="update")
        data = update_schema.model_dump()
        await self.before_update(data)
        obj = await self.repository.update_one(data, *args, **kwargs)
        await self.after_update(obj)
        return obj

    async def before_update(self, data: dict[str, Any]) -> None:
        pass

    async def after_update(self, obj: M | None) -> None:
        pass


class GenericUpdateAPIView(
    BaseGenericUpdateAPIView[PK],
    UpdateAPIView,
    WithRepositoryMixin[M],
):
    """GenericUpdateAPIView"""

    def update(self, pk: PK, update_schema: BaseModel) -> M | None:
        args, kwargs = self.get_primary_key(pk, action="update")
        data = update_schema.model_dump()
        self.before_update(data)
        obj = self.repository.update_one(data, *args, **kwargs)
        self.after_update(obj)
        return obj

    def before_update(self, data: dict[str, Any]) -> None:
        pass

    def after_update(self, obj: M | None) -> None:
        pass


class BaseGenericPartialUpdateAPIView(DetailGenericView[PK]):
    partial_update_schema: type[BaseModel]

    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "partial_update":
            return {
                "pk": cls._pk_annotation(),
                "partial_update_schema": cls.partial_update_schema,
            }
        return {}


class AsyncGenericPartialUpdateAPIView(
    BaseGenericPartialUpdateAPIView[PK],
    AsyncPartialUpdateAPIView,
    WithAsyncRepositoryMixin[M],
):
    """AsyncGenericPartialUpdateAPIView"""

    async def partial_update(self, pk: PK, partial_update_schema: BaseModel) -> Any:
        args, kwargs = self.get_primary_key(pk, action="partial_update")
        data = partial_update_schema.model_dump(exclude_unset=True)
        await self.before_partial_update(data)
        obj = await self.repository.update_one(data, *args, **kwargs)
        await self.after_partial_update(obj)
        return obj

    async def before_partial_update(self, data: dict[str, Any]) -> None:
        pass

    async def after_partial_update(self, obj: M | None) -> None:
        pass


class GenericPartialUpdateAPIView(
    BaseGenericPartialUpdateAPIView[PK],
    PartialUpdateAPIView,
    WithRepositoryMixin[M],
):
    """GenericPartialUpdateAPIView"""

    def partial_update(self, pk: PK, partial_update_schema: BaseModel) -> Any:
        args, kwargs = self.get_primary_key(pk, action="partial_update")
        data = partial_update_schema.model_dump(exclude_unset=True)
        self.before_partial_update(data)
        obj = self.repository.update_one(data, *args, **kwargs)
        self.after_partial_update(obj)
        return obj

    def before_partial_update(self, data: dict[str, Any]) -> None:
        pass

    def after_partial_update(self, obj: M | None) -> None:
        pass


class BaseGenericDestroyAPIView(DetailGenericView[PK]):
    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "destroy":
            return {"pk": cls._pk_annotation()}
        return {}


class AsyncGenericDestroyAPIView(
    BaseGenericDestroyAPIView[PK],
    AsyncDestroyAPIView,
    WithAsyncRepositoryMixin[M],
):
    """AsyncGenericDestroyAPIView"""

    async def destroy(self, pk: PK) -> Any:
        args, kwargs = self.get_primary_key(pk, action="destroy")
        await self.repository.delete_one(*args, **kwargs)


class GenericDestroyAPIView(
    BaseGenericDestroyAPIView[PK],
    DestroyAPIView,
    WithRepositoryMixin[M],
):
    """GenericDestroyAPIView"""

    def destroy(self, pk: PK) -> Any:
        args, kwargs = self.get_primary_key(pk, action="destroy")
        self.repository.delete_one(*args, **kwargs)


class AsyncGenericViewSet(
    AsyncGenericListAPIView,
    AsyncGenericRetrieveAPIView,
    AsyncGenericCreateAPIView,
    AsyncGenericUpdateAPIView,
    AsyncGenericPartialUpdateAPIView,
    AsyncGenericDestroyAPIView,
    Generic[M, PK],
):
    """AsyncGenericViewSet"""


class GenericViewSet(
    GenericListAPIView,
    GenericRetrieveAPIView,
    GenericCreateAPIView,
    GenericUpdateAPIView,
    GenericPartialUpdateAPIView,
    GenericDestroyAPIView,
    Generic[M, PK],
):
    """GenericViewSet"""
