from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from typing_extensions import NotRequired

from .handlers import add_error_handlers
from .middlewares import RequestLimitMiddleware
from .opentelemetry import maybe_instrument_app
from .prometheus import add_prometheus_middleware

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .i18n.translations import TranslationManager


def simplify_operation_ids(app: FastAPI) -> None:
    """Simplify operation IDs so that generated clients have simpler api function names"""
    for route in app.routes:
        if isinstance(route, APIRoute):
            route.operation_id = route.name.replace(" ", "")


def custom_openapi(self: FastAPI) -> dict[str, Any]:
    if not self.openapi_schema:
        self.openapi_schema = get_openapi(
            title=self.title,
            version=self.version,
            openapi_version=self.openapi_version,
            description=self.description,
            terms_of_service=self.terms_of_service,
            contact=self.contact,
            license_info=self.license_info,
            routes=self.routes,
            tags=self.openapi_tags,
            servers=self.servers,
        )
        for method_item in self.openapi_schema.get("paths", {}).values():
            for param in method_item.values():
                responses = param.get("responses")
                if "422" in responses:
                    del responses["422"]
        schemas = self.openapi_schema.get("components", {}).get("schemas", {})
        for k in ("ValidationError", "HTTPValidationError"):
            if k in schemas:
                del schemas[k]

    return self.openapi_schema


class LogConfig(TypedDict):
    log_format: Literal["console", "json"]
    log_level: NotRequired[int]


def configure_app(  # noqa: PLR0913
    app: FastAPI,
    *,
    enable_error_handlers: bool = True,
    enable_prometheus_middleware: bool = True,
    simplify_openapi_ids: bool = True,
    gzip_middleware_min_size: int | None = 500,
    translation_manager: TranslationManager | None = None,
    limits: int | None = 1000,
    log_config: LogConfig | None = None,
    **tracing_options: Any,
) -> None:
    maybe_instrument_app(app, **tracing_options)
    if enable_error_handlers:
        add_error_handlers(app)
        app.__setattr__("openapi", functools.partial(custom_openapi, app))
    if enable_prometheus_middleware:
        add_prometheus_middleware(app)
    if simplify_openapi_ids:
        simplify_operation_ids(app)
    if gzip_middleware_min_size:
        app.add_middleware(GZipMiddleware, minimum_size=gzip_middleware_min_size)
    if translation_manager:
        from .i18n import LocaleMiddleware, configure_translations

        configure_translations(translation_manager)
        app.add_middleware(LocaleMiddleware, translation_manager)

    if limits:
        app.add_middleware(RequestLimitMiddleware, limits)
    if log_config:
        from .logging import RequestLoggingMiddleware, configure_logging

        log_config.setdefault("log_level", logging.INFO)
        configure_logging(**log_config)
        app.add_middleware(RequestLoggingMiddleware)
