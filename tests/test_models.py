from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.status import HTTP_400_BAD_REQUEST

from fastapi_views.models import (
    AnyServerSideEvent,
    BaseSchema,
    CamelCaseSchema,
    ErrorDetails,
    IdSchema,
    ServerSentEvent,
    const_type,
    create_error_model,
)


def test_base_schema_from_attributes():
    class MyModel:
        x = "hello"

    class MySchema(BaseSchema):
        x: str

    obj = MySchema.model_validate(MyModel(), from_attributes=True)
    assert obj.x == "hello"


def test_base_schema_populate_by_name():
    class MySchema(BaseSchema):
        my_field: str

    # Can populate by field name
    obj = MySchema(my_field="test")
    assert obj.my_field == "test"


def test_camel_case_schema():
    class MySchema(CamelCaseSchema):
        my_field: str

    obj = MySchema(my_field="test")
    data = obj.model_dump(by_alias=True)
    assert "myField" in data


def test_id_schema():
    item_id = uuid4()
    obj = IdSchema(id=item_id)
    assert obj.id == item_id


def test_id_schema_validation():
    with pytest.raises(ValidationError):
        IdSchema(id="not-a-uuid")


def test_server_sent_event_defaults():
    event = ServerSentEvent(event="test", data={"key": "value"})
    assert event.event == "test"
    assert event.data == {"key": "value"}
    assert event.retry is None
    assert isinstance(event.id, str)


def test_server_sent_event_with_retry():
    event = ServerSentEvent(event="test", data="data", retry=5000)
    assert event.retry == 5000


def test_server_sent_event_get_openapi_schema_no_title():
    schema = ServerSentEvent.get_openapi_schema()
    assert "title" in schema
    assert "$defs" not in schema


def test_server_sent_event_get_openapi_schema_with_title():
    schema = ServerSentEvent.get_openapi_schema(title="CustomSSE")
    assert schema["title"] == "CustomSSE"


def test_server_sent_event_typed_get_openapi_schema():
    class DummyData(BaseSchema):
        value: int

    schema = ServerSentEvent[DummyData].get_openapi_schema(title="DummySSE")
    assert schema["title"] == "DummySSE"


def test_any_server_side_event():
    event = AnyServerSideEvent(event="test", data={"x": 1})
    assert event.event == "test"


def test_error_details_new():
    details = ErrorDetails.new("test detail", title="Test", status=HTTP_400_BAD_REQUEST)
    assert details.detail == "test detail"
    assert details.title == "Test"
    assert details.status == HTTP_400_BAD_REQUEST


def test_error_details_type_default():
    details = ErrorDetails(title="Test", status=400, detail="detail")
    assert details.type == "about:blank"


def test_const_type():
    annotation, _field = const_type("test_value", "test description")
    assert annotation.__args__[0] == "test_value"


def test_const_type_no_description():
    annotation, _field = const_type(42)
    assert annotation.__args__[0] == 42


def test_create_error_model_defaults():
    model = create_error_model(404)
    assert model.__name__ == "NotFound"


def test_create_error_model_custom_name():
    model = create_error_model(400, name="CustomBadRequest")
    assert model.__name__ == "CustomBadRequest"


def test_create_error_model_custom_title():
    model = create_error_model(400, title="My Custom Error")
    instance = model(detail="test")
    assert instance.title == "My Custom Error"


def test_create_error_model_custom_detail():
    model = create_error_model(400, detail="Custom default detail")
    instance = model()
    assert instance.detail == "Custom default detail"


def test_create_error_model_with_type():
    model = create_error_model(400, type="https://example.com/errors/bad")
    instance = model(detail="test")
    assert "example.com" in str(instance.type)


def test_create_error_model_extra_kwargs():
    model = create_error_model(
        400,
        name="ExtendedError",
        extra_field=(str, "default value"),
    )
    assert model.__name__ == "ExtendedError"
