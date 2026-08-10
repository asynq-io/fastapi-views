from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from fastapi_views.models import (
    AnyServerSentEvent,
    BaseSchema,
    ErrorDetails,
    ErrorDetailsType,
)
from fastapi_views.models.streaming import (
    ResponseCancelled,
    ResponseError,
    ResponseEvent,
    ResponseFinished,
    ResponseResult,
    ResponseStarted,
    ResultData,
)


class Item(BaseSchema):
    id: int
    name: str


def test_response_started_new():
    event = ResponseStarted.new()
    assert event.event == "response.started"
    assert event.data.type == "response.started"
    assert isinstance(event.id, UUID)
    assert event.data.timestamp > 0


def test_response_result_new():
    event = ResponseResult.new(items=[{"a": 1}], index=2, total_results=10)
    assert event.event == "response.result"
    assert event.data.type == "response.result"
    assert event.data.items == [{"a": 1}]
    assert event.data.index == 2
    assert event.data.total_results == 10
    assert isinstance(event.id, UUID)


def test_response_result_new_defaults():
    event = ResponseResult.new(items=[])
    assert event.data.items == []
    assert event.data.index is None
    assert event.data.total_results is None


def test_parameterized_response_result_new_accepts_model_instances():
    items = [Item(id=1, name="first"), Item(id=2, name="second")]
    event = ResponseResult[Item].new(items=items, index=1, total_results=2)
    assert isinstance(event.data, ResultData)
    assert event.data.items == items
    assert all(isinstance(item, Item) for item in event.data.items)
    assert event.data.index == 1
    assert event.data.total_results == 2


def test_parameterized_response_result_new_round_trip():
    event = ResponseResult[Item].new(items=[Item(id=1, name="first")])
    dumped = event.model_dump()
    assert dumped["data"]["items"] == [{"id": 1, "name": "first"}]
    restored = ResponseResult[Item].model_validate(dumped)
    assert restored.data.items == [Item(id=1, name="first")]
    assert restored.id == event.id


def test_parameterized_response_result_new_coerces_dicts():
    event = ResponseResult[Item].new(items=[{"id": 3, "name": "third"}])
    assert event.data.items == [Item(id=3, name="third")]


def test_parameterized_response_result_new_rejects_invalid_items():
    with pytest.raises(ValidationError):
        ResponseResult[Item].new(items=[{"id": "not-an-int", "name": "x"}])


def test_unparameterized_response_result_new_still_accepts_dicts():
    event = ResponseResult.new(items=[{"a": 1}])
    assert event.data.items == [{"a": 1}]


def test_sibling_new_helpers_build_their_declared_payloads():
    assert isinstance(
        ResponseStarted.new().data,
        ResponseStarted.model_fields["data"].annotation,
    )
    assert isinstance(
        ResponseError.new("boom").data,
        ResponseError.model_fields["data"].annotation,
    )
    assert isinstance(
        ResponseFinished.new().data,
        ResponseFinished.model_fields["data"].annotation,
    )
    assert isinstance(
        ResponseCancelled.new().data,
        ResponseCancelled.model_fields["data"].annotation,
    )


def test_response_error_new():
    event = ResponseError.new("boom")
    assert event.event == "response.error"
    assert event.data.type == "response.error"
    assert event.data.error == "boom"
    assert isinstance(event.id, UUID)


def test_response_finished_accepts_zero_duration():
    event = ResponseFinished.new(duration_s=0)
    assert event.event == "response.finished"
    assert event.data.type == "response.finished"
    assert event.data.duration_s == 0
    assert event.data.timestamp > 0


def test_response_finished_duration_defaults_to_none():
    assert ResponseFinished.new().data.duration_s is None


def test_response_finished_rejects_negative_duration():
    with pytest.raises(ValidationError):
        ResponseFinished.new(duration_s=-1)


def test_response_cancelled_new():
    event = ResponseCancelled.new()
    assert event.event == "response.cancelled"
    assert event.data.type == "response.cancelled"
    assert isinstance(event.id, UUID)


def test_events_get_unique_auto_ids():
    assert ResponseStarted.new().id != ResponseStarted.new().id


def test_response_event_discriminated_union_round_trip():
    adapter = TypeAdapter(ResponseEvent)
    original = ResponseResult.new(items=[{"a": 1}], index=0)
    validated = adapter.validate_python(original.model_dump())
    assert isinstance(validated, ResponseResult)
    assert validated.id == original.id
    assert validated.data.items == [{"a": 1}]
    assert validated.data.index == 0


def test_any_server_sent_event_generates_id():
    event = AnyServerSentEvent(event="tick", data={"x": 1})
    assert isinstance(event.id, str)
    parsed = UUID(event.id)
    assert str(parsed) == event.id


def test_error_details_type_is_reexported_from_models():
    assert ErrorDetailsType == type[ErrorDetails]
