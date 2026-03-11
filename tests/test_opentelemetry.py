from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

from fastapi_views import opentelemetry
from fastapi_views.opentelemetry import has_opentelemetry, maybe_instrument_app


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
