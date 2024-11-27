import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Generator
from typing import Any, Callable, ClassVar, Generic, Optional, TypeVar, Union

from fastapi import Depends, Request, Response
from fastapi.utils import is_body_allowed_for_status_code
from pydantic.type_adapter import TypeAdapter
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from typing_extensions import Concatenate

from fastapi_views.exceptions import (
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
    Base View Class
    """

    api_component_name: str
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

    def get_response(self, content: Any, *, status_code: int = HTTP_200_OK) -> Response:
        if isinstance(content, Response):
            return content

        self.response.status_code = status_code
        if content is None:
            return self.response

        if isinstance(content, str):
            content = content.encode(self.response.charset)
        if isinstance(content, bytes):
            self.response.body = content
            self.response.headers["Content-Length"] = str(len(content))
        return self.response

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], Any, None]:
        yield from cls.get_custom_api_actions(prefix)

    @classmethod
    def get_custom_endpoint(
        cls, func: Callable[Concatenate["View", P], Any]
    ) -> Callable[Concatenate["View", P], Any]:
        options = getattr(func, "kwargs", {})
        status_code = options.get("status_code", None)

        async def _async_endpoint(
            self: View, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            res = await func(self, *args, **kwargs)
            return self.get_response(res, status_code=status_code)

        def _sync_endpoint(self: View, *args: P.args, **kwargs: P.kwargs) -> Response:
            res = func(self, *args, **kwargs)
            return self.get_response(res, status_code=status_code)

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
            e.get_status(): {"model": e.model} for e in cls.errors
        } | kwargs.get("responses", {})
        status_code = kwargs.get("status_code", HTTP_200_OK)
        if not is_body_allowed_for_status_code(status_code):
            kwargs["response_model"] = None
        return kwargs

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
        endpoint.__doc__ = method.__doc__
        endpoint.__name__ = method.__name__
        endpoint.kwargs = getattr(method, "kwargs", {})


class APIView(View, ErrorHandlerMixin, Generic[T]):
    """
    View with build-in json serialization via
    `serializer` and error handling
    """

    content_type: str = "application/json"
    validate_response: bool = False
    from_attributes: Optional[bool] = None
    response_schema: Optional[T] = None
    serializer_options: ClassVar[SerializerOptions] = {
        "by_alias": True,
    }
    _serializers: ClassVar[TypeAdapterMap] = {}
    default_errors: tuple[type[APIError], ...] = (BadRequest,)

    def __init__(self, request: Request, response: Response) -> None:
        response.headers["Content-Type"] = self.content_type
        super().__init__(request, response)

    @classmethod
    def get_api_action(
        cls,
        endpoint: Callable,
        prefix: str = "",
        path: str = "",
        action: Optional[Action] = None,
        extra_errors: tuple[type[APIError], ...] = (),
        **kwargs: Any,
    ) -> dict[str, Any]:
        if action:
            kwargs.setdefault("name", f"{action.title()} {cls.get_name()}")
            kwargs.setdefault("operation_id", f"{action}_{cls.get_slug_name()}")

        kwargs.setdefault("response_model", cls.get_response_schema(action))
        kwargs.setdefault("responses", errors(*extra_errors, *cls.default_errors))
        return super().get_api_action(endpoint, prefix=prefix, path=path, **kwargs)

    @classmethod
    def get_status_code(cls, endpoint: str, default: int = HTTP_200_OK) -> int:
        method = getattr(cls, endpoint, None)
        return getattr(method, "kwargs", {}).get("status_code", default)

    @classmethod
    def get_response_schema(cls, action: Optional[Action] = None) -> Optional[T]:  # noqa: ARG003
        return cls.response_schema

    def get_serializer(self, action: Optional[Action] = None) -> TypeAdapter[T]:
        response_schema = self.get_response_schema(action)
        if response_schema not in self._serializers:
            self._serializers[response_schema] = TypeAdapter(response_schema)
        return self._serializers[response_schema]

    def get_response(
        self,
        content: Any,
        *,
        status_code: int = HTTP_200_OK,
        action: Optional[Action] = None,
    ) -> Response:
        if not isinstance(content, (str, bytes, Response)):
            serializer = self.get_serializer(action)
            if self.validate_response:
                content = serializer.validate_python(
                    content, from_attributes=self.from_attributes
                )
            content = serializer.dump_json(content, **self.serializer_options)
        return super().get_response(content, status_code=status_code)


class BaseListAPIView(APIView):
    response_schema_as_list: bool = True

    @classmethod
    def get_response_schema(
        cls: type["BaseListAPIView"], action: Optional[Action] = None
    ) -> Any:
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
            action="list",
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
            return self.get_response(objects, status_code=HTTP_200_OK, action="list")

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
            return self.get_response(objects, status_code=HTTP_200_OK, action="list")

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
            action="retrieve",
            extra_errors=(NotFound,),
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
            return self.get_response(obj, action="retrieve")

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
            return self.get_response(obj, action="retrieve")

        cls._patch_endpoint_signature(endpoint, cls.retrieve)
        return endpoint

    @abstractmethod
    async def retrieve(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseCreateAPIView(APIView):
    return_on_create: bool = True

    @classmethod
    @abstractmethod
    def get_create_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError

    def get_location(self, obj: Any) -> Optional[str]:
        return None

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("create", HTTP_201_CREATED)
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_create_endpoint(status_code),
            methods=["POST"],
            status_code=status_code,
            action="create",
            extra_errors=(Conflict,),
        )
        yield from super().get_api_actions(prefix)


class CreateAPIView(BaseCreateAPIView, Generic[P]):
    """Sync create api view"""

    @classmethod
    def get_create_endpoint(cls, status_code: int) -> Endpoint:
        def endpoint(
            self: CreateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = self.create(*args, **kwargs)
            location = self.get_location(obj)
            if location:
                self.response.headers["location"] = location
            if self.return_on_create:
                return self.get_response(obj, status_code=status_code, action="create")
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.create)
        return endpoint

    @abstractmethod
    def create(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncCreateAPIView(BaseCreateAPIView, Generic[P]):
    """Async create api view"""

    @classmethod
    def get_create_endpoint(cls, status_code: int) -> Endpoint:
        async def endpoint(
            self: AsyncCreateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = await self.create(*args, **kwargs)
            location = self.get_location(obj)
            if location:
                self.response.headers["location"] = location
            if self.return_on_create:
                return self.get_response(obj, status_code=status_code, action="create")
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.create)
        return endpoint

    @abstractmethod
    async def create(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseUpdateAPIView(APIView, DetailViewMixin):
    return_on_update: bool = True

    @classmethod
    @abstractmethod
    def get_update_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("update")
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.get_detail_route(action="update"),
            endpoint=cls.get_update_endpoint(status_code),
            methods=["PUT"],
            status_code=status_code,
            action="update",
            extra_errors=(NotFound,),
        )
        yield from super().get_api_actions(prefix)


class UpdateAPIView(BaseUpdateAPIView, Generic[P]):
    """Sync update api view"""

    @classmethod
    def get_update_endpoint(cls, status_code: int) -> Endpoint:
        def endpoint(
            self: UpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = self.update(*args, **kwargs)
            if not self.return_on_update:
                return Response(status_code=status_code)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            return self.get_response(obj, status_code=status_code, action="update")

        cls._patch_endpoint_signature(endpoint, cls.update)
        return endpoint

    @abstractmethod
    def update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncUpdateAPIView(BaseUpdateAPIView, Generic[P]):
    """Async update api view"""

    @classmethod
    def get_update_endpoint(cls, status_code: int) -> Endpoint:
        async def endpoint(
            self: AsyncUpdateAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            obj = await self.update(*args, **kwargs)
            if not self.return_on_update:
                return Response(status_code=status_code)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            return self.get_response(obj, status_code=status_code, action="update")

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
            action="partial_update",
            extra_errors=(BadRequest,),
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
                return self.get_response(obj, action="partial_update")
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
                return self.get_response(obj, action="partial_update")
            return Response(status_code=HTTP_200_OK)

        cls._patch_endpoint_signature(endpoint, cls.partial_update)
        return endpoint

    @abstractmethod
    async def partial_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseDestroyAPIView(APIView, DetailViewMixin):
    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("destroy", HTTP_204_NO_CONTENT)
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.get_detail_route(action="destroy"),
            endpoint=cls.get_destroy_endpoint(status_code),
            methods=["DELETE"],
            status_code=status_code,
            response_class=Response,
            action="destroy",
            responses=errors(*cls.default_errors),
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_destroy_endpoint(cls, status_code: int) -> Any:
        raise NotImplementedError


class DestroyAPIView(BaseDestroyAPIView, Generic[P]):
    """Sync destroy api view"""

    @classmethod
    def get_destroy_endpoint(cls, status_code: int) -> Endpoint:
        def endpoint(
            self: DestroyAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            self.destroy(*args, **kwargs)
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.destroy)
        return endpoint

    @abstractmethod
    def destroy(self, *args: P.args, **kwargs: P.kwargs) -> None:
        raise NotImplementedError


class AsyncDestroyAPIView(BaseDestroyAPIView, Generic[P]):
    """Async destroy api view"""

    @classmethod
    def get_destroy_endpoint(cls, status_code: int) -> Endpoint:
        async def endpoint(
            self: AsyncDestroyAPIView, *args: P.args, **kwargs: P.kwargs
        ) -> Response:
            await self.destroy(*args, **kwargs)
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.destroy)
        return endpoint

    @abstractmethod
    async def destroy(self, *args: P.args, **kwargs: P.kwargs) -> None:
        raise NotImplementedError
