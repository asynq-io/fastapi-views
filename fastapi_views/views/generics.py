from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Callable, Generic, Protocol

from fastapi import Depends
from pydantic import BaseModel
from typing_extensions import TypeVar

from fastapi_views.exceptions import Conflict, NotFound
from fastapi_views.filters.dependencies import FilterDepends
from fastapi_views.filters.models import Filter
from fastapi_views.pagination import NumberedPage
from fastapi_views.views.api import APIView

from .api import (
    AsyncCreateAPIView,
    AsyncDestroyAPIView,
    AsyncListAPIView,
    AsyncRetrieveAPIView,
    AsyncUpdateAPIView,
)

M_co = TypeVar("M_co", covariant=True)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_views.types import Action


class AsyncRepository(Protocol[M_co]):
    """Interface for repository pattern"""

    async def create(self, **kwargs: Any) -> M_co | None: ...

    async def get(self, *args: Any, **kwargs: Any) -> M_co | None: ...

    async def get_filtered_page(self, filter: Filter) -> None: ...

    async def list(self, *args: Any, **kwargs: Any) -> Sequence[M_co]: ...

    async def delete(self, *args: Any, **kwargs: Any) -> None: ...

    async def update_one(
        self, values: dict[str, Any], *args: Any, **kwargs: Any
    ) -> M_co | None: ...


M = TypeVar("M")


class GenericView(APIView, Generic[M]):
    repository: AsyncRepository[M]

    @classmethod
    def _patch_schema(cls, func: Callable, action: Action | None = None) -> None:
        name = action or func.__name__
        param = f"{name}_schema"
        schema = getattr(cls, param)
        func.__annotations__[param] = schema


class Id(BaseModel):
    id: int


PK = TypeVar("PK", bound=BaseModel)


class DetailGenericView(GenericView[M], Generic[M, PK]):
    primary_key: type[PK]

    @classmethod
    def _patch_pk_param(cls, func: Callable) -> None:
        func.__annotations__["pk"] = Annotated[BaseModel, Depends(cls.primary_key)]

    def get_primary_key(
        self, primary_key: PK, action: Action | None = None
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (), primary_key.model_dump()


class AsyncGenericListAPIView(AsyncListAPIView, GenericView):
    response_schema_as_list: bool = False
    filter: type[BaseModel] | None = None

    @classmethod
    def get_response_schema(cls, action: Action | None = None) -> Any:
        if action == "list":
            return NumberedPage[cls.response_schema]  # type: ignore[name-defined]
        return cls.response_schema

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        if cls.filter is None:
            return

        cls.list.__annotations__["filter"] = Annotated[
            Filter, FilterDepends(cls.filter)
        ]

    async def list(self: AsyncGenericListAPIView, filter: Filter) -> Any:
        return self.repository.get_filtered_page(filter)


CreateSchemaT = TypeVar("CreateSchemaT", bound=BaseModel)
UpdateSchemaT = TypeVar("UpdateSchemaT", bound=BaseModel)


class AsyncGenericCreateAPIView(GenericView[M], AsyncCreateAPIView):
    create_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        if not hasattr(cls, "create_schema"):
            return

        cls._patch_schema(cls.create)

    async def create(self, create_schema: BaseModel) -> Any:
        data = create_schema.model_dump()
        await self.before_create(data)
        obj: M | None = await self.repository.create(**data)
        if obj is None:
            msg = f"{self.get_name()} already exists"
            raise Conflict(msg)
        await self.after_create(obj)
        return obj

    async def before_create(self, data: dict[str, Any]) -> None:
        pass

    async def after_create(self, obj: M) -> None:
        pass


class AsyncGenericRetrieveAPIView(DetailGenericView[M, PK], AsyncRetrieveAPIView):
    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        if not hasattr(cls, "primary_key"):
            return
        cls._patch_pk_param(cls.retrieve)

    async def retrieve(self, pk: PK) -> M | None:
        args, kwargs = self.get_primary_key(pk, action="retrieve")
        return await self.repository.get(*args, **kwargs)


class AsyncGenericUpdateAPIView(DetailGenericView[M, PK], AsyncUpdateAPIView):
    update_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "update_schema"):
            return

        cls._patch_pk_param(cls.update)
        cls._patch_schema(cls.update)

    async def update(self, pk: PK, update_schema: BaseModel) -> M:
        args, kwargs = self.get_primary_key(pk, action="update")
        data = update_schema.model_dump()
        await self.before_update(data)
        obj = await self.repository.update_one(data, *args, **kwargs)
        if obj is None:
            msg = f"{self.get_name()} does not exist"
            raise NotFound(msg)
        await self.after_update(obj)
        return obj

    async def before_update(self, data: dict[str, Any]) -> None:
        pass

    async def after_update(self, obj: M) -> None:
        pass


class AsyncGenericPartialUpdateAPIView(DetailGenericView[M, PK], AsyncUpdateAPIView):
    partial_update_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "partial_update_schema"):
            return

        cls._patch_pk_param(cls.partial_update)
        cls._patch_schema(cls.partial_update)

    async def partial_update(self, pk: PK, partial_update_schema: BaseModel) -> Any:
        args, kwargs = self.get_primary_key(pk, action="update")
        data = partial_update_schema.model_dump(exclude_unset=True)
        await self.before_partial_update(data)
        obj = await self.repository.update_one(data, *args, **kwargs)
        if obj is None:
            msg = f"{self.get_name()} does not exist"
            raise NotFound(msg)
        await self.after_partial_update(obj)
        return obj

    async def before_partial_update(self, data: dict[str, Any]) -> None:
        pass

    async def after_partial_update(self, new_obj: M) -> None:
        pass


class AsyncGenericDestroyAPIView(DetailGenericView[M, PK], AsyncDestroyAPIView):
    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        if not hasattr(cls, "primary_key"):
            return

        cls._patch_pk_param(cls.destroy)

    async def destroy(self, pk: PK) -> Any:
        args, kwargs = self.get_primary_key(pk, action="destroy")
        await self.repository.delete(*args, **kwargs)


class AsyncGenericViewSet(
    AsyncGenericListAPIView,
    AsyncGenericRetrieveAPIView,
    AsyncGenericCreateAPIView,
    AsyncGenericUpdateAPIView,
    AsyncGenericPartialUpdateAPIView,
    AsyncGenericDestroyAPIView,
):
    pass
