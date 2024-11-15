import logging
import socket

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from fastapi_views import configure_app

logging.basicConfig(level=logging.INFO)
resource = Resource(
    attributes={
        "service.name": "test-api",
        "service.version": "0.1.0",
        "service.instance.id": socket.gethostname(),
    }
)
provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
LoggingInstrumentor().instrument()


app = FastAPI(title="My API")

configure_app(app)


@app.get("/test")
async def raise_error():
    # example of Internal Server Error being returned, with exception being recorded and correlation id returned
    raise ValueError("Server side error")
