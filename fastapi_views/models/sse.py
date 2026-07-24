from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from .base import OpenAPIBase


class BaseServerSentEvent(OpenAPIBase):
    __content_type__ = "text/event-stream"

    retry: int | None = None


class IdBaseServerSentEvent(BaseServerSentEvent):
    id: UUID = Field(default_factory=uuid4)


class AnyServerSentEvent(BaseServerSentEvent):
    id: str
    event: str
    data: Any
