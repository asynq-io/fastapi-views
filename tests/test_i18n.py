from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from fastapi_views.exceptions import NotFound
from fastapi_views.handlers import api_error_handler
from fastapi_views.i18n import (
    InMemoryTranslations,
    LocaleMiddleware,
    NoTranslations,
    configure_translations,
    get_locale,
    override_locale,
    translate,
)
from fastapi_views.i18n import translations as translations_module
from fastapi_views.i18n.formatter import StrFormatter
from fastapi_views.i18n.jinja2 import JinjaFormatter

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_manager() -> Iterator[None]:
    """Keep the module-level translation manager isolated per test."""
    original = translations_module._manager
    try:
        yield
    finally:
        translations_module._manager = original


@pytest.mark.parametrize(
    ("fallbacks", "expected"),
    [
        (None, {}),
        ({}, {}),
        ({"de-AT": "de"}, {"de-AT": ("de",)}),
        ({"de-AT": ["de", "de-DE"]}, {"de-AT": ("de", "de-DE")}),
        (
            {("pt-BR", "pt-PT"): "pt"},
            {"pt-BR": ("pt",), "pt-PT": ("pt",)},
        ),
        (
            {("pt-BR", "pt-PT"): ["pt", "es"]},
            {"pt-BR": ("pt", "es"), "pt-PT": ("pt", "es")},
        ),
    ],
)
def test_normalize_fallbacks(
    fallbacks: Any, expected: dict[str, tuple[str, ...]]
) -> None:
    manager = NoTranslations(default="en", fallbacks=fallbacks)
    assert manager.fallbacks == expected


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        # configured fallback, then default appended
        ("de-AT", ("de-AT", "de", "en")),
        # no configured fallback: locale then default
        ("fr", ("fr", "en")),
        # default itself: no duplication
        ("en", ("en",)),
    ],
)
def test_get_fallback_chain(locale: str, expected: tuple[str, ...]) -> None:
    manager = NoTranslations(
        default="en",
        supported_locales=["en", "de", "de-AT", "fr"],
        fallbacks={"de-AT": "de"},
    )
    assert manager.get_fallback_chain(locale) == expected


def test_fallback_chain_dedupes_and_keeps_order() -> None:
    manager = NoTranslations(
        default="en",
        supported_locales=["en", "de", "de-AT"],
        fallbacks={"de-AT": ["de", "de", "en", "de-AT"]},
    )
    assert manager.get_fallback_chain("de-AT") == ("de-AT", "de", "en")


def test_supported_locale_chains_are_precomputed() -> None:
    manager = NoTranslations(
        default="en",
        supported_locales=["en", "de-AT"],
        fallbacks={"de-AT": "de"},
    )
    assert set(manager._fallback_chains) == {"en", "de-AT"}


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("de", "de"),  # exact supported
        ("gsw", "de"),  # configured fallback (subtag would not help)
        ("de-CH", "de"),  # subtag stripping
        ("fr", None),  # nothing matches
    ],
)
def test_match_supported(tag: str, expected: str | None) -> None:
    manager = NoTranslations(
        default="en",
        supported_locales=["en", "de"],
        fallbacks={"de-AT": ["de"], "gsw": ["de"]},
    )
    assert manager.match_supported(tag) == expected


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("de", "Hallo"),  # present in requested locale
        ("de-AT", "Hallo"),  # falls back to "de"
        ("pl", "Hello"),  # falls back to default "en"
    ],
)
def test_format_key_walks_fallback_chain(locale: str, expected: str) -> None:
    manager = InMemoryTranslations(
        {"en": {"greeting": "Hello"}, "de": {"greeting": "Hallo"}},
        default="en",
        supported_locales=["en", "de", "de-AT", "pl"],
        fallbacks={"de-AT": "de"},
    )
    assert manager.format_key("greeting", locale=locale) == expected


def test_format_key_missing_everywhere_degrades_to_key_tail() -> None:
    manager = InMemoryTranslations(
        {"en": {}},
        default="en",
        supported_locales=["en"],
    )
    assert manager.format_key("errors.not_found") == "not_found"


@pytest.fixture
def empty_manager() -> InMemoryTranslations:
    return InMemoryTranslations({"en": {}}, default="en", supported_locales=["en"])


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("errors.not_found", "not_found"),
        ("errors.http.not-found", "not-found"),
        ("errors._private", "_private"),
        ("błędy.nie_znaleziono", "nie_znaleziono"),
    ],
)
def test_missing_dotted_key_degrades_to_tail(
    empty_manager: InMemoryTranslations, key: str, expected: str
) -> None:
    assert empty_manager.format_key(key) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Item not found.",
        "3.5 items",
        "Item does not exist",
        "errors.not found",
        "Requires version 1.2 or newer.",
        "...",
        "Failed. Try again.",
    ],
)
def test_missing_free_text_is_returned_unchanged(
    empty_manager: InMemoryTranslations, text: str
) -> None:
    assert empty_manager.format_key(text) == text


