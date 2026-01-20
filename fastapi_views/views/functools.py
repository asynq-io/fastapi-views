from __future__ import annotations

import functools
import inspect
from collections import defaultdict
from collections.abc import AsyncIterable, Iterable
from typing import TYPE_CHECKING, Any, Callable, TypeVar, Union

from fastapi.responses import StreamingResponse
from pydantic.type_adapter import TypeAdapter
from starlette.concurrency import iterate_in_threadpool
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from typing_extensions import Concatenate, NotRequired, ParamSpec, TypedDict, Unpack

from fastapi_views.models import AnyServerSideEvent, ServerSideEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Iterator

    from fastapi_views.exceptions import APIError
    from fastapi_views.types import (
        BaseRouteOptions,
        PathRouteOptions,
        RouteOptions,
        SerializerOptions,
    )
    from fastapi_views.views.api import View
    from fastapi_views.views.mixins import ErrorHandlerMixin

VIEWSET_ROUTE_FLAG = "_is_viewset_route"

_P = ParamSpec("_P")
V = TypeVar("V", bound="View")

EndpointFn = Callable[Concatenate[V, _P], Any]


def annotate(**kwargs: Unpack[PathRouteOptions]) -> Callable[[EndpointFn], EndpointFn]:
    def wrapper(func: EndpointFn) -> EndpointFn:
        func.__setattr__("kwargs", kwargs)
        return func

    return wrapper


override = annotate


class Responses(TypedDict):
    model: Any
    description: NotRequired[str | None]


def errors(*exceptions: type[APIError]) -> dict[int | str, dict[str, Any]]:
    status_to_exc: dict[int, list[type[APIError]]] = defaultdict(list)
    for e in exceptions:
        status = e.get_status()
        status_to_exc[status].append(e)
    responses: dict[int | str, dict[str, Any]] = {}
    for status, excs in status_to_exc.items():
        if len(excs) == 1:
            exc = excs[0]
            responses[status] = {"model": exc.model, "description": exc.__doc__}
        else:
            responses[status] = {"model": Union[tuple(e.model for e in excs)]}
    return responses


def throws(*exceptions: type[APIError]) -> Callable[..., EndpointFn]:
    return override(responses=errors(*exceptions))


def route(
    path: str = "", **kwargs: Unpack[RouteOptions]
) -> Callable[[EndpointFn], EndpointFn]:
    def wrapper(func: EndpointFn) -> EndpointFn:
        setattr(func, VIEWSET_ROUTE_FLAG, True)
        return override(path=path, **kwargs)(func)

    return wrapper


def serialize_sse(id: Any, event: Any, data: Any, retry: int | None = None) -> str:
    line = f"id: {id}\nevent: {event}\ndata: {data}\n"
    if retry is not None:
        line += f"retry: {retry}\n"
    return f"{line}]\n"


async def _wrapped_events(
    iterable: Iterable[Any] | AsyncIterable[Any],
    data_serializer: TypeAdapter[Any],
    **options: Unpack[SerializerOptions],
) -> AsyncIterator[str]:
    if isinstance(iterable, AsyncIterable):
        async_iterable = iterable
    else:
        async_iterable = iterate_in_threadpool(iterable)
    async for item in async_iterable:
        sse = AnyServerSideEvent.model_validate(item)
        validated_data = data_serializer.validate_python(sse.data)
        data = data_serializer.dump_json(validated_data, **options)
        yield serialize_sse(sse.id, sse.event, data, sse.retry)


