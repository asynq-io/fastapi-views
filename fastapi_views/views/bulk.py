from __future__ import annotations

from abc import abstractmethod
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Generic,
    Protocol,
    TypeVar,
)

from fastapi import Response
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from typing_extensions import ParamSpec

from fastapi_views.exceptions import Conflict, NotFound
from fastapi_views.filters.dependencies import FilterDepends
from fastapi_views.filters.models import BaseFilter

from .api import APIView
from .functools import errors
from .generics import (
    AsyncRepository,
    GenericView,
    Repository,
    _NoFilter,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping, Sequence

    from pydantic import BaseModel

    from fastapi_views.types import Action, Endpoint

P = ParamSpec("P")
M = TypeVar("M")
M_co = TypeVar("M_co", covariant=True)


# --------------------------------------------------------------------------- #
# Repository protocols                                                         #
# --------------------------------------------------------------------------- #
class AsyncBulkRepository(AsyncRepository[M_co], Protocol[M_co]):
    """Repository contract required by the async bulk views.

    Extends :class:`~fastapi_views.views.generics.AsyncRepository` (bulk delete
    reuses its ``delete``). Implementations are expected to perform each operation
    atomically (one transaction) so the all-or-nothing guarantee holds.
    """

    async def bulk_create(
        self, items: Sequence[Mapping[str, Any]]
    ) -> Sequence[M_co]: ...

    async def bulk_update(
        self, items: Sequence[Mapping[str, Any]]
    ) -> Sequence[M_co]: ...


class BulkRepository(Repository[M_co], Protocol[M_co]):
    """Synchronous counterpart of :class:`AsyncBulkRepository`."""

    def bulk_create(
        self, items: Sequence[Mapping[str, Any]], **options: Any
    ) -> Sequence[M_co]: ...

    def bulk_update(
        self, items: Sequence[Mapping[str, Any]], **options: Any
    ) -> Sequence[M_co]: ...


class WithAsyncBulkRepositoryMixin(Generic[M]):
    repository: AsyncBulkRepository[M]


class WithBulkRepositoryMixin(Generic[M]):
    repository: BulkRepository[M]


# --------------------------------------------------------------------------- #
# Abstract views — routing, OpenAPI, endpoint generation                      #
# --------------------------------------------------------------------------- #
class BaseBulkCreateAPIView(APIView):
    bulk_create_route: str = "/bulk-create"
    return_on_create: bool = True

    @classmethod
    def get_response_schema(cls, action: Action | None = None) -> Any:
        if action == "bulk_create":
            return list[cls.response_schema]  # type: ignore[name-defined]
        return super().get_response_schema(action)

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("bulk_create", HTTP_201_CREATED)
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.bulk_create_route,
            endpoint=cls.get_bulk_create_endpoint(status_code),
            methods=["POST"],
            status_code=status_code,
            action="bulk_create",
            extra_errors=(Conflict,),
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_bulk_create_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError


class BulkCreateAPIView(BaseBulkCreateAPIView, Generic[P]):
    """Sync bulk create."""

    @classmethod
    def get_bulk_create_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="bulk_create")

        def endpoint(
            self: BulkCreateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            objs = self.bulk_create(*args, **kwargs)
            if not self.return_on_create:
                objs = None
            return self.get_response(objs, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.bulk_create)
        return endpoint

    @abstractmethod
    def bulk_create(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncBulkCreateAPIView(BaseBulkCreateAPIView, Generic[P]):
    """Async bulk create."""

    @classmethod
    def get_bulk_create_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="bulk_create")

        async def endpoint(
            self: AsyncBulkCreateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            objs = await self.bulk_create(*args, **kwargs)
            if not self.return_on_create:
                objs = None
            return self.get_response(objs, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.bulk_create)
        return endpoint

    @abstractmethod
    async def bulk_create(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseBulkUpdateAPIView(APIView):
    bulk_update_route: str = "/bulk-update"
    return_on_update: bool = True

    @classmethod
    def get_response_schema(cls, action: Action | None = None) -> Any:
        if action == "bulk_update":
            return list[cls.response_schema]  # type: ignore[name-defined]
        return super().get_response_schema(action)

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("bulk_update", HTTP_200_OK)
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.bulk_update_route,
            endpoint=cls.get_bulk_update_endpoint(status_code),
            methods=["PUT"],
            status_code=status_code,
            action="bulk_update",
            extra_errors=(NotFound, Conflict),
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_bulk_update_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError


class BulkUpdateAPIView(BaseBulkUpdateAPIView, Generic[P]):
    """Sync bulk update."""

    @classmethod
    def get_bulk_update_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="bulk_update")

        def endpoint(
            self: BulkUpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            objs = self.bulk_update(*args, **kwargs)
            if not self.return_on_update:
                objs = None
            return self.get_response(objs, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.bulk_update)
        return endpoint

    @abstractmethod
    def bulk_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncBulkUpdateAPIView(BaseBulkUpdateAPIView, Generic[P]):
    """Async bulk update."""

    @classmethod
    def get_bulk_update_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="bulk_update")

        async def endpoint(
            self: AsyncBulkUpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            objs = await self.bulk_update(*args, **kwargs)
            if not self.return_on_update:
                objs = None
            return self.get_response(objs, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.bulk_update)
        return endpoint

    @abstractmethod
    async def bulk_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseBulkDestroyAPIView(APIView):
    bulk_delete_route: str = "/bulk-delete"

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("bulk_delete", HTTP_204_NO_CONTENT)
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.bulk_delete_route,
            endpoint=cls.get_bulk_delete_endpoint(status_code),
            methods=["DELETE"],
            status_code=status_code,
            response_class=Response,
            action="bulk_delete",
            responses=errors(*cls.default_errors),
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_bulk_delete_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError


class BulkDestroyAPIView(BaseBulkDestroyAPIView, Generic[P]):
    """Sync bulk delete."""

    @classmethod
    def get_bulk_delete_endpoint(cls, status_code: int) -> Endpoint:
        def endpoint(
            self: BulkDestroyAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            self.bulk_delete(*args, **kwargs)
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.bulk_delete)
        return endpoint

    @abstractmethod
    def bulk_delete(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncBulkDestroyAPIView(BaseBulkDestroyAPIView, Generic[P]):
    """Async bulk delete."""

    @classmethod
    def get_bulk_delete_endpoint(cls, status_code: int) -> Endpoint:
        async def endpoint(
            self: AsyncBulkDestroyAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            await self.bulk_delete(*args, **kwargs)
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.bulk_delete)
        return endpoint

    @abstractmethod
    async def bulk_delete(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Generic, repository-backed views                                            #
# --------------------------------------------------------------------------- #


class BaseGenericBulkAPIView(GenericView):
    repository_options: ClassVar[dict[str, Any]] = {}

    def get_repository_options(
        self,
        action: Action | None = None,  # noqa: ARG002
    ) -> dict[str, Any]:
        return self.repository_options


class BaseGenericBulkCreateAPIView(BaseGenericBulkAPIView):
    if TYPE_CHECKING:
        bulk_create: Callable

    create_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "create_schema"):
            return
        cls.bulk_create.__annotations__["items"] = list[cls.create_schema]  # type: ignore[name-defined]


class AsyncGenericBulkCreateAPIView(
    BaseGenericBulkCreateAPIView,
    AsyncBulkCreateAPIView,
    WithAsyncBulkRepositoryMixin[M],
):
    """Async repository-backed bulk create."""

    async def bulk_create(self, items: list[BaseModel]) -> Sequence[M]:
        extra = self.get_kwargs("bulk_create")
        data = [item.model_dump() | extra for item in items]
        await self.before_bulk_create(data)
        objects = await self.repository.bulk_create(
            data, **self.get_repository_options("bulk_create")
        )
        await self.after_bulk_create(objects)
        return objects

    async def before_bulk_create(self, data: list[dict[str, Any]]) -> None:
        pass

    async def after_bulk_create(self, objects: Sequence[M]) -> None:
        pass


class GenericBulkCreateAPIView(
    BaseGenericBulkCreateAPIView,
    BulkCreateAPIView,
    WithBulkRepositoryMixin[M],
):
    """Sync repository-backed bulk create."""

    def bulk_create(self, items: list[BaseModel]) -> Sequence[M]:
        extra = self.get_kwargs("bulk_create")
        data = [item.model_dump() | extra for item in items]
        self.before_bulk_create(data)
        objects = self.repository.bulk_create(
            data, **self.get_repository_options("bulk_create")
        )
        self.after_bulk_create(objects)
        return objects

    def before_bulk_create(self, data: list[dict[str, Any]]) -> None:
        pass

    def after_bulk_create(self, objs: Sequence[M]) -> None:
        pass


class BaseGenericBulkUpdateAPIView(BaseGenericBulkAPIView):
    if TYPE_CHECKING:
        bulk_update: Callable

    #: Per-item schema for bulk updates — must carry the primary key.
    bulk_update_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "bulk_update_schema"):
            return
        cls.bulk_update.__annotations__["items"] = list[cls.bulk_update_schema]  # type: ignore[name-defined]


class AsyncGenericBulkUpdateAPIView(
    BaseGenericBulkUpdateAPIView,
    AsyncBulkUpdateAPIView,
    WithAsyncBulkRepositoryMixin[M],
):
    """Async repository-backed bulk update."""

    async def bulk_update(self, items: list[BaseModel]) -> Sequence[M]:
        extra = self.get_kwargs("bulk_update")
        data = [item.model_dump() | extra for item in items]
        await self.before_bulk_update(data)
        objs = await self.repository.bulk_update(
            data, **self.get_repository_options("bulk_update")
        )
        await self.after_bulk_update(objs)
        return objs

    async def before_bulk_update(self, data: list[dict[str, Any]]) -> None:
        pass

    async def after_bulk_update(self, objs: Sequence[M]) -> None:
        pass


class GenericBulkUpdateAPIView(
    BaseGenericBulkUpdateAPIView,
    BulkUpdateAPIView,
    WithBulkRepositoryMixin[M],
):
    """Sync repository-backed bulk update."""

    def bulk_update(self, items: list[BaseModel]) -> Sequence[M]:
        extra = self.get_kwargs("bulk_update")
        data = [item.model_dump() | extra for item in items]
        self.before_bulk_update(data)
        objs = self.repository.bulk_update(
            data, **self.get_repository_options("bulk_update")
        )
        self.after_bulk_update(objs)
        return objs

    def before_bulk_update(self, data: list[dict[str, Any]]) -> None:
        pass

    def after_bulk_update(self, objs: Sequence[M]) -> None:
        pass


class BaseGenericBulkDestroyAPIView(GenericView):
    if TYPE_CHECKING:
        bulk_delete: Callable

    #: Filter model selecting which rows to delete. Delete-by-id is just a filter
    #: with an ``id__in`` field; swap it for any criteria. Set to ``None`` to allow
    #: an unfiltered delete of everything matched by :meth:`get_kwargs`.
    filter: type[BaseModel] | None

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "filter"):
            return
        filter_ = cls.filter or _NoFilter
        cls.bulk_delete.__annotations__["filter"] = Annotated[
            BaseFilter,
            FilterDepends(filter_),  # type: ignore[type-var, unused-ignore]
        ]

    def resolve_filter(
        self, filter: BaseFilter
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (), filter.as_kwargs()

    def get_delete_args(
        self, filter: BaseFilter
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        if type(filter) is _NoFilter:
            return (), self.get_kwargs("bulk_delete")
        filter.with_kwargs(**self.get_kwargs("bulk_delete"))
        return self.resolve_filter(filter)


class AsyncGenericBulkDestroyAPIView(
    BaseGenericBulkDestroyAPIView,
    AsyncBulkDestroyAPIView,
    WithAsyncBulkRepositoryMixin[M],
):
    """Async bulk delete: resolve the filter, then ``repository.delete``."""

    async def bulk_delete(self, filter: BaseFilter) -> None:
        await self.before_bulk_delete(filter)
        args, kwargs = self.get_delete_args(filter)
        await self.repository.delete(*args, **kwargs)
        await self.after_bulk_delete(filter)

    async def before_bulk_delete(self, filter: BaseFilter) -> None:
        pass

    async def after_bulk_delete(self, filter: BaseFilter) -> None:
        pass


class GenericBulkDestroyAPIView(
    BaseGenericBulkDestroyAPIView,
    BulkDestroyAPIView,
    WithBulkRepositoryMixin[M],
):
    """Sync bulk delete: resolve the filter, then ``repository.delete``."""

    def bulk_delete(self, filter: BaseFilter) -> None:
        self.before_bulk_delete(filter)
        args, kwargs = self.get_delete_args(filter)
        self.repository.delete(*args, **kwargs)
        self.after_bulk_delete(filter)

    def before_bulk_delete(self, filter: BaseFilter) -> None:
        pass

    def after_bulk_delete(self, filter: BaseFilter) -> None:
        pass


# --------------------------------------------------------------------------- #
# Opt-in viewsets                                                             #
# --------------------------------------------------------------------------- #
class AsyncBulkAPIViewSet(
    AsyncGenericBulkCreateAPIView,
    AsyncGenericBulkUpdateAPIView,
    AsyncGenericBulkDestroyAPIView,
):
    """All three async bulk actions. Mix in alongside a regular viewset."""


class BulkAPIViewSet(
    GenericBulkCreateAPIView,
    GenericBulkUpdateAPIView,
    GenericBulkDestroyAPIView,
):
    """All three sync bulk actions. Mix in alongside a regular viewset."""
