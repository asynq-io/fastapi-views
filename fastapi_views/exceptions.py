from __future__ import annotations

import http
from typing import Any

from starlette.status import HTTP_400_BAD_REQUEST

from .models import (
    BadRequestErrorDetails,
    ConflictErrorDetails,
    ErrorDetails,
    ForbiddenErrorDetails,
    NotFoundErrorDetails,
    ServiceUnavailableErrorDetails,
    TooManyRequestsErrorDetails,
    UnauthorizedErrorDetails,
    UnprocessableEntityErrorDetails,
)


class APIError(Exception):
    model: type[ErrorDetails] | None = None
    default_kwargs: dict[str, Any] = {}

    def __init__(
        self,
        detail: str | None = None,
        *,
        status: int | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        if status:
            kwargs["status"] = status

        if detail:
            kwargs["detail"] = detail

        if self.model is None:
            kwargs.setdefault("status", HTTP_400_BAD_REQUEST)
            status_code = http.HTTPStatus(kwargs["status"])
            kwargs.setdefault("title", status_code.phrase)
            kwargs.setdefault("detail", status_code.description)

        self.headers = headers
        self.kwargs = self.default_kwargs | kwargs

    @classmethod
    def get_status(cls) -> int:
        if cls.model is None:
            msg = "Get status called on APIError without model"
            raise TypeError(msg)
        return cls.model.model_fields["status"].get_default()

    def as_model(self) -> ErrorDetails:
        model = self.model or ErrorDetails
        return model(**self.kwargs)


class NotFound(APIError):
    model = NotFoundErrorDetails


class UnprocessableEntity(APIError):
    model = UnprocessableEntityErrorDetails


class BadRequest(APIError):
    model = BadRequestErrorDetails


class Conflict(APIError):
    model = ConflictErrorDetails


class Throttled(APIError):
    model = TooManyRequestsErrorDetails


class Unauthorized(APIError):
    model = UnauthorizedErrorDetails


class Forbidden(APIError):
    model = ForbiddenErrorDetails


class Unavailable(APIError):
    model = ServiceUnavailableErrorDetails
