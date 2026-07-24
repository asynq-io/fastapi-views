"""
Universal responses schemas for streaming results,
for example with SSE, loosely inspired by OpenAI responses API
"""

from abc import abstractmethod
from datetime import datetime, timezone
from typing import Annotated, Any, Generic, Literal

from pydantic import Field, PositiveInt
from typing_extensions import Self, TypeAliasType, TypeVar

from .base import BaseSchema
from .sse import IdBaseServerSentEvent

T = TypeVar("T", default=dict[str, Any])


def timestamp() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


class _BaseEvent(IdBaseServerSentEvent):
    @classmethod
    @abstractmethod
    def new(cls, *args: Any, **kwargs: Any) -> Self:
        raise NotImplementedError


class TimestampData(BaseSchema):
    timestamp: int = Field(default_factory=timestamp, description="UTC timestamp")


class StartedData(TimestampData):
    type: Literal["response.started"] = "response.started"


class ResponseStarted(_BaseEvent):
    event: Literal["response.started"] = "response.started"
    data: StartedData

    @classmethod
    def new(cls) -> Self:
        return cls(data=StartedData())


class ErrorData(BaseSchema):
    type: Literal["response.error"] = "response.error"
    error: str


class ResponseError(_BaseEvent):
    event: Literal["response.error"] = "response.error"
    data: ErrorData

    @classmethod
    def new(cls, error: str) -> Self:
        return cls(data=ErrorData(error=error))


class ResultData(BaseSchema, Generic[T]):
    type: Literal["response.result"] = "response.result"
    items: list[T] = Field(description="List of results")
    index: int | None = Field(None, description="Optional result index (page number)")
    total_results: int | None = Field(
        None, description="Optional total number of results to expect"
    )


class ResponseResult(_BaseEvent, Generic[T]):
    event: Literal["response.result"] = "response.result"
    data: ResultData[T]

    @classmethod
    def new(
        cls,
        items: list[T],
        *,
        index: int | None = None,
        total_results: int | None = None,
    ) -> Self:
        return cls.model_validate(
            {"data": {"items": items, "index": index, "total_results": total_results}}
        )


class FinishedData(TimestampData):
    type: Literal["response.finished"] = "response.finished"
    duration_s: PositiveInt | None = Field(
        None, description="Optional duration in seconds"
    )


class ResponseFinished(_BaseEvent):
    event: Literal["response.finished"] = "response.finished"
    data: FinishedData

    @classmethod
    def new(cls, duration_s: int | None = None) -> Self:
        return cls(data=FinishedData(duration_s=duration_s))


class CancelledData(TimestampData):
    type: Literal["response.cancelled"] = "response.cancelled"


class ResponseCancelled(_BaseEvent):
    event: Literal["response.cancelled"] = "response.cancelled"
    data: CancelledData

    @classmethod
    def new(cls) -> Self:
        return cls(data=CancelledData())


ResponseEvent = TypeAliasType(
    "ResponseEvent",
    Annotated[
        ResponseStarted
        | ResponseResult[T]
        | ResponseError
        | ResponseCancelled
        | ResponseFinished,
        Field(discriminator="event"),
    ],
    type_params=(T,),
)
