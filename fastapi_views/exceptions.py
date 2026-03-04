from __future__ import annotations

import http
import re
from typing import Any, ClassVar

from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from .models import ErrorDetails, const_type, create_error_model


def _camel_to_title(name: str) -> str:
    """Convert CamelCase to Title Case (e.g., UserNotFound -> User Not Found)."""

    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)


_sentinel = object()

_RFC_TYPE_MAP: dict[int, str] = {
    HTTP_404_NOT_FOUND: "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.4",
    HTTP_422_UNPROCESSABLE_ENTITY: "https://datatracker.ietf.org/doc/html/rfc4918#section-11.2",
    HTTP_400_BAD_REQUEST: "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.1",
    HTTP_401_UNAUTHORIZED: "https://datatracker.ietf.org/doc/html/rfc7235#section-3.1",
    HTTP_409_CONFLICT: "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.8",
    HTTP_429_TOO_MANY_REQUESTS: "https://datatracker.ietf.org/doc/html/rfc6585#section-4",
    HTTP_403_FORBIDDEN: "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.3",
    HTTP_500_INTERNAL_SERVER_ERROR: "https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.1",
    HTTP_503_SERVICE_UNAVAILABLE: "https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.4",
}


class APIError(Exception):
    model: ClassVar[type[ErrorDetails]] = ErrorDetails

    status: ClassVar[int] = HTTP_400_BAD_REQUEST
    title: ClassVar[str]
    type: ClassVar[str]
    detail: ClassVar[str | None] = None

    def __init__(
        self,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self.headers = headers

        if detail:
            kwargs["detail"] = detail

        if self.model is ErrorDetails:
            status_code = kwargs.get("status", HTTP_400_BAD_REQUEST)
            status = http.HTTPStatus(status_code)
            kwargs.setdefault("status", status.value)
            kwargs.setdefault("title", status.phrase)
            kwargs.setdefault("detail", status.description)
            kwargs.setdefault("type", _RFC_TYPE_MAP.get(status_code, "about:blank"))
        self._model_instance = self.model(**kwargs)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        parent_model = cls.model
        if not cls._has_attr("title"):
            cls.title = _camel_to_title(cls.__name__)
        if not cls._has_attr("type"):
            cls.type = _RFC_TYPE_MAP.get(cls.status, "about:blank")
        extra_fields = cls._get_extra_fields()
        cls.model = create_error_model(
            status=cls.status,
            type=cls.type,
            title=cls.title,
            name=cls.__name__,
            detail=cls.detail,
            __doc__=cls.__doc__,
            __base__=parent_model,
            **extra_fields,
        )

    @classmethod
    def get_status(cls) -> int:
        return cls.status

    @property
    def status_code(self) -> int:
        return self._model_instance.status

    def as_model(self) -> ErrorDetails:
        return self._model_instance

    @classmethod
    def _has_attr(cls, attribute: str) -> bool:
        return attribute in cls.__dict__

    @classmethod
    def _get_extra_fields(cls) -> dict[str, tuple[Any, Any]]:
        extra_fields: dict[str, Any] = {}
        base_attrs = {"type", "title", "status", "detail", "model"}

        annotations = getattr(cls, "__annotations__", {})
        for field_name, field_type in annotations.items():
            if field_name in base_attrs or field_name.startswith("_"):
                continue

            # Get default value if exists
            default = getattr(cls, field_name, _sentinel)
            if default is _sentinel:
                extra_fields[field_name] = (field_type, ...)
            elif isinstance(default, (list, dict, set)):
                extra_fields[field_name] = (field_type, default)
            else:
                # Use const_type for Literal fields (like error_code)
                extra_fields[field_name] = const_type(default, field_name)
        return extra_fields


class NotFound(APIError):
    status = HTTP_404_NOT_FOUND


class UnprocessableEntity(APIError):
    status = HTTP_422_UNPROCESSABLE_ENTITY


class BadRequest(APIError):
    status = HTTP_400_BAD_REQUEST


class Unauthorized(APIError):
    status = HTTP_401_UNAUTHORIZED


class Conflict(APIError):
    status = HTTP_409_CONFLICT


class Throttled(APIError):
    title = "Too Many Requests"
    status = HTTP_429_TOO_MANY_REQUESTS


class Forbidden(APIError):
    status = HTTP_403_FORBIDDEN


class InternalServerError(APIError):
    status = HTTP_500_INTERNAL_SERVER_ERROR


class Unavailable(APIError):
    title = "Service Unavailable"
    status = HTTP_503_SERVICE_UNAVAILABLE
