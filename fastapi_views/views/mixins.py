from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn

from fastapi import Depends
from starlette.status import HTTP_400_BAD_REQUEST

from fastapi_views.exceptions import APIError, NotFound

if TYPE_CHECKING:
    from fastapi import Request

    from fastapi_views.types import Action


class DependencyMixin:
    @classmethod
    def _patch_endpoint_signature(cls, endpoint: Any, method: Callable) -> None:
        old_signature = inspect.signature(method)
        old_parameters: list[inspect.Parameter] = list(
            old_signature.parameters.values(),
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


class DetailViewMixin:
    detail_route: str = "/{id}"
    raise_on_none: bool = True
    request: Request
    get_name: Callable[..., str]
    error_message = "{} does not exist"

    @classmethod
    def get_detail_route(cls, action: Action) -> str:  # noqa: ARG003
        return cls.detail_route

    def raise_not_found_error(self) -> NoReturn:
        msg = self.error_message.format(self.get_name())
        raise NotFound(msg)


class _Sentinel(Exception):
    pass


class ErrorHandlerMixin:
    request: Request

    raises: ClassVar[dict[type[Exception], str | dict[str, Any]]] = {}

    def get_error_message(self, key: type[Exception]) -> str | dict[str, Any]:
        return self.raises.get(key, {})

    def handle_error(self, exc: Exception, **kwargs: Any) -> NoReturn:
        kw = self.get_error_message(type(exc))
        if isinstance(kw, str):
            kwargs["detail"] = kw
        elif isinstance(kw, Mapping):
            kwargs.update(kw)
        kwargs.setdefault("instance", self.request.url.path)
        kwargs.setdefault("title", type(exc).__name__)
        kwargs.setdefault("detail", str(exc))
        kwargs.setdefault("status", HTTP_400_BAD_REQUEST)
        raise APIError(**kwargs)

    def get_exception_class(self) -> tuple[type[Exception], ...] | type[Exception]:
        return tuple(self.raises.keys()) or _Sentinel
