from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


def test_has_opentelemetry_import_error():
    from fastapi_views import opentelemetry

    with patch.dict(sys.modules, {"opentelemetry.instrumentation.fastapi": None}):
        import importlib

        importlib.reload(opentelemetry)
    # Restore
    importlib.reload(opentelemetry)


def test_has_opentelemetry_returns_false():
    from fastapi_views.opentelemetry import has_opentelemetry

    with patch.dict(sys.modules, {"opentelemetry.instrumentation.fastapi": None}):
        result = has_opentelemetry()
    assert result is False


def test_maybe_instrument_app_import_error():
    from fastapi_views.opentelemetry import maybe_instrument_app

    app = MagicMock()

    with patch("builtins.__import__", side_effect=ImportError):
        maybe_instrument_app(app)
        # Should not raise; ImportError is caught
