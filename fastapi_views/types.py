from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Literal, TypedDict, TypeVar

if TYPE_CHECKING:
    from collections.abc import Sequence
    from enum import Enum

    from fastapi import Response, params
    from fastapi.routing import APIRoute
    from pydantic.main import IncEx
    from starlette.routing import BaseRoute

Entity = TypeVar("Entity", bound=Any)
Action = Literal[
    "create", "list", "retrieve", "update", "destroy", "partial_update", "events"
]


class SerializerOptions(TypedDict, total=False):
    include: IncEx | None
    exclude: IncEx | None
    by_alias: bool
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    round_trip: bool
    warnings: bool


class BaseRouteOptions(TypedDict, total=False):
    response_model: Any
    status_code: int
    tags: list[str | Enum] | None
    dependencies: Sequence[params.Depends] | None
    summary: str | None
    description: str | None
    response_description: str
    responses: dict[int | str, dict[str, Any]] | None
    deprecated: bool | None
    operation_id: str | None
    response_model_include: IncEx | None
    response_model_exclude: IncEx | None
    response_model_by_alias: bool
    response_model_exclude_unset: bool
    response_model_exclude_defaults: bool
    response_model_exclude_none: bool
    include_in_schema: bool
    response_class: type[Response]
    name: str | None
    callbacks: list[BaseRoute] | None
    openapi_extra: dict[str, Any] | None
    generate_unique_id_function: Callable[[APIRoute], str]


class RouteOptions(BaseRouteOptions, total=False):
    methods: list[str] | None


class PathRouteOptions(RouteOptions, total=False):
    path: str
