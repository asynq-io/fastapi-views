from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from opentelemetry.sdk.resources import Resource
from starlette_exporter import PrometheusMiddleware

from fastapi_views import configure_app
from fastapi_views.config import (
    _collect_local_defs,
    custom_openapi,
    simplify_operation_ids,
)
from fastapi_views.i18n import LocaleMiddleware, NoTranslations
from fastapi_views.i18n import translations as translations_module
from fastapi_views.middlewares.structlog import RequestLoggingMiddleware


def test_configure_app(app):
    configure_app(app)


def test_configure_app_registers_prometheus_middleware_once(app):
    configure_app(app)
    assert sum(1 for m in app.user_middleware if m.cls is PrometheusMiddleware) == 1


def test_configure_app_enables_request_logging_when_structlog_installed(app):
    configure_app(app)
    assert any(m.cls is RequestLoggingMiddleware for m in app.user_middleware)


def test_configure_app_disables_request_logging_middleware(app):
    configure_app(app, enable_request_logging_middleware=False)
    assert all(m.cls is not RequestLoggingMiddleware for m in app.user_middleware)


def test_configure_app_rejects_middleware_and_exporter(app):
    with pytest.raises(ValueError, match="Only one prometheus exporter"):
        configure_app(app, prometheus_exporter_resource=Resource.create())


def test_configure_app_with_prometheus_exporter(app):
    configure_app(
        app,
        enable_prometheus_middleware=False,
        prometheus_exporter_resource=Resource.create(),
    )
    assert any(getattr(route, "path", None) == "/metrics" for route in app.routes)


def test_configure_app_with_translation_manager(app):
    manager = NoTranslations(default="en", supported_locales=["en"])
    original = translations_module._manager
    try:
        configure_app(app, translation_manager=manager)
    finally:
        translations_module._manager = original
    assert any(m.cls is LocaleMiddleware for m in app.user_middleware)


def test_collect_local_defs_moves_defs_to_components():
    schemas = {}
    node = {
        "content": {
            "schema": {
                "$defs": {"Item": {"type": "object"}},
                "$ref": "#/components/schemas/Item",
            }
        }
    }
    _collect_local_defs(node, schemas)
    assert schemas == {"Item": {"type": "object"}}
    assert "$defs" not in node["content"]["schema"]


def test_collect_local_defs_skips_identical_definition():
    schemas = {"Item": {"type": "object"}}
    _collect_local_defs({"$defs": {"Item": {"type": "object"}}}, schemas)
    assert schemas == {"Item": {"type": "object"}}


def test_collect_local_defs_keeps_first_definition_on_conflict(caplog):
    schemas = {"Item": {"type": "object"}}
    with caplog.at_level("WARNING"):
        _collect_local_defs({"$defs": {"Item": {"type": "string"}}}, schemas)
    assert schemas == {"Item": {"type": "object"}}
    assert "Conflicting OpenAPI schema definitions" in caplog.text


def test_simplify_operation_ids():
    app = FastAPI()

    @app.get("/hello")
    def hello_world():
        return {}

    simplify_operation_ids(app)
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name == "hello_world":
            assert route.operation_id == "hello_world"


def test_custom_openapi_removes_422():
    app = FastAPI()

    @app.post("/items")
    def create_item(name: str):
        return {"name": name}

    schema = custom_openapi(app)
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "responses" in operation:
                assert "422" not in operation["responses"]


def test_custom_openapi_caches():
    app = FastAPI()

    @app.get("/test")
    def test_route():
        return {}

    schema1 = custom_openapi(app)
    schema2 = custom_openapi(app)
    assert schema1 is schema2
