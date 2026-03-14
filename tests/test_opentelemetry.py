from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from fastapi_views import opentelemetry
from fastapi_views.opentelemetry import (
    has_opentelemetry,
    maybe_instrument_app,
)


def test_has_opentelemetry_import_error():
    with patch.dict(sys.modules, {"opentelemetry.instrumentation.fastapi": None}):
        importlib.reload(opentelemetry)
    # Restore
    importlib.reload(opentelemetry)


def test_has_opentelemetry_returns_false():
    with patch.dict(sys.modules, {"opentelemetry.instrumentation.fastapi": None}):
        result = has_opentelemetry()
    assert result is False


def test_maybe_instrument_app_import_error():
    app = MagicMock()

    with patch("builtins.__import__", side_effect=ImportError):
        maybe_instrument_app(app)
        # Should not raise; ImportError is caught


def test_server_request_hook_sets_correlation_id():
    provider = TracerProvider()
    trace.set_tracer_provider(provider)

    captured_hook = {}

    class FakeInstrumentor:
        @staticmethod
        def instrument_app(_app, **options) -> None:
            captured_hook["hook"] = options.get("server_request_hook")

    with patch(
        "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor", FakeInstrumentor
    ):
        maybe_instrument_app(MagicMock())

    hook = captured_hook["hook"]
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test-span") as span:
        hook(span, {})
        assert opentelemetry.CORRELATION_ID.get() is not None
        assert len(opentelemetry.CORRELATION_ID.get()) == 32


def test_server_request_hook_skips_non_recording_span():
    captured_hook = {}

    class FakeInstrumentor:
        @staticmethod
        def instrument_app(_app, **options) -> None:
            captured_hook["hook"] = options.get("server_request_hook")

    with patch(
        "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor", FakeInstrumentor
    ):
        maybe_instrument_app(MagicMock())

    hook = captured_hook["hook"]
    opentelemetry.CORRELATION_ID.set(None)
    non_recording_span = MagicMock()
    non_recording_span.is_recording.return_value = False
    hook(non_recording_span, {})
    assert opentelemetry.CORRELATION_ID.get() is None