def test_translate_free_text_with_period_survives() -> None:
    configure_translations(
        InMemoryTranslations({"en": {}}, default="en", supported_locales=["en"])
    )
    assert translate("Item not found.") == "Item not found."
    assert translate("3.5 items") == "3.5 items"


def test_api_error_detail_with_period_survives_handler_round_trip() -> None:
    configure_translations(
        InMemoryTranslations(
            {"en": {}},
            default="en",
            supported_locales=["en"],
            formatter=StrFormatter(),
        )
    )
    request = MagicMock()
    request.url.path = "/items/1"

    response = api_error_handler(request, NotFound("Item not found."))

    assert json.loads(bytes(response.body))["detail"] == "Item not found."


def test_format_key_rejects_unsupported_locale() -> None:
    manager = InMemoryTranslations({"en": {}}, default="en", supported_locales=["en"])
    with pytest.raises(ValueError, match="Unsupported locale"):
        manager.format_key("greeting", locale="zz")


def test_default_must_be_supported() -> None:
    with pytest.raises(ValueError, match="not supported"):
        InMemoryTranslations({}, default="en", supported_locales=["pl"])


def test_translate_uses_current_locale() -> None:
    configure_translations(
        InMemoryTranslations(
            {"en": {"greeting": "Hello"}, "pl": {"greeting": "Cześć"}},
            default="en",
            supported_locales=["en", "pl"],
        )
    )
    with override_locale("pl"):
        assert translate("greeting") == "Cześć"
    assert translate("greeting") == "Hello"


class _LocaleRecordingFormatter:
    def format(self, text: str, **kwargs: Any) -> str:
        return f"{text}:{get_locale()}"


def test_explicit_locale_reaches_the_formatter() -> None:
    configure_translations(
        InMemoryTranslations(
            {"en": {"greeting": "Hello"}, "pl": {"greeting": "Cześć"}},
            default="en",
            supported_locales=["en", "pl"],
            formatter=_LocaleRecordingFormatter(),
        )
    )
    manager = translations_module.get_manager()
    assert manager.format_key("greeting", locale="pl") == "Cześć:pl"
    assert manager.format_key("greeting") == "Hello:en"


def test_explicit_locale_does_not_leak_after_formatting() -> None:
    configure_translations(
        InMemoryTranslations(
            {"en": {"greeting": "Hello"}, "pl": {"greeting": "Cześć"}},
            default="en",
            supported_locales=["en", "pl"],
            formatter=_LocaleRecordingFormatter(),
        )
    )
    assert translate("greeting", locale="pl") == "Cześć:pl"
    assert get_locale() == "en"


def test_explicit_locale_governs_babel_interpolation() -> None:
    configure_translations(
        InMemoryTranslations(
            {"en": {"n": "{{ v | number }}"}},
            default="en",
            supported_locales=["en", "pl"],
            formatter=JinjaFormatter(),
        )
    )
    assert translate("n", locale="pl", v=1234.5) == "1\xa0234,5"
    assert translate("n", v=1234.5) == "1,234.5"
    with override_locale("pl"):
        assert translate("n", v=1234.5) == "1\xa0234,5"


def _make_request(
    query: str = "",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        cookie = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie.encode()))
    return Request(
        {"type": "http", "query_string": query.encode(), "headers": raw_headers}
    )


@pytest.fixture
def middleware() -> LocaleMiddleware:
    manager = NoTranslations(
        default="en",
        supported_locales=["en", "de"],
        fallbacks={"de-AT": ["de"], "gsw": ["de"]},
    )
    return LocaleMiddleware(app=None, manager=manager)  # type: ignore[arg-type]


def test_detect_uses_fallback_from_header(middleware: LocaleMiddleware) -> None:
    request = _make_request(headers={"Accept-Language": "gsw, fr;q=0.5"})
    assert middleware._detect_best_locale(request) == ("de", False)


def test_detect_fallback_of_higher_q_beats_direct_lower_q(
    middleware: LocaleMiddleware,
) -> None:
    # gsw (q=1.0) resolves to "de" via the configured fallback and wins over the
    # directly-supported "en" (q=0.8): a fallback inherits its trigger's priority.
    request = _make_request(headers={"Accept-Language": "gsw, en;q=0.8"})
    assert middleware._detect_best_locale(request) == ("de", False)


def test_detect_query_param_resolves_and_sets_cookie(
    middleware: LocaleMiddleware,
) -> None:
    request = _make_request(query="lang=gsw")
    assert middleware._detect_best_locale(request) == ("de", True)


def test_detect_falls_back_to_default(middleware: LocaleMiddleware) -> None:
    request = _make_request(headers={"Accept-Language": "fr, es"})
    assert middleware._detect_best_locale(request) == ("en", False)


def test_detect_prefers_query_over_cookie(middleware: LocaleMiddleware) -> None:
    request = _make_request(query="lang=de", cookies={"locale": "en"})
    assert middleware._detect_best_locale(request) == ("de", True)
