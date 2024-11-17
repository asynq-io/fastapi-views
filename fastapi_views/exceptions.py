from __future__ import annotations

from typing import Any

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
    model: type[ErrorDetails] = ErrorDetails

    def __init__(
        self, detail: str, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> None:
        self.detail = detail
        self.headers = headers
        self.kwargs = kwargs

    @classmethod
    def get_status(cls) -> int:
        return cls.model.model_fields["status"].get_default()

    def as_model(self, **kwargs: Any) -> ErrorDetails:
        kwargs = {**self.kwargs, **kwargs}
        return self.model(detail=self.detail, **kwargs)


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
