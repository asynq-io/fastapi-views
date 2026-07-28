from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from fastapi_views.models import AnyServerSentEvent, ErrorDetails, ErrorDetailsType
from fastapi_views.models.streaming import (
    ResponseCancelled,
    ResponseError,
    ResponseEvent,
    ResponseFinished,
    ResponseResult,
    ResponseStarted,
)


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
