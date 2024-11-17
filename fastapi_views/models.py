from datetime import datetime
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from pydantic.alias_generators import to_camel
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
from typing_extensions import Self

from .opentelemetry import get_correlation_id


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        use_enum_values=True, populate_by_name=True, from_attributes=True
    )


class CamelCaseSchema(BaseSchema):
    model_config = ConfigDict(alias_generator=to_camel)


class IdSchema(BaseSchema):
    id: UUID = Field(..., description="Entity ID")


class CreatedUpdatedSchema(BaseSchema):
    created_at: datetime = Field(..., description="Timestamp when entity was created")
    updated_at: datetime = Field(
        ..., description="Timestamp when entity was last updated"
    )


class IdCreatedUpdatedSchema(IdSchema, CreatedUpdatedSchema):
    pass


class ErrorDetails(BaseSchema):
    """
    Base Model for https://www.rfc-editor.org/rfc/rfc9457.html
    """

    @classmethod
    def new(cls: type[Self], detail: str, **kwargs: Any) -> Self:
        return cls(detail=detail, **kwargs)

    type: Union[Url, Literal["about:blank"]] = Field(
        "about:blank", description="Error type"
    )
    title: Optional[str] = Field("Bad Request", description="Error title")
    status: int = Field(HTTP_400_BAD_REQUEST, description="Error status")
    detail: str = Field(description="Error detail")
    instance: Optional[str] = Field(None, description="Requested instance")
    correlation_id: Optional[str] = Field(
        description="Optional correlation id", default_factory=get_correlation_id
    )
    errors: list[Any] = Field([], description="List of any additional errors")

    @field_validator("detail", mode="before")
    @classmethod
    def validate_detail(cls, v: Any) -> str:
        return v or "Internal Server Error"


def create_error_model(
    name: str, type: str, title: str, status: int
) -> type[ErrorDetails]:
    return create_model(
        name,
        __base__=ErrorDetails,
        type=(Literal[type], Field(type, description="Error type")),
        title=(Literal[title], Field(title, description="Error title")),
        status=(Literal[status], Field(status, description="Error status")),
    )


NotFoundErrorDetails = create_error_model(
    "NotFound",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.4",
    title="Not Found",
    status=HTTP_404_NOT_FOUND,
)

UnprocessableEntityErrorDetails = create_error_model(
    "UnprocessableEntity",
    type="https://datatracker.ietf.org/doc/html/rfc4918#section-11.2",
    title="Unprocessable Entity",
    status=HTTP_422_UNPROCESSABLE_ENTITY,
)


BadRequestErrorDetails = create_error_model(
    "BadRequest",
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
    "Forbidden",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.3",
    title="Forbidden",
    status=HTTP_403_FORBIDDEN,
)

TooManyRequestsErrorDetails = create_error_model(
    "TooManyRequests",
    type="https://datatracker.ietf.org/doc/html/rfc6585#section-4",
    title="Too many requests",
    status=HTTP_429_TOO_MANY_REQUESTS,
)

ConflictErrorDetails = create_error_model(
    "Conflict",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.8",
    title="Conflict",
    status=HTTP_409_CONFLICT,
)

ServiceUnavailableErrorDetails = create_error_model(
    "ServiceUnavailable",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.4",
    title="Service Unavailable",
    status=HTTP_503_SERVICE_UNAVAILABLE,
)

InternalServerErrorDetails = create_error_model(
    "InternalServer",
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.1",
    title="Internal Server Error",
    status=HTTP_500_INTERNAL_SERVER_ERROR,
)
