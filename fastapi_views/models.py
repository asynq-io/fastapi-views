from datetime import datetime
from typing import Any, Generic, Literal, Optional, TypeVar, Union
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)
from pydantic.alias_generators import to_camel
from pydantic_core import Url
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


D = TypeVar("D", bound=Any)


def _str_uuid() -> str:
    return str(uuid4())


class ServerSideEvent(BaseSchema, Generic[D]):
    id: str = Field(default_factory=_str_uuid)
    event: str
    data: D
    retry: Optional[int] = None

    @classmethod
    def get_openapi_schema(cls, title: Optional[str] = None) -> dict[str, Any]:
        schema_dump = cls.model_json_schema(
            ref_template="#/components/schemas/{model}", mode="serialization"
        )
        schema_dump.pop("$defs", None)
        if title:
            schema_dump["title"] = title
        return schema_dump


class AnyServerSideEvent(ServerSideEvent[Any]):
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
