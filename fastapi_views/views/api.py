import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Generator
from typing import Any, Callable, ClassVar, Generic, TypeVar, Union

from fastapi import Depends, Request, Response
from opentelemetry.util.http import Optional
from pydantic.type_adapter import TypeAdapter
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from typing_extensions import Concatenate

from fastapi_views.errors.exceptions import (
    APIError,
    BadRequest,
    Conflict,
    NotFound,
)
from fastapi_views.types import Action, P, SerializerOptions

from .functools import VIEWSET_ROUTE_FLAG, errors
from .mixins import DetailViewMixin, ErrorHandlerMixin

Endpoint = Callable[..., Union[Response, Awaitable[Response]]]
T = TypeVar("T")
TypeAdapterMap = dict[T, TypeAdapter[T]]


class View(ABC):
    """
    Basic View Class
    Usage:
    from fastapi_views.views.functools import get, post, delete

    class MyCustomViewClass(View):

        @get("")
        async def get_items(self, ...):
            ...

        @post(path="")
    """

    media_type: Optional[str] = None
    api_component_name: str
    default_response_class: type[Response] = Response
    errors: tuple[type[APIError], ...] = ()

    def __init__(self, request: Request, response: Response) -> None:
        self.request = request
        self.response = response

    @classmethod
    def get_name(cls) -> str:
        return getattr(cls, "api_component_name", cls.__name__)

    @classmethod
    def get_slug_name(cls) -> str:
        return f"{cls.get_name().lower().replace(' ', '_')}"

    def get_response(
        self,
        content: Any,
        status_code: Optional[int] = None,
        response_class: Optional[type[Response]] = None,
    ) -> Response:
        if isinstance(content, Response):
            return content
        response_class = response_class or self.default_response_class
        return response_class(
            content=content,
            status_code=status_code or self.response.status_code or HTTP_200_OK,
            media_type=self.media_type,
            headers=dict(self.response.headers),
        )

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], Any, None]:
        yield from cls.get_custom_api_actions(prefix)

    @classmethod
    def get_custom_endpoint(
        cls, func: Callable[Concatenate["View", P], Any]
    ) -> Callable[Concatenate["View", P], Any]:
        options = getattr(func, "kwargs", {})
        status_code = options.get("status_code", None)
        response_class = options.get("response_class", None)

        async def _async_endpoint(
            self: View, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            res = await func(self, *args, **kwargs)
            return self.get_response(
                content=res, status_code=status_code, response_class=response_class
            )

        def _sync_endpoint(self: View, *args: P.args, **kwargs: P.kwargs) -> Response:
            res = func(self, *args, **kwargs)
            return self.get_response(
                content=res, status_code=status_code, response_class=response_class
            )

        endpoint = (
            _async_endpoint if asyncio.iscoroutinefunction(func) else _sync_endpoint
        )

        cls._patch_endpoint_signature(endpoint, func)
        return endpoint

    @classmethod
    def get_custom_api_actions(
        cls, prefix: str = ""
    ) -> Generator[dict[str, Any], None, None]:
        for _, route_endpoint in inspect.getmembers(
            cls, lambda member: callable(member) and hasattr(member, VIEWSET_ROUTE_FLAG)
        ):
            endpoint = cls.get_custom_endpoint(route_endpoint)
            yield cls.get_api_action(
                endpoint, prefix=prefix, name=f"{endpoint.__name__} {cls.get_name()}"
            )

    @classmethod
    def get_api_action(
        cls, endpoint: Callable, prefix: str = "", path: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        kw = getattr(endpoint, "kwargs", {})
        kwargs.update(kw)
        path = kwargs.get("path", path)
        kwargs["endpoint"] = endpoint
        kwargs["path"] = prefix + path
        kwargs.setdefault("name", endpoint.__name__)
        endpoint_name = kwargs["name"]
        kwargs.setdefault("methods", ["GET"])
        kwargs.setdefault("operation_id", f"{cls.get_slug_name()}_{endpoint_name}")
        kwargs["responses"] = {
            e.model.get_status(): {"model": e.model} for e in cls.errors
        } | kwargs.get("responses", {})
        return kwargs

    @classmethod
    def _patch_metadata(cls, endpoint: Any, method: Callable) -> None:
        endpoint.__doc__ = method.__doc__
        endpoint.__name__ = method.__name__
        endpoint.kwargs = getattr(method, "kwargs", {})

    @classmethod
    def _patch_endpoint_signature(cls, endpoint: Any, method: Callable) -> None:
        old_signature = inspect.signature(method)
        old_parameters: list[inspect.Parameter] = list(
            old_signature.parameters.values()
        )
        old_first_parameter = old_parameters[0]
        new_first_parameter = old_first_parameter.replace(default=Depends(cls))
        new_parameters = [new_first_parameter] + [
            parameter.replace(kind=inspect.Parameter.KEYWORD_ONLY)
            for parameter in old_parameters[1:]
        ]
        new_signature = old_signature.replace(parameters=new_parameters)
        endpoint.__signature__ = new_signature
        cls._patch_metadata(endpoint, method)


class APIView(View, ErrorHandlerMixin):
    """
    View with build-in json serialization via
    `serializer` and error handling
    """

    media_type = "application/json"
    validate_response: bool = False
    from_attributes: Optional[bool] = None
    response_schema: Any
    serializer_options: ClassVar[SerializerOptions] = {
        "by_alias": True,
    }
    _serializers: ClassVar[TypeAdapterMap] = {}

    @classmethod
    def get_extra_kwargs(cls, action: Action) -> dict[str, Any]:  # noqa: ARG003
        return {}

    @classmethod
    def get_response_schema(cls, action: Action) -> Any:  # noqa: ARG003
        return cls.response_schema

    def get_serializer(self, action: Action) -> TypeAdapter:
        response_schema = self.get_response_schema(action)
        if response_schema not in self._serializers:
            self._serializers[response_schema] = TypeAdapter(response_schema)
        return self._serializers[response_schema]

    def serialize_response(
        self,
        action: Action,
        content: Any,
        status_code: int = HTTP_200_OK,
    ) -> Response:
        if content is not None and not isinstance(content, (bytes, str)):
            serializer = self.get_serializer(action)
            if self.validate_response:
                content = serializer.validate_python(
                    content, from_attributes=self.from_attributes
                )

            content = serializer.dump_json(content, **self.serializer_options)
        if self.response.status_code is None:
            self.response.status_code = status_code
        return self.get_response(content)


class BaseListAPIView(APIView):
    response_schema_as_list: bool = True

    @classmethod
    def get_response_schema(cls: type["BaseListAPIView"], action: Action) -> Any:
        if action == "list" and cls.response_schema_as_list:
            return list[cls.response_schema]  # type: ignore[name-defined]
        return cls.response_schema

    @classmethod
    @abstractmethod
    def get_list_endpoint(cls) -> Endpoint:
        raise NotImplementedError

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_list_endpoint(),
            methods=["GET"],
            response_model=cls.get_response_schema("list"),
            responses=errors(BadRequest),
            name=f"List {cls.get_name()}",
            operation_id=f"list_{cls.get_slug_name()}",
            **cls.get_extra_kwargs("list"),
        )
        yield from super().get_api_actions(prefix)


class AsyncListAPIView(BaseListAPIView, ABC, Generic[P]):
    """Async list api view"""

    @classmethod
    def get_list_endpoint(cls) -> Endpoint:
        async def endpoint(
            self: AsyncListAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            objects = await self.list(*args, **kwargs)
            return self.serialize_response("list", objects)

        cls._patch_endpoint_signature(endpoint, cls.list)
        return endpoint

    @abstractmethod
    async def list(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class ListAPIView(BaseListAPIView, ABC, Generic[P]):
    """Sync list api view"""

    @classmethod
    def get_list_endpoint(cls) -> Endpoint:
        def endpoint(self: ListAPIView, *args: P.args, **kwargs: P.kwargs) -> Response:
            objects = self.list(*args, **kwargs)
            return self.serialize_response("list", objects)

        cls._patch_endpoint_signature(endpoint, cls.list)
        return endpoint

    @abstractmethod
    def list(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseRetrieveAPIView(APIView, DetailViewMixin):
    @classmethod
    @abstractmethod
    def get_retrieve_endpoint(cls) -> Endpoint:
        raise NotImplementedError

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_retrieve_endpoint(),
            path=cls.get_detail_route(action="retrieve"),
            methods=["GET"],
            responses=errors(BadRequest, NotFound),
            response_model=cls.get_response_schema(action="retrieve"),
            name=f"Get {cls.get_name()}",
            operation_id=f"get_{cls.get_slug_name()}",
            **cls.get_extra_kwargs("retrieve"),
        )
        yield from super().get_api_actions(prefix)


class RetrieveAPIView(BaseRetrieveAPIView, Generic[P]):
    """Sync retrieve api view"""

    @classmethod
    def get_retrieve_endpoint(cls) -> Endpoint:
        def endpoint(
            self: RetrieveAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = self.retrieve(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            return self.serialize_response("retrieve", obj)

        cls._patch_endpoint_signature(endpoint, cls.retrieve)
        return endpoint

    @abstractmethod
    def retrieve(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncRetrieveAPIView(BaseRetrieveAPIView, Generic[P]):
    """Async retrieve api view"""

    @classmethod
    def get_retrieve_endpoint(cls) -> Endpoint:
        async def endpoint(
            self: AsyncRetrieveAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = await self.retrieve(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            return self.serialize_response("retrieve", obj)

        cls._patch_endpoint_signature(endpoint, cls.retrieve)
        return endpoint

    @abstractmethod
    async def retrieve(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseCreateAPIView(APIView):
    return_on_create: bool = True

    @classmethod
    @abstractmethod
    def get_create_endpoint(cls) -> Endpoint:
        raise NotImplementedError

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_create_endpoint(),
            methods=["POST"],
            status_code=201,
            responses=errors(BadRequest, Conflict),
            response_model=cls.get_response_schema(action="create"),
            name=f"Create {cls.get_name()}",
            operation_id=f"create_{cls.get_slug_name()}",
            **cls.get_extra_kwargs("create"),
        )
        yield from super().get_api_actions(prefix)


class CreateAPIView(BaseCreateAPIView, Generic[P]):
    """Sync create api view"""

    @classmethod
    def get_create_endpoint(cls) -> Endpoint:
        def endpoint(
            self: CreateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = self.create(*args, **kwargs)
            if self.return_on_create:
                return self.serialize_response("create", obj, HTTP_201_CREATED)
            return Response(status_code=HTTP_201_CREATED)

        cls._patch_endpoint_signature(endpoint, cls.create)
        return endpoint

    @abstractmethod
    def create(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncCreateAPIView(BaseCreateAPIView, Generic[P]):
    """Async create api view"""

    @classmethod
    def get_create_endpoint(cls) -> Endpoint:
        async def endpoint(
            self: AsyncCreateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = await self.create(*args, **kwargs)
            if self.return_on_create:
                return self.serialize_response("create", obj, HTTP_201_CREATED)
            return Response(status_code=HTTP_201_CREATED)

        cls._patch_endpoint_signature(endpoint, cls.create)
        return endpoint

    @abstractmethod
    async def create(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseUpdateAPIView(APIView, DetailViewMixin):
    return_on_update: bool = True

    @classmethod
    @abstractmethod
    def get_update_endpoint(cls) -> Endpoint:
        raise NotImplementedError

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.get_detail_route(action="update"),
            endpoint=cls.get_update_endpoint(),
            methods=["PUT"],
            responses=errors(BadRequest, NotFound),
            response_model=cls.get_response_schema(action="update"),
            name=f"Update {cls.get_name()}",
            operation_id=f"update_{cls.get_slug_name()}",
            **cls.get_extra_kwargs("update"),
        )
        yield from super().get_api_actions(prefix)


class UpdateAPIView(BaseUpdateAPIView, Generic[P]):
    """Sync update api view"""

    @classmethod
    def get_update_endpoint(cls) -> Endpoint:
        def endpoint(
            self: UpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = self.update(*args, **kwargs)
            if not self.return_on_update:
                return Response(status_code=HTTP_200_OK)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            return self.serialize_response("update", obj)

        cls._patch_endpoint_signature(endpoint, cls.update)
        return endpoint

    @abstractmethod
    def update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncUpdateAPIView(BaseUpdateAPIView, Generic[P]):
    """Async update api view"""

    @classmethod
    def get_update_endpoint(cls) -> Endpoint:
        async def endpoint(
            self: AsyncUpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = await self.update(*args, **kwargs)
            if not self.return_on_update:
                return Response(status_code=HTTP_200_OK)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            return self.serialize_response("update", obj)

        cls._patch_endpoint_signature(endpoint, cls.update)
        return endpoint

    @abstractmethod
    async def update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BasePartialUpdateAPIView(APIView, DetailViewMixin):
    return_on_update: bool = True

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.get_detail_route(action="partial_update"),
            endpoint=cls.get_partial_update_endpoint(),
            methods=["PATCH"],
            responses=errors(BadRequest, NotFound),
            response_model=cls.get_response_schema(action="partial_update"),
            name=f"Partial update {cls.get_name()}",
            operation_id=f"patch_{cls.get_slug_name()}",
            **cls.get_extra_kwargs("partial_update"),
        )

        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_partial_update_endpoint(cls) -> Endpoint:
        raise NotImplementedError


class PartialUpdateAPIView(BasePartialUpdateAPIView, Generic[P]):
    """Sync partial update api view"""

    @classmethod
    def get_partial_update_endpoint(cls) -> Endpoint:
        def endpoint(
            self: PartialUpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = self.partial_update(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            if self.return_on_update:
                return self.serialize_response("partial_update", obj)
            return Response(status_code=HTTP_200_OK)

        cls._patch_endpoint_signature(endpoint, cls.partial_update)
        return endpoint

    @abstractmethod
    def partial_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncPartialUpdateAPIView(BasePartialUpdateAPIView, Generic[P]):
    """Async partial update api view"""

    @classmethod
    def get_partial_update_endpoint(cls) -> Endpoint:
        async def endpoint(
            self: AsyncPartialUpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = await self.partial_update(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            if self.return_on_update:
                return self.serialize_response("partial_update", obj)
            return Response(status_code=HTTP_200_OK)

        cls._patch_endpoint_signature(endpoint, cls.partial_update)
        return endpoint

    @abstractmethod
    async def partial_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseDestroyAPIView(APIView, DetailViewMixin):
    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.get_detail_route(action="destroy"),
            endpoint=cls.get_destroy_endpoint(),
            methods=["DELETE"],
            response_class=Response,
            responses=errors(BadRequest),
            status_code=HTTP_204_NO_CONTENT,
            name=f"Delete {cls.get_name()}",
            operation_id=f"delete_{cls.get_slug_name()}",
            **cls.get_extra_kwargs("destroy"),
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_destroy_endpoint(cls) -> Any:
        raise NotImplementedError


class DestroyAPIView(BaseDestroyAPIView, Generic[P]):
    """Sync destroy api view"""

    @classmethod
    def get_destroy_endpoint(cls) -> Endpoint:
        def endpoint(
            self: DestroyAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            self.destroy(*args, **kwargs)
            return Response(status_code=HTTP_204_NO_CONTENT)

        cls._patch_endpoint_signature(endpoint, cls.destroy)
        return endpoint

    @abstractmethod
    def destroy(self, *args: P.args, **kwargs: P.kwargs) -> None:
        raise NotImplementedError


class AsyncDestroyAPIView(BaseDestroyAPIView, Generic[P]):
    """Async destroy api view"""

    @classmethod
    def get_destroy_endpoint(cls) -> Endpoint:
        async def endpoint(
            self: AsyncDestroyAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            await self.destroy(*args, **kwargs)
            return Response(status_code=HTTP_204_NO_CONTENT)

        cls._patch_endpoint_signature(endpoint, cls.destroy)
        return endpoint

    @abstractmethod
    async def destroy(self, *args: P.args, **kwargs: P.kwargs) -> None:
        raise NotImplementedError
