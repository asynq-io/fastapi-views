from __future__ import annotations

import functools
import inspect
from collections import defaultdict
from collections.abc import AsyncIterable, Callable, Iterable
from typing import TYPE_CHECKING, Any, Concatenate, TypeVar

from fastapi.responses import StreamingResponse
from pydantic.type_adapter import TypeAdapter
from starlette.concurrency import iterate_in_threadpool
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from typing_extensions import NotRequired, ParamSpec, TypedDict, Unpack

from fastapi_views.models import AnyServerSideEvent, ServerSentEvent
from fastapi_views.models.errors import ErrorDetails

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
    """Build OpenAPI responses for the given errors.

    Error models are documented as explicit content under their declared
    `__content_type__` (`application/problem+json` for `ErrorDetails`).
    """
    status_to_exc: dict[int, list[type[APIError]]] = defaultdict(list)
    for e in exceptions:
        status = e.get_status()
        status_to_exc[status].append(e)
    responses: dict[int | str, dict[str, Any]] = {}
    for status, excs in status_to_exc.items():
        response: dict[str, Any] = {}
        if len(excs) == 1:
            response["description"] = excs[0].__doc__
        schemas = [e.model.get_openapi_schema() for e in excs]
        response["content"] = {
            ErrorDetails.__content_type__: {
                "schema": schemas[0] if len(schemas) == 1 else {"anyOf": schemas},
            },
        }
        responses[status] = response
    return responses


def throws(*exceptions: type[APIError]) -> Callable[..., EndpointFn]:
    return override(responses=errors(*exceptions))


def route(
    path: str = "",
    **kwargs: Unpack[RouteOptions],
) -> Callable[[EndpointFn], EndpointFn]:
    def wrapper(func: EndpointFn) -> EndpointFn:
        setattr(func, VIEWSET_ROUTE_FLAG, True)
        return override(path=path, **kwargs)(func)

    return wrapper


def action(
    path: str = "",
    *,
    detail: bool = False,
    **kwargs: Unpack[RouteOptions],
) -> Callable[[EndpointFn], EndpointFn]:
    """Register an extra routable method on a view (à la DRF's ``@action``).

    Sugar over :func:`route` that additionally:

    * defaults the path to the hyphenated method name (``mark_read`` -> ``/mark-read``),
    * nests the route under the view's detail route when ``detail=True``
      (e.g. ``POST /{id}/publish``),
    * documents ``response_headers`` on the success response.

    The OpenAPI response model comes from an explicit ``response_model`` option;
    otherwise it falls back to the view's ``response_schema``.

    Example::

        class ArticleViewSet(AsyncAPIViewSet):
            @action(methods=["POST"], detail=True, response_headers=LocationHeaders)
            async def publish(self, id: UUID) -> Article: ...
            # -> POST /{id}/publish
    """

    def wrapper(func: EndpointFn) -> EndpointFn:
        options: dict[str, Any] = dict(kwargs)
        options["path"] = path or f"/{func.__name__.replace('_', '-')}"
        if detail:
            options["detail"] = True
        setattr(func, VIEWSET_ROUTE_FLAG, True)
        func.__setattr__("kwargs", options)
        return func

    return wrapper


def serialize_sse(id: Any, event: Any, data: Any, retry: int | None = None) -> str:
    line = f"id: {id}\nevent: {event}\ndata: {data}\n"
    if retry is not None:
        line += f"retry: {retry}\n"
    return f"{line}\n"


async def _wrapped_events(
    iterable: Iterable[ServerSentEvent] | AsyncIterable[ServerSentEvent],
    data_serializer: TypeAdapter[Any],
    **options: Unpack[SerializerOptions],
) -> AsyncIterator[str]:
    if isinstance(iterable, AsyncIterable):
        async_iterable = iterable
    else:
        async_iterable = iterate_in_threadpool(iterable)
    async for sse in async_iterable:
        data = data_serializer.dump_json(sse.data, **options).decode("utf-8")
        yield serialize_sse(sse.id, sse.event, data, sse.retry)


