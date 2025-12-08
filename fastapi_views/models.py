import http
from datetime import datetime
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
)
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

from .opentelemetry import get_correlation_id, has_opentelemetry


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
    title: str = Field(description="Error title")
    status: int = Field(description="Error status")
    detail: str = Field(description="Error detail")
    instance: Optional[str] = Field(None, description="Requested instance")

    if has_opentelemetry():
        correlation_id: Optional[str] = Field(
            description="Optional correlation id", default_factory=get_correlation_id
        )
    errors: list[Any] = Field([], description="List of any additional errors")


def const_type(
    value: Any, description: Optional[str] = None, **kwargs: Any
) -> tuple[Any, Any]:
    return (Literal[value], Field(value, description=description, **kwargs))


def create_error_model(
    status: int,
    type: str = "about:blank",
    name: Optional[str] = None,
    __doc__: Optional[str] = None,
    __base__: type[ErrorDetails] = ErrorDetails,
    **extra_fields: Any,
) -> type[ErrorDetails]:
    status_code = http.HTTPStatus(status)
    title = status_code.phrase
    if name is None:
        name = title.replace(" ", "")
    detail = status_code.description
    return create_model(
        name,
        __base__=__base__,
        __doc__=__doc__,
        title=const_type(title, "Error title"),
        status=const_type(status, "Error status"),
        type=const_type(type, "Error type"),
        detail=(str, Field(detail, description="Error detail")),
        **extra_fields,
    )


NotFoundErrorDetails = create_error_model(
    status=HTTP_404_NOT_FOUND,
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.4",
)

UnprocessableEntityErrorDetails = create_error_model(
    status=HTTP_422_UNPROCESSABLE_ENTITY,
    type="https://datatracker.ietf.org/doc/html/rfc4918#section-11.2",
)


BadRequestErrorDetails = create_error_model(
    status=HTTP_400_BAD_REQUEST,
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.1",
)

UnauthorizedErrorDetails = create_error_model(
    status=HTTP_401_UNAUTHORIZED,
    type="https://datatracker.ietf.org/doc/html/rfc7235#section-3.1",
)

ForbiddenErrorDetails = create_error_model(
    status=HTTP_403_FORBIDDEN,
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.3",
)

TooManyRequestsErrorDetails = create_error_model(
    status=HTTP_429_TOO_MANY_REQUESTS,
    type="https://datatracker.ietf.org/doc/html/rfc6585#section-4",
)

ConflictErrorDetails = create_error_model(
    status=HTTP_409_CONFLICT,
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.8",
)

ServiceUnavailableErrorDetails = create_error_model(
    status=HTTP_503_SERVICE_UNAVAILABLE,
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.4",
)

InternalServerErrorDetails = create_error_model(
    status=HTTP_500_INTERNAL_SERVER_ERROR,
    type="https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.1",
)
