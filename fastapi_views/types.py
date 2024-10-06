from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Literal, Protocol, TypedDict, TypeVar

from typing_extensions import ParamSpec

if TYPE_CHECKING:
    from pydantic.type_adapter import IncEx

Entity = TypeVar("Entity", bound=Any)
Action = Literal["create", "list", "retrieve", "update", "destroy", "partial_update"]

P = ParamSpec("P")
F = Callable[[P.args, P.kwargs], Any]


class SerializerOptions(TypedDict, total=False):
    validate: bool
    from_attributes: bool | Literal["auto"]
    indent: int | None
    include: IncEx | None
    exclude: IncEx | None
    by_alias: bool
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    round_trip: bool
    warnings: bool


class Repository(Protocol[Entity]):
    def retrieve(self, *args: Any, **kwargs: Any) -> Entity | None: ...

    def create(self, entity: Entity, **kwargs: Any) -> Entity | None: ...

    def update(self, entity: Entity, **kwargs: Any) -> Entity | None: ...

    def delete(self, *args: Any, **kwargs: Any) -> None: ...

    def list(self, *args: Any, **kwargs: Any) -> list[Entity]: ...


class AsyncRepository(Protocol[Entity]):
    async def retrieve(self, *args: Any, **kwargs: Any) -> Entity | None: ...

    async def create(self, entity: Entity, **kwargs: Any) -> Entity | None: ...

    async def update(self, entity: Entity, **kwargs: Any) -> Entity | None: ...

    async def delete(self, *args: Any, **kwargs: Any) -> None: ...

    async def list(self, *args: Any, **kwargs: Any) -> list[Entity]: ...