def sse_route(
    path: str = "",
    serializer_options: SerializerOptions | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Unpack[RouteOptions],
) -> Any:
    status_code = kwargs.get("status_code", HTTP_200_OK)
    kwargs.setdefault("status_code", HTTP_200_OK)
    kwargs.setdefault("methods", ["GET"])
    response_model = kwargs.pop("response_model", None) or AnyServerSideEvent
    data_serializer: TypeAdapter[Any] = TypeAdapter(
        response_model.model_fields["data"].annotation
    )
    kwargs.update(
        {
            "response_model": None,
            "response_class": StreamingResponse,
            "responses": {
                status_code: {
                    "content": {
                        "text/event-stream": {
                            "schema": response_model.get_openapi_schema(),
                        }
                    }
                },
            },
        },
    )
    if headers is None:
        headers = {
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }

    def wrapper(
        func: Callable[
            Concatenate[V, _P],
            AsyncIterator[ServerSentEvent],
        ]
        | Callable[Concatenate[V, _P], Iterator[ServerSentEvent]],
    ) -> Callable[Concatenate[V, _P], Awaitable[StreamingResponse]]:

        @functools.wraps(func)
        async def wrapped(
            self: V,
            *args: _P.args,
            **kwargs: _P.kwargs,
        ) -> StreamingResponse:
            async_iterator = _wrapped_events(
                func(self, *args, **kwargs),
                data_serializer,
                **(serializer_options or {}),
            )
            return StreamingResponse(
                async_iterator,
                media_type="text/event-stream",
                headers=headers,
            )

        return route(path, **kwargs)(wrapped)

    return wrapper


def catch(
    exc_type: type[Exception] | tuple[type[Exception]],
    **kw: Any,
) -> Callable[
    [Callable[Concatenate[ErrorHandlerMixin, _P], Any]],
    Callable[Concatenate[ErrorHandlerMixin, _P], Any],
]:
    def wrapper(
        func: Callable[Concatenate[ErrorHandlerMixin, _P], Any],
    ) -> Callable[Concatenate[ErrorHandlerMixin, _P], Any]:
        @functools.wraps(func)
        async def wrapped_async(
            self: ErrorHandlerMixin,
            *args: _P.args,
            **kwargs: _P.kwargs,
        ) -> Any:
            try:
                return await func(self, *args, **kwargs)
            except exc_type as e:
                self.handle_error(e, **kw)

        @functools.wraps(func)
        def wrapped_sync(
            self: ErrorHandlerMixin,
            *args: _P.args,
            **kwargs: _P.kwargs,
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
        self: ErrorHandlerMixin,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> Any:
        try:
            return await func(self, *args, **kwargs)
        except self.get_exception_class() as e:
            self.handle_error(e)

    @functools.wraps(func)
    def wrapped_sync(
        self: ErrorHandlerMixin,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> Any:
        try:
            return func(self, *args, **kwargs)
        except self.get_exception_class() as e:
            self.handle_error(e)

    if inspect.iscoroutinefunction(func):
        return wrapped_async
    return wrapped_sync


def get(
    path: str = "",
    **kwargs: Unpack[BaseRouteOptions],
) -> Callable[[EndpointFn], EndpointFn]:
    return route(path, methods=["GET"], **kwargs)


def post(
    path: str = "",
    **kwargs: Unpack[BaseRouteOptions],
) -> Callable[[EndpointFn], EndpointFn]:
    kwargs.setdefault("status_code", HTTP_201_CREATED)
    return route(path, methods=["POST"], **kwargs)


def put(
    path: str = "",
    **kwargs: Unpack[BaseRouteOptions],
) -> Callable[[EndpointFn], EndpointFn]:
    return route(path, methods=["PUT"], **kwargs)


def patch(
    path: str = "",
    **kwargs: Unpack[BaseRouteOptions],
) -> Callable[[EndpointFn], EndpointFn]:
    return route(path, methods=["PATCH"], **kwargs)


def delete(
    path: str = "",
    **kwargs: Unpack[BaseRouteOptions],
) -> Callable[[EndpointFn], EndpointFn]:
    kwargs.setdefault("status_code", HTTP_204_NO_CONTENT)
    return route(path, methods=["DELETE"], **kwargs)
