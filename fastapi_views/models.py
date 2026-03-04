from __future__ import annotations

import http
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
)
from pydantic.alias_generators import to_camel
from pydantic_core import Url
from typing_extensions import Self

from .opentelemetry import get_correlation_id, has_opentelemetry

if TYPE_CHECKING:
    from datetime import datetime

    from pydantic_core import Url


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        use_enum_values=True,
        populate_by_name=True,
        from_attributes=True,
    )


class CamelCaseSchema(BaseSchema):
    model_config = ConfigDict(alias_generator=to_camel)


class IdSchema(BaseSchema):
    id: UUID = Field(..., description="Entity ID")


class CreatedUpdatedSchema(BaseSchema):
    created_at: datetime = Field(..., description="Timestamp when entity was created")
    updated_at: datetime = Field(
        ...,
        description="Timestamp when entity was last updated",
    )


class IdCreatedUpdatedSchema(IdSchema, CreatedUpdatedSchema):
    pass


D = TypeVar("D", bound=Any)


def _str_uuid() -> str:
    return str(uuid4())


class ServerSideEvent(BaseSchema, Generic[D]):
    id: str = Field(default_factory=_str_uuid)
    event: str
    data: D
    retry: int | None = None

    @classmethod
    def get_openapi_schema(cls, title: str | None = None) -> dict[str, Any]:
        schema_dump = cls.model_json_schema(
            ref_template="#/components/schemas/{model}",
            mode="serialization",
        )
        schema_dump.pop("$defs", None)
        if title:
            schema_dump["title"] = title
        return schema_dump


class AnyServerSideEvent(ServerSideEvent[Any]):
    pass


class ErrorDetails(BaseSchema):
    """Base Model for https://www.rfc-editor.org/rfc/rfc9457.html"""

    @classmethod
    def new(cls: type[Self], detail: str, **kwargs: Any) -> Self:
        return cls(detail=detail, **kwargs)

    type: Url | Literal["about:blank"] = Field(
        "about:blank",
        description="Error type",
    )
    title: str = Field(description="Error title")
    status: int = Field(description="Error status")
    detail: str = Field(description="Error detail")
    instance: str | None = Field(None, description="Requested instance")

    if has_opentelemetry():
        correlation_id: str | None = Field(
            description="Optional correlation id",
            default_factory=get_correlation_id,
        )

    errors: list[Any] = Field([], description="List of any additional errors")


def const_type(
    value: Any,
    description: str | None = None,
    **kwargs: Any,
) -> tuple[Any, Any]:
    return (Literal[value], Field(value, description=description, **kwargs))


def create_error_model(
    status: int,
    type: str = "about:blank",
    name: Optional[str] = None,
    title: Optional[str] = None,
    detail: Optional[str] = None,
    __doc__: Optional[str] = None,
    __base__: type[ErrorDetails] = ErrorDetails,
    **extra_fields: Any,
) -> type[ErrorDetails]:
    status_code = http.HTTPStatus(status)
    if title is None:
        title = status_code.phrase
    if name is None:
        name = title.replace(" ", "")
    if detail is None:
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
