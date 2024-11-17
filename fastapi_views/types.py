from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Literal, TypedDict, TypeVar

from typing_extensions import ParamSpec

if TYPE_CHECKING:
    from pydantic.main import IncEx

Entity = TypeVar("Entity", bound=Any)
Action = Literal["create", "list", "retrieve", "update", "destroy", "partial_update"]

P = ParamSpec("P")
F = Callable[[P.args, P.kwargs], Any]


class SerializerOptions(TypedDict, total=False):
    indent: int | None
    include: IncEx | None
    exclude: IncEx | None
    by_alias: bool
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    round_trip: bool
    warnings: bool
