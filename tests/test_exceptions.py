from __future__ import annotations

from typing import ClassVar

from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from fastapi_views.exceptions import (
    APIError,
    BadRequest,
    Conflict,
    Forbidden,
    InternalServerError,
    NotFound,
    Throttled,
    Unauthorized,
    Unavailable,
    UnprocessableEntity,
    _camel_to_title,
)
from fastapi_views.models import ErrorDetails


def test_camel_to_title_single_word():
    assert _camel_to_title("BadRequest") == "Bad Request"


def test_camel_to_title_multi_word():
    assert _camel_to_title("UserNotFound") == "User Not Found"


def test_camel_to_title_internal_server_error():
    assert _camel_to_title("InternalServerError") == "Internal Server Error"


def test_camel_to_title_no_change():
    assert _camel_to_title("Simple") == "Simple"


def test_api_error_default():
    err = APIError()
    assert err.status_code == HTTP_400_BAD_REQUEST


def test_api_error_with_detail():
    err = APIError("custom detail")
    model = err.as_model()
    assert model.detail == "custom detail"


def test_api_error_with_custom_status():
    err = APIError(status=404)
    assert err.status_code == HTTP_404_NOT_FOUND


def test_api_error_with_headers():
    err = BadRequest("detail", headers={"x-custom": "value"})
    assert err.headers == {"x-custom": "value"}


def test_api_error_headers_none():
    err = BadRequest("detail")
    assert err.headers is None


def test_api_error_get_status():
    assert NotFound.get_status() == HTTP_404_NOT_FOUND
    assert BadRequest.get_status() == HTTP_400_BAD_REQUEST
    assert Conflict.get_status() == HTTP_409_CONFLICT


def test_api_error_as_model_instance():
    err = BadRequest("some detail")
    model = err.as_model()
    assert isinstance(model, ErrorDetails)
    assert model.status == HTTP_400_BAD_REQUEST
    assert model.detail == "some detail"


def test_not_found():
    err = NotFound("not found detail")
    assert err.status_code == HTTP_404_NOT_FOUND
    model = err.as_model()
    assert model.title == "Not Found"


def test_conflict():
    err = Conflict("conflict detail")
    assert err.status_code == HTTP_409_CONFLICT
    model = err.as_model()
    assert model.title == "Conflict"


def test_unauthorized():
    err = Unauthorized("unauthorized detail")
    assert err.status_code == HTTP_401_UNAUTHORIZED
    model = err.as_model()
    assert model.status == HTTP_401_UNAUTHORIZED


def test_forbidden():
    err = Forbidden("forbidden detail")
    assert err.status_code == HTTP_403_FORBIDDEN


def test_throttled():
    err = Throttled()
    assert err.status_code == HTTP_429_TOO_MANY_REQUESTS
    model = err.as_model()
    assert model.title == "Too Many Requests"


def test_unprocessable_entity():
    err = UnprocessableEntity("entity detail")
    assert err.status_code == HTTP_422_UNPROCESSABLE_CONTENT


def test_internal_server_error():
    err = InternalServerError()
    assert err.status_code == HTTP_500_INTERNAL_SERVER_ERROR


def test_unavailable():
    err = Unavailable()
    assert err.status_code == HTTP_503_SERVICE_UNAVAILABLE
    model = err.as_model()
    assert model.title == "Service Unavailable"


def test_custom_exception_with_literal_field():
    class AppError(BadRequest):
        error_code: str = "APP_ERROR"

    err = AppError("app error")
    assert err.status_code == HTTP_400_BAD_REQUEST
    model = err.as_model()
    assert model.error_code == "APP_ERROR"


def test_custom_exception_with_required_field():
    class TraceError(BadRequest):
        trace_id: str

    err = TraceError("detail", trace_id="abc123")
    model = err.as_model()
    assert model.trace_id == "abc123"


def test_custom_exception_with_list_field():
    class MultiError(BadRequest):
        details: ClassVar[list] = []

    err = MultiError("multi error")
    model = err.as_model()
    assert model.details == []


def test_custom_exception_with_dict_field():
    class DictError(BadRequest):
        meta: ClassVar[dict] = {}

    err = DictError("dict error")
    model = err.as_model()
    assert model.meta == {}


def test_api_error_title_from_class_name():
    class UserNotFound(APIError):
        status = 404

    err = UserNotFound()
    model = err.as_model()
    assert model.title == "User Not Found"


def test_api_error_inherits_model():
    class SubNotFound(NotFound):
        pass

    err = SubNotFound("sub error")
    assert err.status_code == HTTP_404_NOT_FOUND
    model = err.as_model()
    # Subclass gets title from its own class name via _camel_to_title
    assert model.title == "Sub Not Found"


def test_api_error_type_from_rfc_map():
    err = NotFound("test")
    model = err.as_model()
    assert "rfc" in str(model.type).lower() or "rfc7231" in str(model.type)


def test_api_error_no_detail_in_kwargs():
    err = BadRequest()
    model = err.as_model()
    assert model.detail is not None


def test_custom_subclass_with_custom_title():
    class MyError(BadRequest):
        title = "My Custom Error"

    err = MyError()
    model = err.as_model()
    assert model.title == "My Custom Error"


def test_custom_subclass_with_custom_type():
    class MyError(BadRequest):
        type = "https://example.com/errors/my-error"

    err = MyError()
    model = err.as_model()
    assert "example.com" in str(model.type)


def test_exception_field_in_base_attrs_skipped():
    class MyError(BadRequest):
        detail: ClassVar[str] = "custom default"

    err = MyError()
    model = err.as_model()
    assert model is not None
