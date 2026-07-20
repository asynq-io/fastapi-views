from typing import Any, Generic

from typing_extensions import TypeVar

from .base import OpenAPIBase

ID = TypeVar("ID", default=str)
Event = TypeVar("Event", bound=str, default=str)
Data = TypeVar("Data", default=Any)


class ServerSentEvent(OpenAPIBase, Generic[ID, Event, Data]):
    """Generic Server-Sent Event model.

    Fully customizable via the `ID`, `Event` and `Data` type parameters,
    e.g. `ServerSentEvent[UUID, Literal["my.event"], MyModel]`.
    If `event` is not provided but `data` carries a `type` attribute (or key),
    the event name is derived from it; it can always be set explicitly.
    """

    __content_type__ = "text/event-stream"

    id: ID
    event: Event
    data: Data
    retry: int | None = None


class AnyServerSideEvent(ServerSentEvent[str, str, Any]):
    pass
