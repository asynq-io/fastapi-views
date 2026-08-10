from __future__ import annotations

import pytest
from starlette.datastructures import Headers

from fastapi_views.headers import (
    DEFAULT_REQUEST_HEADER_FILTER,
    DEFAULT_RESPONSE_HEADER_FILTER,
    HeaderFilter,
)


@pytest.mark.parametrize(
    "name",
    [
        "authorization",
        "proxy-authorization",
        "cookie",
        "x-api-key",
        "x-auth-token",
    ],
)
def test_default_request_filter_drops_credentials(name):
    headers = Headers({name: "secret", "user-agent": "pytest"})
    assert DEFAULT_REQUEST_HEADER_FILTER(headers) == {"user_agent": "pytest"}


def test_default_response_filter_drops_set_cookie():
    headers = Headers({"set-cookie": "session=secret", "vary": "origin"})
    assert DEFAULT_RESPONSE_HEADER_FILTER(headers) == {"vary": "origin"}


def test_filter_normalizes_names_to_snake_case():
    header_filter = HeaderFilter({"X-Forwarded-For"})
    assert header_filter(Headers({"X-Forwarded-For": "10.0.0.1"})) == {
        "x_forwarded_for": "10.0.0.1"
    }


def test_filter_raw_decodes_asgi_headers():
    header_filter = HeaderFilter({"content-type"})
    raw = [(b"Content-Type", b"application/json"), (b"authorization", b"Bearer token")]
    assert header_filter.filter_raw(raw) == {"content_type": "application/json"}


def test_empty_filter_drops_everything():
    assert HeaderFilter(())(Headers({"host": "test"})) == {}
