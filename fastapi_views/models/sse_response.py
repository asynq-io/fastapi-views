"""
Universal responses schemas for streaming results,
for example with SSE, loosely inspired by OpenAI responses API
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Generic, Literal
from uuid import UUID, uuid4

from pydantic import Field, PositiveInt
from typing_extensions import (
    NotRequired,
    Self,
    TypeAliasType,
    TypedDict,
    TypeVar,
    Unpack,
)

from .base import BaseSchema
from .sse import ServerSentEvent

Item = TypeVar("Item", default=dict[str, Any])


def now_utc_timestamp() -> int:
    return int(datetime.now(timezone.utc).timestamp())


class ResponseStarted(BaseSchema):
    type: Literal["response.started"] = "response.started"
    timestamp: int = Field(
        default_factory=now_utc_timestamp, description="UTC timestamp"
    )


class ResponseError(BaseSchema):
    type: Literal["response.error"] = "response.error"
    error: str = Field(description="Error detail")


class ResponsePage(BaseSchema, Generic[Item]):
    type: Literal["response.result_page"] = "response.result_page"
    items: list[Item] = Field(description="Page items")
    page: PositiveInt = Field(description="Page number")
    total_pages: PositiveInt | None = Field(None, description="Optional total pages")


class ResponseResult(BaseSchema, Generic[Item]):
    type: Literal["response.result"] = "response.result"
    items: list[Item] = Field(description="Response items")


class ResponseFinished(BaseSchema):
    type: Literal["response.finished"] = "response.finished"
    timestamp: int = Field(
        default_factory=now_utc_timestamp, description="UTC timestamp"
    )
    duration_s: PositiveInt | None = Field(
        None, description="Optional duration in seconds"
    )


ResponseType = Literal[
    "response.started",
    "response.error",
    "response.result_page",
    "response.result",
    "response.finished",
]

ResponseData = TypeAliasType(
    "ResponseData",
    Annotated[
        ResponseStarted
        | ResponsePage[Item]
        | ResponseResult[Item]
        | ResponseError
        | ResponseFinished,
        Field(discriminator="type"),
    ],
    type_params=(Item,),
)


class Extra(TypedDict):
    id: NotRequired[UUID]
    retry: NotRequired[int | None]


class ResponseEvent(
    ServerSentEvent[UUID, ResponseType, ResponseData[Item]], Generic[Item]
):
    """Typed SSE for streaming responses.

    Use `new` or the per-type factories to build events
    with `event` derived from `data.type`.
    """

    id: UUID = Field(default_factory=uuid4)
    event: ResponseType = Field(
        description="Response event type, specifies `data` type",
    )
    data: ResponseData[Item] = Field(
        description="Event data in JSON format, determined by `event` property"
    )

    @classmethod
    def new(cls, data: ResponseData[Item], **kwargs: Unpack[Extra]) -> Self:
        return cls(event=data.type, data=data, **kwargs)

    @classmethod
    def error(cls, error: str, **kwargs: Unpack[Extra]) -> Self:
        return cls.new(ResponseError(error=error), **kwargs)

    @classmethod
    def page(
        cls,
        items: list[Item],
        *,
        page: PositiveInt = 1,
        total_pages: PositiveInt | None = None,
        **kwargs: Unpack[Extra],
    ) -> Self:
        data = ResponsePage[Any](items=items, page=page, total_pages=total_pages)
        return cls.new(data, **kwargs)

    @classmethod
    def result(cls, items: list[Item], **kwargs: Unpack[Extra]) -> Self:
        return cls.new(ResponseResult[Any](items=items), **kwargs)

    @classmethod
    def started(cls, **kwargs: Unpack[Extra]) -> Self:
        return cls.new(ResponseStarted(), **kwargs)

    @classmethod
    def finished(
        cls,
        duration_s: PositiveInt | None = None,
        **kwargs: Unpack[Extra],
    ) -> Self:
        return cls.new(ResponseFinished(duration_s=duration_s), **kwargs)
