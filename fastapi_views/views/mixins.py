from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Callable, ClassVar, NoReturn

from starlette.status import HTTP_400_BAD_REQUEST

from fastapi_views.exceptions import APIError, NotFound

if TYPE_CHECKING:
    from fastapi import Request

    from fastapi_views.types import Action


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
