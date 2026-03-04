# OpenTelemetry

FastAPI Views provides optional OpenTelemetry integration that automatically:

1. Instruments your FastAPI application using `FastAPIInstrumentor`.
2. Captures the active trace ID for each request and stores it in a context variable.
3. Injects the trace ID as a `correlation_id` field in every error response.

This makes it trivial to correlate an error a user reports with a specific trace in your observability backend (Jaeger, Zipkin, Grafana Tempo, etc.).

---

## Installation

Install the `opentelemetry` extra:

```shell
pip install 'fastapi-views[opentelemetry]'
```

Or install the instrumentation package directly:

```shell
pip install opentelemetry-instrumentation-fastapi
```

The integration is **opt-in** — if the package is not installed, everything works normally and error responses will not include a `correlation_id` field.

---

## How it works

When `configure_app(app)` is called and `opentelemetry-instrumentation-fastapi` is available, FastAPI Views:

1. Calls `FastAPIInstrumentor.instrument_app(app)` with a `server_request_hook` that reads the current span's trace ID and stores it in a `ContextVar` (`CORRELATION_ID`).
2. The `ErrorDetails` model conditionally declares a `correlation_id` field whose default factory reads from that `ContextVar`.
3. Every error response — whether from an `APIError`, a validation error, or an unhandled exception — will automatically include the `correlation_id` of the trace that triggered it.

---

## Setup

Configure a `TracerProvider` (pointing at your observability backend), then call `configure_app`. No other changes are required.

```python
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
        "service.name": "my-api",
        "service.version": "1.0.0",
        "service.instance.id": socket.gethostname(),
    }
)

provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

# Propagate trace IDs into log records
LoggingInstrumentor().instrument()

app = FastAPI(title="My API")
configure_app(app)


@app.get("/test")
async def raise_error():
    # Any unhandled exception is caught by configure_app's error handlers.
    # The response will include the correlation_id of the current trace.
    raise ValueError("Something went wrong")
```

### Error response with `correlation_id`

When an error occurs during a traced request, the response body will include the trace ID:

```json
{
  "type": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.1",
  "title": "Internal Server Error",
  "status": 500,
  "detail": "Internal server error",
  "instance": "/test",
  "correlation_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "errors": []
}
```

The `correlation_id` value is the W3C trace ID formatted as a 32-character hex string. Pass this ID to your tracing UI to find the full span and all associated logs.

---

## Passing options to `FastAPIInstrumentor`

Any keyword arguments passed to `configure_app` beyond its own parameters are forwarded to `FastAPIInstrumentor.instrument_app`. This lets you configure excluded URLs, custom span name formatting, etc.:

```python
configure_app(
    app,
    excluded_urls="/healthz,/metrics",
    span_name_formatter=lambda scope: scope["path"],
)
```

See the [OpenTelemetry FastAPI Instrumentation docs](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html) for the full list of available options.

---

## Sending traces to a real backend

Replace `ConsoleSpanExporter` with the exporter for your backend.

**OTLP via gRPC:**

```shell
pip install opentelemetry-exporter-otlp-proto-grpc
```

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel-collector:4317"))
)
```

**OTLP via HTTP:**

```shell
pip install opentelemetry-exporter-otlp-proto-http
```

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(endpoint="http://otel-collector:4318/v1/traces")
    )
)
```

---

## Complete example

```python
--8<-- "examples/opentelemetry.py"
```
