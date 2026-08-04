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
    GenericView,
    _NoFilter,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

    from pydantic import BaseModel

    from fastapi_views.types import Action, Endpoint

P = ParamSpec("P")
M = TypeVar("M")
M_co = TypeVar("M_co", covariant=True)


# --------------------------------------------------------------------------- #
# Repository protocols                                                         #
# --------------------------------------------------------------------------- #
class AsyncBulkRepository(Protocol[M_co]):
    """Repository contract required by the async bulk views.

    Only the methods the bulk views call are required: ``create_many`` and
    ``bulk_update`` receive one mapping per item; ``update_many`` applies a
    single values mapping to every row matching the criteria; ``delete_many``
    removes the matching rows. Implementations are expected to perform each
    operation atomically (one transaction) so the all-or-nothing guarantee
    holds.
    """

    async def create_many(
        self, items: Sequence[Mapping[str, Any]]
    ) -> Sequence[M_co]: ...

    async def update_many(
        self, values: Mapping[str, Any], /, *args: Any, **kwargs: Any
    ) -> Sequence[M_co]: ...

    async def bulk_update(self, items: Sequence[Mapping[str, Any]], /) -> None: ...

    async def delete_many(self, *args: Any, **kwargs: Any) -> None: ...


class BulkRepository(Protocol[M_co]):
    """Synchronous counterpart of :class:`AsyncBulkRepository`."""

    def create_many(self, items: Sequence[Mapping[str, Any]]) -> Sequence[M_co]: ...

    def update_many(
        self, values: Mapping[str, Any], /, *args: Any, **kwargs: Any
    ) -> Sequence[M_co]: ...

    def bulk_update(self, items: Sequence[Mapping[str, Any]], /) -> None: ...

    def delete_many(self, *args: Any, **kwargs: Any) -> None: ...


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
    """Per-item bulk update: many rows, each with its own values.

    Backed by an ``executemany``-style repository call which cannot return
    rows, so the route responds with ``204 No Content``.
    """

    bulk_update_route: str = "/bulk-update"

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("bulk_update", HTTP_204_NO_CONTENT)
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.bulk_update_route,
            endpoint=cls.get_bulk_update_endpoint(status_code),
            methods=["PUT"],
            status_code=status_code,
            response_class=Response,
            action="bulk_update",
            extra_errors=(NotFound, Conflict),
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_bulk_update_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError


class BulkUpdateAPIView(BaseBulkUpdateAPIView, Generic[P]):
    """Sync per-item bulk update."""

    @classmethod
    def get_bulk_update_endpoint(cls, status_code: int) -> Endpoint:
        def endpoint(
            self: BulkUpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            self.bulk_update(*args, **kwargs)
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.bulk_update)
        return endpoint

    @abstractmethod
    def bulk_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncBulkUpdateAPIView(BaseBulkUpdateAPIView, Generic[P]):
    """Async per-item bulk update."""

    @classmethod
    def get_bulk_update_endpoint(cls, status_code: int) -> Endpoint:
        async def endpoint(
            self: AsyncBulkUpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            await self.bulk_update(*args, **kwargs)
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.bulk_update)
        return endpoint

    @abstractmethod
    async def bulk_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseUpdateManyAPIView(APIView):
    """Filtered update: apply one set of values to every row a filter selects.

    The repository call can use ``RETURNING``, so the route responds with the
    updated objects by default.
    """

    update_many_route: str = "/bulk-update"
    return_on_update: bool = True

    @classmethod
    def get_response_schema(cls, action: Action | None = None) -> Any:
        if action == "update_many":
            return list[cls.response_schema]  # type: ignore[name-defined]
        return super().get_response_schema(action)

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("update_many", HTTP_200_OK)
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.update_many_route,
            endpoint=cls.get_update_many_endpoint(status_code),
            methods=["PATCH"],
            status_code=status_code,
            action="update_many",
            extra_errors=(Conflict,),
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_update_many_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError


