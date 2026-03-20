from __future__ import annotations

from fastapi_views.pagination import decode_cursor, encode_cursor


def test_encode_cursor():
    encoded = encode_cursor("hello")
    assert isinstance(encoded, str)
    assert encoded != "hello"


def test_decode_cursor_valid():
    encoded = encode_cursor("hello")
    assert decode_cursor(encoded) == "hello"


def test_decode_cursor_invalid_falls_back():
    result = decode_cursor("not-valid-base64!!!")
    assert result == "not-valid-base64!!!"
