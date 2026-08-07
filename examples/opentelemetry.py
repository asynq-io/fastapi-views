import socket

import structlog
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from fastapi_views import configure_app
from fastapi_views.headers import DEFAULT_REQUEST_HEADERS, HeaderFilter

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)

resource = Resource.create(
    attributes={
        "service.name": "test-api",
        "service.version": "0.1.0",
        "service.instance.id": socket.gethostname(),
    },
)
provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))


app = FastAPI(title="My API")

configure_app(
    app,
    prometheus_exporter_resource=resource,
    enable_request_logging_middleware=True,
    request_header_filter=HeaderFilter({*DEFAULT_REQUEST_HEADERS, "x-tenant-id"}),
    gzip_middleware_min_size=500,
    limits=1000,
    excluded_urls="/healthcheck,/metrics",
)


@app.get("/healthcheck")
async def healthcheck():
    return {"status": "ok"}


@app.get("/test")
async def raise_error():
    raise ValueError("Server side error")
