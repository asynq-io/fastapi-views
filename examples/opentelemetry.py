import logging
import socket

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from fastapi_views import configure_app

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
    enable_prometheus_middleware=False,
    prometheus_exporter_resource=resource,
    log_config={"log_level": logging.INFO, "log_format": "console"},
)


@app.get("/test")
async def raise_error():
    # example of Internal Server Error being returned, with exception being recorded and correlation id returned
    raise ValueError("Server side error")
