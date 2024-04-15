from typing import Any, ClassVar, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from pydantic_core import Url
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

from fastapi_views.opentelemetry import get_context_trace_id


class ErrorDetails(BaseModel):
    """
    Base Model for https://www.rfc-editor.org/rfc/rfc9457.html
    """

    _registry: ClassVar[dict[int, type["ErrorDetails"]]] = {}

    def __init_subclass__(cls, **kwargs):
        cls._registry[cls.get_status()] = cls

    type: Union[Url, Literal["about:blank"]] = Field(
        "about:blank",
        description="Error type",
    )
    title: Optional[str] = Field("Bad Request", description="Error title")
    status: int = Field(HTTP_400_BAD_REQUEST, description="Error status")
    detail: str = Field(
        ...,
        description="Error detail",
    )
    instance: Optional[str] = Field(None, description="Requested instance")
    trace_id: Optional[str] = Field(
        None, alias="traceId", description="Optional trace id", validate_default=True
    )
    errors: Optional[Any] = Field(None, description="Any additional multiple errors")

    @field_validator("detail", mode="before")
    @classmethod
    def validate_detail(cls, v):
        return v or "Internal Server Error"

    @field_validator("trace_id", mode="before")
    @classmethod
    def validate_trace_id(cls, v):
        if v is None:
            return get_context_trace_id()
        return v

    @classmethod
    def get_status(cls) -> int:
        return cls.model_fields["status"].get_default()

    @classmethod
    def get_model_for_status(cls, status: int):
        return cls._registry.get(status, cls)

    def model_dump_json(self, **kwargs) -> str:
        kwargs.setdefault("exclude_none", True)
        return super().model_dump_json(**kwargs)

    model_config = ConfigDict(
        use_enum_values=True, populate_by_name=True, extra="allow"
    )


def create_error_model(name: str, type: str, title: str, status: int):
    return create_model(
        name,
        __base__=ErrorDetails,
        type=(Literal[type], Field(type, description="Error type")),
        title=(Literal[title], Field(title, description="Error title")),
        status=(Literal[status], Field(status, description="Error status")),
    )


NotFoundErrorDetails = create_error_model(
    "NotFoundErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.4",
    title="Not Found",
    status=HTTP_404_NOT_FOUND,
)

UnprocessableEntityErrorDetails = create_error_model(
    "UnprocessableEntityErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc4918#section-11.2",
    title="Unprocessable Entity",
    status=HTTP_422_UNPROCESSABLE_ENTITY,
)


BadRequestErrorDetails = create_error_model(
    "BadRequestErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.1",
    title="Bad Request",
    status=HTTP_400_BAD_REQUEST,
)

UnauthorizedErrorDetails = create_error_model(
    "UnauthorizedErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc7235#section-3.1",
    title="Unauthorized",
    status=HTTP_401_UNAUTHORIZED,
)

ForbiddenErrorDetails = create_error_model(
    "ForbiddenErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.3",
    title="Forbidden",
    status=HTTP_403_FORBIDDEN,
)

TooManyRequestsErrorDetails = create_error_model(
    "TooManyRequestsErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc6585#section-4",
    title="Too many requests",
    status=HTTP_429_TOO_MANY_REQUESTS,
)

ConflictErrorDetails = create_error_model(
    "ConflictErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.8",
    title="Conflict",
    status=HTTP_409_CONFLICT,
)

ServiceUnavailableErrorDetails = create_error_model(
    "ServiceUnavailableErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.4",
    title="Service Unavailable",
    status=HTTP_503_SERVICE_UNAVAILABLE,
)

InternalServerErrorDetails = create_error_model(
    "InternalServerErrorDetails",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.1",
    title="Internal Server Error",
    status=HTTP_500_INTERNAL_SERVER_ERROR,
)
