from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi.middleware.gzip import GZipMiddleware
from fastapi.routing import APIRoute

from .errors.handlers import add_error_handlers
from .opentelemetry import maybe_instrument_app
from .prometheus import add_prometheus_middleware

if TYPE_CHECKING:
    from fastapi import FastAPI


def simplify_operation_ids(app: FastAPI) -> None:
    """
    Simplify operation IDs so that generated clients have simpler api function names
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            route.operation_id = route.name.replace(" ", "")


def configure_app(
    app: FastAPI,
    enable_error_handlers: bool = True,
    enable_prometheus_middleware: bool = True,
    simplify_openapi_ids: bool = True,
    gzip_middleware_min_size: int | None = None,
    **tracing_options: Any,
) -> None:
    if enable_error_handlers:
        add_error_handlers(app)
    if enable_prometheus_middleware:
        add_prometheus_middleware(app)
    if simplify_openapi_ids:
        simplify_operation_ids(app)
    if gzip_middleware_min_size:
        app.add_middleware(GZipMiddleware, minimum_size=gzip_middleware_min_size)

    maybe_instrument_app(app, **tracing_options)
