from __future__ import annotations

from typing import Any, ClassVar

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
    _registry: ClassVar[dict[int, type[ErrorDetails]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._registry[cls.get_status()] = cls.model

    def __init__(
        self,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        if detail:
            kwargs["detail"] = detail
        self.headers = headers
        self.kwargs = kwargs

    @classmethod
    def get_status(cls) -> int:
        return cls.model.model_fields["status"].get_default()

    def as_model(self, **kwargs: Any) -> ErrorDetails:
        kwargs = {**self.kwargs, **kwargs}
        status = kwargs.get("status", self.get_status())
        model = self._registry.get(status, self.model)
        return model(**kwargs)


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
