import http
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
)
from pydantic.alias_generators import to_camel
from pydantic_core import Url
from typing_extensions import Self

from .opentelemetry import OPENTELEMETRY_INSTALLED, get_correlation_id
from .utils import str_uuid


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


class _OpenAPIBase(BaseSchema):
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


_IGNORED_HEADER_SCHEMA_KEYS = frozenset({"description", "title", "default"})


def _simplify_header_schema(prop: dict[str, Any]) -> dict[str, Any]:
    """Build a header ``schema`` from a property, collapsing nullable unions.

    A field typed as ``X | None`` yields ``anyOf: [X, null]``; response headers
    are never null, so the null branch is dropped and the remaining type merged.
    """
    schema = {
        key: value
        for key, value in prop.items()
        if key not in _IGNORED_HEADER_SCHEMA_KEYS
    }
    any_of = schema.get("anyOf")
    if any_of is None:
        return schema
    non_null = [option for option in any_of if option.get("type") != "null"]
    if len(non_null) != 1:
        return schema
    del schema["anyOf"]
    return {**schema, **non_null[0]}


class ResponseHeaders(_OpenAPIBase):
    """Class used to specify OpenAPI for response headers.

    Each field is rendered as an OpenAPI `Header Object
    <https://spec.openapis.org/oas/v3.1.0#header-object>`_: ``description`` is
    lifted to the top level, the remaining JSON schema is nested under
    ``schema``, and required fields are flagged with ``required: true``.
    """

    @classmethod
    def get_openapi_schema(cls, title: str | None = None) -> dict[str, Any]:
        base = super().get_openapi_schema(title=title)
        required = base.get("required", [])
        headers: dict[str, Any] = {}
        for name, prop in base["properties"].items():
            header: dict[str, Any] = {}
            description = prop.get("description")
            if description is not None:
                header["description"] = description
            if name in required:
                header["required"] = True
            header["schema"] = _simplify_header_schema(prop)
            headers[name] = header
        return headers


class ServerSentEvent(_OpenAPIBase, Generic[D]):
    id: str = Field(default_factory=str_uuid)
    event: str
    data: D
    retry: int | None = None


class AnyServerSideEvent(ServerSentEvent[Any]):
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

    if OPENTELEMETRY_INSTALLED:
        correlation_id: str | None = Field(
            default_factory=get_correlation_id,
            description="Request correlation identifier",
        )

    errors: list[Any] = Field([], description="List of any additional errors")


def const_type(
    value: Any,
    description: str | None = None,
    **kwargs: Any,
) -> tuple[Any, Any]:
    return (Literal[value], Field(value, description=description, **kwargs))


ErrorDetailsType = type[ErrorDetails]


def create_error_model(
    status: int,
    type: str = "about:blank",
    name: str | None = None,
    title: str | None = None,
    detail: str | None = None,
    **kwargs: Any,
) -> type[ErrorDetails]:
    status_code = http.HTTPStatus(status)
    if title is None:
        title = status_code.phrase
    if name is None:
        name = title.replace(" ", "")
    if detail is None:
        detail = status_code.description
    __base__: ErrorDetailsType = kwargs.pop("__base__", ErrorDetails)
    return create_model(
        name,
        __base__=__base__,
        title=const_type(title, "Error title"),
        status=const_type(status, "Error status"),
        type=const_type(type, "Error type"),
        detail=(str, Field(detail, description="Error detail")),
        **kwargs,
    )
