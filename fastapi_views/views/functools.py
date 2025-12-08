from __future__ import annotations

import asyncio
import functools
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Callable, TypeVar, Union

from starlette.status import HTTP_204_NO_CONTENT
from typing_extensions import Concatenate, NotRequired, ParamSpec, TypedDict

if TYPE_CHECKING:
    from fastapi_views.exceptions import APIError
    from fastapi_views.views.api import View
    from fastapi_views.views.mixins import ErrorHandlerMixin

VIEWSET_ROUTE_FLAG = "_is_viewset_route"

_P = ParamSpec("_P")

V = TypeVar("V", bound="View")

EndpointFn = Callable[Concatenate[V, _P], Any]


def annotate(**kwargs: Any) -> Callable[[EndpointFn], EndpointFn]:
    def wrapper(func: EndpointFn) -> EndpointFn:
        func.__setattr__("kwargs", kwargs)
        return func

    return wrapper


override = annotate


class Responses(TypedDict):
    model: Any
    description: NotRequired[str | None]


def errors(*exceptions: type[APIError]) -> dict[int, Responses]:
    status_to_exc: dict[int, list[type[APIError]]] = defaultdict(list)
    for e in exceptions:
        status = e.get_status()
        status_to_exc[status].append(e)
    responses: dict[int, Responses] = {}
    for status, excs in status_to_exc.items():
        if len(excs) == 1:
            exc = excs[0]
            responses[status] = {"model": exc.model, "description": exc.__doc__}
        else:
            responses[status] = {"model": Union[tuple(e.model for e in excs)]}
    return responses


def throws(*exceptions: type[APIError]) -> Callable[..., EndpointFn]:
    return override(responses=errors(*exceptions))


def route(path: str, **kwargs: Any) -> Callable[[EndpointFn], EndpointFn]:
    def wrapper(func: EndpointFn) -> EndpointFn:
        setattr(func, VIEWSET_ROUTE_FLAG, True)
        return override(path=path, **kwargs)(func)

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


get = functools.partial(route, methods=["GET"])
post = functools.partial(route, methods=["POST"])
put = functools.partial(route, methods=["PUT"])
patch = functools.partial(route, methods=["PATCH"])
delete = functools.partial(route, methods=["DELETE"], status_code=HTTP_204_NO_CONTENT)