class UpdateManyAPIView(BaseUpdateManyAPIView, Generic[P]):
    """Sync filtered update."""

    @classmethod
    def get_update_many_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="update_many")

        def endpoint(
            self: UpdateManyAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            objs = self.update_many(*args, **kwargs)
            if not self.return_on_update:
                objs = None
            return self.get_response(objs, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.update_many)
        return endpoint

    @abstractmethod
    def update_many(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncUpdateManyAPIView(BaseUpdateManyAPIView, Generic[P]):
    """Async filtered update."""

    @classmethod
    def get_update_many_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="update_many")

        async def endpoint(
            self: AsyncUpdateManyAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            objs = await self.update_many(*args, **kwargs)
            if not self.return_on_update:
                objs = None
            return self.get_response(objs, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.update_many)
        return endpoint

    @abstractmethod
    async def update_many(self, *args: P.args, **kwargs: P.kwargs) -> Any:
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
    create_schema: type[BaseModel]

    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "bulk_create":
            return {"items": list[cls.create_schema]}  # type: ignore[name-defined]
        return {}


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
        objects = await self.repository.create_many(
            data, **self.get_repository_options("bulk_create")
        )
        await self.after_bulk_create(objects)
        return objects

    async def before_bulk_create(self, data: list[dict[str, Any]]) -> None:
        """Hook receiving the validated payloads before the repository call."""

    async def after_bulk_create(self, objects: Sequence[M]) -> None:
        """Hook receiving the created objects before the response is built."""


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
        objects = self.repository.create_many(
            data, **self.get_repository_options("bulk_create")
        )
        self.after_bulk_create(objects)
        return objects

    def before_bulk_create(self, data: list[dict[str, Any]]) -> None:
        """Hook receiving the validated payloads before the repository call."""

    def after_bulk_create(self, objs: Sequence[M]) -> None:
        """Hook receiving the created objects before the response is built."""


class BaseGenericBulkUpdateAPIView(BaseGenericBulkAPIView):
    #: Per-item schema for bulk updates — must carry the primary key.
    bulk_update_schema: type[BaseModel]

    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "bulk_update":
            return {"items": list[cls.bulk_update_schema]}  # type: ignore[name-defined]
        return {}


class AsyncGenericBulkUpdateAPIView(
    BaseGenericBulkUpdateAPIView,
    AsyncBulkUpdateAPIView,
    WithAsyncBulkRepositoryMixin[M],
):
    """Async repository-backed per-item bulk update."""

    async def bulk_update(self, items: list[BaseModel]) -> None:
        extra = self.get_kwargs("bulk_update")
        data = [item.model_dump() | extra for item in items]
        await self.before_bulk_update(data)
        await self.repository.bulk_update(
            data, **self.get_repository_options("bulk_update")
        )
        await self.after_bulk_update()

    async def before_bulk_update(self, data: list[dict[str, Any]]) -> None:
        """Hook receiving the validated payloads before the repository call."""

    async def after_bulk_update(self) -> None:
        """Hook invoked after rows were updated."""


class GenericBulkUpdateAPIView(
    BaseGenericBulkUpdateAPIView,
    BulkUpdateAPIView,
    WithBulkRepositoryMixin[M],
):
    """Sync repository-backed per-item bulk update."""

    def bulk_update(self, items: list[BaseModel]) -> None:
        extra = self.get_kwargs("bulk_update")
        data = [item.model_dump() | extra for item in items]
        self.before_bulk_update(data)
        self.repository.bulk_update(data, **self.get_repository_options("bulk_update"))
        self.after_bulk_update()

    def before_bulk_update(self, data: list[dict[str, Any]]) -> None:
        """Hook receiving the validated payloads before the repository call."""

    def after_bulk_update(self) -> None:
        """Hook invoked after rows were updated."""


class BaseGenericFilteredBulkAPIView(GenericView):
    #: Filter model selecting which rows the action applies to. Acting by id is
    #: just a filter with an ``id__in`` field; swap it for any criteria. Set to
    #: ``None`` to act on everything matched by :meth:`get_kwargs`.
    filter: type[BaseModel] | None

    @classmethod
    def _filter_annotation(cls) -> Any:
        filter_ = cls.filter or _NoFilter
        return Annotated[
            BaseFilter,
            FilterDepends(filter_),  # type: ignore[type-var, unused-ignore]
        ]

    def resolve_filter(
        self, filter: BaseFilter
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (), filter.as_kwargs()

    def get_filter_args(
        self, filter: BaseFilter, action: Action | None = None
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        if type(filter) is _NoFilter:
            return (), self.get_kwargs(action)
        filter.with_kwargs(**self.get_kwargs(action))
        return self.resolve_filter(filter)


class BaseGenericUpdateManyAPIView(BaseGenericFilteredBulkAPIView):
    #: Schema of the values applied to every row selected by the filter.
    update_schema: type[BaseModel]

    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "update_many":
            return {
                "values": cls.update_schema,
                "filter": cls._filter_annotation(),
            }
        return {}


class AsyncGenericUpdateManyAPIView(
    BaseGenericUpdateManyAPIView,
    AsyncUpdateManyAPIView,
    WithAsyncBulkRepositoryMixin[M],
):
    """Async filtered update: one set of values applied to the matched rows."""

    async def update_many(self, values: BaseModel, filter: BaseFilter) -> Sequence[M]:
        data = values.model_dump(exclude_unset=True)
        args, kwargs = self.get_filter_args(filter, "update_many")
        await self.before_update_many(data)
        objs = await self.repository.update_many(data, *args, **kwargs)
        await self.after_update_many(objs)
        return objs

    async def before_update_many(self, values: dict[str, Any]) -> None:
        """Hook receiving the validated values before the repository call."""

    async def after_update_many(self, objs: Sequence[M]) -> None:
        """Hook receiving the updated objects before the response is built."""


class GenericUpdateManyAPIView(
    BaseGenericUpdateManyAPIView,
    UpdateManyAPIView,
    WithBulkRepositoryMixin[M],
):
    """Sync filtered update: one set of values applied to the matched rows."""

    def update_many(self, values: BaseModel, filter: BaseFilter) -> Sequence[M]:
        data = values.model_dump(exclude_unset=True)
        args, kwargs = self.get_filter_args(filter, "update_many")
        self.before_update_many(data)
        objs = self.repository.update_many(data, *args, **kwargs)
        self.after_update_many(objs)
        return objs

    def before_update_many(self, values: dict[str, Any]) -> None:
        """Hook receiving the validated values before the repository call."""

    def after_update_many(self, objs: Sequence[M]) -> None:
        """Hook receiving the updated objects before the response is built."""


class BaseGenericBulkDestroyAPIView(BaseGenericFilteredBulkAPIView):
    @classmethod
    def get_extra_annotations(cls, action: str) -> dict[str, Any]:
        if action == "bulk_delete":
            return {"filter": cls._filter_annotation()}
        return {}


class AsyncGenericBulkDestroyAPIView(
    BaseGenericBulkDestroyAPIView,
    AsyncBulkDestroyAPIView,
    WithAsyncBulkRepositoryMixin[M],
):
    """Async bulk delete: resolve the filter, then ``repository.delete_many``."""

    async def bulk_delete(self, filter: BaseFilter) -> None:
        await self.before_bulk_delete()
        args, kwargs = self.get_filter_args(filter, "bulk_delete")
        await self.repository.delete_many(*args, **kwargs)
        await self.after_bulk_delete()

    async def before_bulk_delete(self) -> None:
        """Hook invoked before rows are deleted."""

    async def after_bulk_delete(self) -> None:
        """Hook invoked after rows were deleted."""


class GenericBulkDestroyAPIView(
    BaseGenericBulkDestroyAPIView,
    BulkDestroyAPIView,
    WithBulkRepositoryMixin[M],
):
    """Sync bulk delete: resolve the filter, then ``repository.delete_many``."""

    def bulk_delete(self, filter: BaseFilter) -> None:
        self.before_bulk_delete()
        args, kwargs = self.get_filter_args(filter, "bulk_delete")
        self.repository.delete_many(*args, **kwargs)
        self.after_bulk_delete()

    def before_bulk_delete(self) -> None:
        """Hook invoked before rows are deleted."""

    def after_bulk_delete(self) -> None:
        """Hook invoked after rows were deleted."""


# --------------------------------------------------------------------------- #
# Opt-in viewsets                                                             #
# --------------------------------------------------------------------------- #
class AsyncBulkAPIViewSet(
    AsyncGenericBulkCreateAPIView,
    AsyncGenericBulkUpdateAPIView,
    AsyncGenericUpdateManyAPIView,
    AsyncGenericBulkDestroyAPIView,
):
    """All four async bulk actions. Mix in alongside a regular viewset."""


class BulkAPIViewSet(
    GenericBulkCreateAPIView,
    GenericBulkUpdateAPIView,
    GenericUpdateManyAPIView,
    GenericBulkDestroyAPIView,
):
    """All four sync bulk actions. Mix in alongside a regular viewset."""