def sse_route(
    path: str = "",
    serializer_options: SerializerOptions | None = None,
    **kwargs: Unpack[RouteOptions],
) -> Any:
    status_code = kwargs.get("status_code", HTTP_200_OK)
    kwargs.setdefault("status_code", HTTP_200_OK)
    kwargs.setdefault("methods", ["GET"])
    response_model = kwargs.pop("response_model", Any)
    schema = ServerSideEvent[response_model].get_openapi_schema(  # type: ignore[valid-type]
        title=f"{response_model.__name__.title()}ServerSideEvent"
    )
    data_serializer = TypeAdapter(response_model)
    kwargs.update(
        {
            "response_model": None,
            "response_class": StreamingResponse,
            "responses": {
                status_code: {"content": {"text/event-stream": {"schema": schema}}}
            },
        }
    )

    def wrapper(
        func: Callable[
            Concatenate[V, _P],
            AsyncIterator[Any],
        ]
        | Callable[Concatenate[V, _P], Iterator[Any]],
    ) -> Callable[Concatenate[V, _P], Awaitable[StreamingResponse]]:
        @functools.wraps(func)
        async def wrapped(
            self: V, *args: _P.args, **kwargs: _P.kwargs
        ) -> StreamingResponse:
            async_iterator = _wrapped_events(
                func(self, *args, **kwargs),
                data_serializer,
                **(serializer_options or {}),
            )
            return StreamingResponse(
                async_iterator,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-store",
                    "Connection": "keep-alive",
                },
            )

        return route(path, **kwargs)(wrapped)

    return wrapper


def catch(
    exc_type: type[Exception] | tuple[type[Exception]], **kw: Any
) -> Callable[
    [Callable[Concatenate[ErrorHandlerMixin, _P], Any]],
    Callable[Concatenate[ErrorHandlerMixin, _P], Any],
]:
    def wrapper(
        func: Callable[Concatenate[ErrorHandlerMixin, _P], Any],
    ) -> Callable[Concatenate[ErrorHandlerMixin, _P], Any]:
        @functools.wraps(func)
        async def wrapped_async(
            self: ErrorHandlerMixin, *args: _P.args, **kwargs: _P.kwargs
        ) -> Any:
            try:
                return await func(self, *args, **kwargs)
            except exc_type as e:
                self.handle_error(e, **kw)

        @functools.wraps(func)
        def wrapped_sync(
            self: ErrorHandlerMixin, *args: _P.args, **kwargs: _P.kwargs
        ) -> Any:
            try:
                return func(self, *args, **kwargs)
            except exc_type as e:
                self.handle_error(e, **kw)

        if inspect.iscoroutinefunction(func):
            return wrapped_async
        return wrapped_sync

    return wrapper


def catch_defined(
    func: Callable[Concatenate[ErrorHandlerMixin, _P], Any],
) -> Callable[Concatenate[ErrorHandlerMixin, _P], Any]:
    @functools.wraps(func)
    async def wrapped_async(
        self: ErrorHandlerMixin, *args: _P.args, **kwargs: _P.kwargs
    ) -> Any:
        try:
            return await func(self, *args, **kwargs)
        except self.get_exception_class() as e:
            self.handle_error(e)

    @functools.wraps(func)
    def wrapped_sync(
        self: ErrorHandlerMixin, *args: _P.args, **kwargs: _P.kwargs
    ) -> Any:
        try:
            return func(self, *args, **kwargs)
        except self.get_exception_class() as e:
            self.handle_error(e)

    if inspect.iscoroutinefunction(func):
        return wrapped_async
    return wrapped_sync


def get(
    path: str = "", **kwargs: Unpack[BaseRouteOptions]
) -> Callable[[EndpointFn], EndpointFn]:
    return route(path, methods=["GET"], **kwargs)


def post(
    path: str = "", **kwargs: Unpack[BaseRouteOptions]
) -> Callable[[EndpointFn], EndpointFn]:
    kwargs.setdefault("status_code", HTTP_201_CREATED)
    return route(path, methods=["POST"], **kwargs)


def put(
    path: str = "", **kwargs: Unpack[BaseRouteOptions]
) -> Callable[[EndpointFn], EndpointFn]:
    return route(path, methods=["PUT"], **kwargs)


def patch(
    path: str = "", **kwargs: Unpack[BaseRouteOptions]
) -> Callable[[EndpointFn], EndpointFn]:
    return route(path, methods=["PATCH"], **kwargs)


def delete(
    path: str = "", **kwargs: Unpack[BaseRouteOptions]
) -> Callable[[EndpointFn], EndpointFn]:
    kwargs.setdefault("status_code", HTTP_204_NO_CONTENT)
    return route(path, methods=["DELETE"], **kwargs)
