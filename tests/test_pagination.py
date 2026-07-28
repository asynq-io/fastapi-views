from __future__ import annotations

from fastapi_views.pagination import TokenPage, decode_cursor, encode_cursor


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


def test_token_page_cursor_defaults_to_none():
    page = TokenPage(items=[])
    assert page.cursor is None
    assert page.model_dump(mode="json")["cursor"] is None


def test_token_page_cursor_base64_encoded_like_next_page():
    page = TokenPage(items=[], cursor="abc", next_page="abc")
    dumped = page.model_dump(mode="json")
    assert dumped["cursor"] == encode_cursor("abc")
    assert dumped["cursor"] == dumped["next_page"]
