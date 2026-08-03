import http
from typing import Any, Literal

from pydantic import (
    Field,
    create_model,
)
from pydantic_core import Url
from typing_extensions import Self

from fastapi_views.opentelemetry import OPENTELEMETRY_INSTALLED, get_correlation_id

from .base import OpenAPIBase


class ErrorDetails(OpenAPIBase):
    """Base Model for https://www.rfc-editor.org/rfc/rfc9457.html"""

    __content_type__ = "application/problem+json"

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
