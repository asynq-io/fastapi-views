from __future__ import annotations

import asyncio
import functools
from collections import defaultdict
from collections.abc import AsyncIterable, Iterable
from typing import TYPE_CHECKING, Any, Callable, TypeVar, Union

from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from typing_extensions import Concatenate, NotRequired, ParamSpec, TypedDict, Unpack

from fastapi_views.models import JsonServerSideEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Iterator

    from fastapi_views.exceptions import APIError
    from fastapi_views.types import BaseRouteOptions, PathRouteOptions, RouteOptions
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


def serialize_sse(id: Any, event: Any, data: Any) -> str:
    return f"id: {id}\nevent: {event}\ndata: {data}\n\n"


async def _wrapped_events(
    iterable: Iterable[tuple[str, str, str]] | AsyncIterable[tuple[str, str, Any]],
) -> AsyncIterator[str]:
    if isinstance(iterable, AsyncIterable):
        async_iterable = iterable
    else:
        async_iterable = iterate_in_threadpool(iterable)
    async for id, event, data in async_iterable:
        yield serialize_sse(id, event, data)


def sse_route(path: str = "", **kwargs: Unpack[RouteOptions]) -> Any:
    status_code = kwargs.get("status_code", HTTP_200_OK)
    kwargs.setdefault("status_code", HTTP_200_OK)
    kwargs.setdefault("methods", ["GET"])
    kwargs.update(
        {
            "response_class": StreamingResponse,
            "responses": {
                status_code: {
                    "content": {
                        "text/event-stream": {
                            "schema": JsonServerSideEvent.get_openapi_schema(
                                title="ServerSideEvent"
                            )
                        }
                    }
                }
            },
        }
    )

    def wrapper(
        func: Callable[
            Concatenate[V, _P],
            AsyncIterator[tuple[str, str, str]],
        ]
        | Callable[Concatenate[V, _P], Iterator[tuple[str, str, str]]],
    ) -> Callable[Concatenate[V, _P], Awaitable[StreamingResponse]]:
        @functools.wraps(func)
        async def wrapped(
            self: V, *args: _P.args, **kwargs: _P.kwargs
        ) -> StreamingResponse:
            async_iterator = _wrapped_events(func(self, *args, **kwargs))
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

        if asyncio.iscoroutinefunction(func):
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

    if asyncio.iscoroutinefunction(func):
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
