from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any

from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from .handlers import add_error_handlers
from .headers import DEFAULT_REQUEST_HEADER_FILTER, HeaderFilter
from .opentelemetry import maybe_instrument_app
from .prometheus import add_prometheus_exporter, add_prometheus_middleware

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.resources import Resource

    from .i18n.translations import TranslationManager

logger = logging.getLogger(__name__)


def simplify_operation_ids(app: FastAPI) -> None:
    """Simplify operation IDs so that generated clients have simpler api function names"""
    for route in app.routes:
        if isinstance(route, APIRoute):
            route.operation_id = route.name.replace(" ", "")


def _collect_local_defs(node: Any, schemas: dict[str, Any]) -> None:
    """Move `$defs` of hand-authored content schemas into components.

    Schemas passed directly as OpenAPI response content (e.g. SSE events)
    are opaque to FastAPI, so the models they reference are never registered
    in `components/schemas`. Their definitions travel in `$defs` instead
    and are relocated here to make the references resolvable.
    """
    if isinstance(node, dict):
        defs = node.pop("$defs", None)
        if isinstance(defs, dict):
            for name, definition in defs.items():
                existing = schemas.get(name)
                if existing is None:
                    schemas[name] = definition
                elif existing != definition:
                    logger.warning(
                        "Conflicting OpenAPI schema definitions for %r; "
                        "keeping the first one",
                        name,
                    )
        for value in node.values():
            _collect_local_defs(value, schemas)
    elif isinstance(node, list):
        for value in node:
            _collect_local_defs(value, schemas)


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
        _collect_local_defs(
            self.openapi_schema.get("paths", {}),
            self.openapi_schema.setdefault("components", {}).setdefault("schemas", {}),
        )
        schemas = self.openapi_schema.get("components", {}).get("schemas", {})
        for k in ("ValidationError", "HTTPValidationError"):
            if k in schemas:
                del schemas[k]

    return self.openapi_schema


def _setup_prometheus(
    app: FastAPI,
    *,
    enable_middleware: bool | None,
    exporter_resource: Resource | None,
) -> bool:
    """Resolve the prometheus backend, returning whether to add the middleware."""
    if exporter_resource is None:
        return True if enable_middleware is None else enable_middleware
    if enable_middleware:
        raise ValueError("Only one prometheus exporter can be configured")
    add_prometheus_exporter(app, resource=exporter_resource)
    return False


def configure_app(  # noqa: PLR0913
    app: FastAPI,
    *,
    enable_error_handlers: bool = True,
    enable_prometheus_middleware: bool | None = None,
    enable_request_logging_middleware: bool = False,
    prometheus_exporter_resource: Resource | None = None,
    simplify_openapi_ids: bool = True,
    gzip_middleware_min_size: int | None = 500,
    translation_manager: TranslationManager | None = None,
    limits: float | None = 1000,
    request_header_filter: HeaderFilter = DEFAULT_REQUEST_HEADER_FILTER,
    **tracing_options: Any,
) -> None:
    maybe_instrument_app(app, **tracing_options)
    if enable_error_handlers:
        add_error_handlers(app, request_header_filter)
        app.__setattr__("openapi", functools.partial(custom_openapi, app))
    enable_prometheus_middleware = _setup_prometheus(
        app,
        enable_middleware=enable_prometheus_middleware,
        exporter_resource=prometheus_exporter_resource,
    )
    if simplify_openapi_ids:
        simplify_operation_ids(app)

    # Middlewares are registered innermost-first: `add_middleware` prepends to
    # the stack, so the last one added is the first to see a request.
    if translation_manager:
        from .i18n import LocaleMiddleware, configure_translations

        app.add_middleware(LocaleMiddleware, translation_manager)
        configure_translations(translation_manager)
    if gzip_middleware_min_size:
        app.add_middleware(GZipMiddleware, minimum_size=gzip_middleware_min_size)
    if enable_prometheus_middleware:
        add_prometheus_middleware(app)
    if limits:
        from .middlewares.limits import RequestLimitMiddleware

        app.add_middleware(RequestLimitMiddleware, limits)
    if enable_request_logging_middleware:
        from .middlewares.structlog import RequestLoggingMiddleware

        app.add_middleware(
            RequestLoggingMiddleware, request_header_filter=request_header_filter
        )
