# Observability

`configure_app` is the single entry point for the observability stack: OpenTelemetry
tracing, Prometheus metrics, structured request logging, response compression, a
concurrency limit, locale detection and the RFC 9457 error handlers.

Everything is opt-in at the dependency level — if an optional package is not installed the
matching feature is skipped (tracing) or raises on import (metrics, logging), and the rest
of the application keeps working.

---

## Installation

The relevant extras, exactly as declared in `pyproject.toml`:

```shell
pip install 'fastapi-views[opentelemetry]'   # opentelemetry-instrumentation-fastapi,
                                             # opentelemetry-exporter-prometheus,
                                             # prometheus-client
pip install 'fastapi-views[prometheus]'      # starlette-exporter
pip install 'fastapi-views[structlog]'       # structlog
pip install 'fastapi-views[cli]'             # typer
```

There is also a curated `standard` bundle (`uvloop`, `uvicorn`, `starlette-exporter`,
`opentelemetry-instrumentation-fastapi`, `typer`) and `all`, which installs every extra.

An OpenTelemetry SDK and an exporter are not pulled in by name — install
`opentelemetry-sdk` plus the exporter for your backend (see
[Sending traces to a real backend](#sending-traces-to-a-real-backend)).

---

## `configure_app`

```python
from fastapi import FastAPI

from fastapi_views import configure_app

app = FastAPI(title="My API")
configure_app(app)
```

| Parameter | Default | What it does |
|---|---|---|
| `enable_error_handlers` | `True` | Registers the RFC 9457 handlers for `APIError`, `HTTPException`, `RequestValidationError`, `ResponseValidationError` and `Exception`, and replaces `app.openapi` with the library's `custom_openapi` (OpenAPI 3.2.0, `422` responses and the `ValidationError`/`HTTPValidationError` schemas removed, inline `$defs` relocated into `components/schemas`) |
| `enable_prometheus_middleware` | `True` | Adds `starlette-exporter`'s `PrometheusMiddleware` and a `/metrics` route |
| `enable_request_logging_middleware` | `False` | Adds `RequestLoggingMiddleware` (requires the `structlog` extra) |
| `prometheus_exporter_resource` | `None` | When set, installs the OpenTelemetry metrics pipeline instead and mounts `/metrics`. Mutually exclusive with `enable_prometheus_middleware` |
| `simplify_openapi_ids` | `True` | Rewrites every `APIRoute.operation_id` to the route name without spaces |
| `gzip_middleware_min_size` | `500` | Minimum response size in bytes for `GZipMiddleware`; pass `None` or `0` to skip it |
| `translation_manager` | `None` | Installs `LocaleMiddleware` and registers the manager as the global translation source — see [Internationalization](i18n.md) |
| `limits` | `1000` | Maximum number of concurrently handled requests (`RequestLimitMiddleware`); pass `None` or `0` to skip it |
| `request_header_filter` | `DEFAULT_REQUEST_HEADER_FILTER` | `HeaderFilter` allow-list used both by the unhandled-exception handler and by `RequestLoggingMiddleware` |
| `**tracing_options` | — | Forwarded verbatim to `FastAPIInstrumentor.instrument_app` |

!!! note
    `log_config` no longer exists. Structured logging is enabled with
    `enable_request_logging_middleware=True`, and configuring `structlog`'s own
    processors and renderer is left to your application.

### Middleware order

`add_middleware` prepends to the stack, so the middleware added last is the first to see a
request. With every feature enabled, a request travels outermost → innermost:

```text
RequestLoggingMiddleware   -> PrometheusMiddleware -> GZipMiddleware
-> LocaleMiddleware        -> RequestLimitMiddleware -> router
```

Consequences worth knowing:

- request logging observes the final status code and the compressed response headers;
- the Prometheus histogram includes the time a request spends waiting for a concurrency
  slot;
- the concurrency limit is applied last, so `/metrics` scrapes and gzip work even while
  the limiter is saturated.

Any middleware you add yourself *after* `configure_app` ends up outside all of them.

---

## OpenTelemetry tracing

`configure_app` always calls `maybe_instrument_app(app, **tracing_options)`, which imports
`FastAPIInstrumentor` lazily and returns silently when
`opentelemetry-instrumentation-fastapi` is not installed:

```python
from fastapi_views.opentelemetry import (
    OPENTELEMETRY_INSTALLED,
    get_correlation_id,
    maybe_instrument_app,
)
```

- `maybe_instrument_app(app, **options)` — instruments the app, or does nothing.
- `get_correlation_id()` — returns the current span's trace ID as a 32-character hex
  string, or `None` when the span context is invalid (no active trace) or the
  instrumentation package is missing.
- `OPENTELEMETRY_INSTALLED` — evaluated once at import time.

### How the `correlation_id` reaches error responses

`ErrorDetails` declares its `correlation_id` field **only** when
`OPENTELEMETRY_INSTALLED` is true:

```python
if OPENTELEMETRY_INSTALLED:
    correlation_id: str | None = Field(default_factory=get_correlation_id)
```

The default factory runs when the error model is instantiated — inside the request, while
the server span is still current — so every response produced by the error handlers
(`APIError`, `HTTPException`, request/response validation errors and unhandled exceptions)
carries the trace ID of the request that produced it. Without the extra installed the
field is absent from both the response body and the OpenAPI schema.

### Setup

Configure a `TracerProvider` pointing at your backend, then call `configure_app`.

```python
import socket

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from fastapi_views import configure_app

resource = Resource.create(
    attributes={
        "service.name": "my-api",
        "service.version": "1.0.0",
        "service.instance.id": socket.gethostname(),
    }
)

provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

app = FastAPI(title="My API")
configure_app(app)


@app.get("/test")
async def raise_error():
    raise ValueError("Something went wrong")
```

### Error response with `correlation_id`

```json
{
  "type": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.6.1",
  "title": "Internal Server Error",
  "status": 500,
  "detail": "Unhandled server error",
  "instance": "/test",
  "correlation_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "errors": []
}
```

The response media type is `application/problem+json`. Pass the `correlation_id` to your
tracing UI to find the full span and all associated logs.

### Passing options to `FastAPIInstrumentor`

Every keyword argument that is not part of the signature above is forwarded to
`FastAPIInstrumentor.instrument_app`:

```python
configure_app(
    app,
    excluded_urls="/healthcheck,/metrics",
    span_name_formatter=lambda scope: scope["path"],
)
```

See the [OpenTelemetry FastAPI Instrumentation docs](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)
for the full list of supported options.

### Sending traces to a real backend

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

## Prometheus metrics

Two mutually exclusive backends are available. Passing both raises
`ValueError("Only one prometheus exporter can be configured")`:

```python
configure_app(app, prometheus_exporter_resource=resource)  # ValueError:
                                                           # enable_prometheus_middleware
                                                           # defaults to True
```

### 1. `starlette-exporter` middleware (default)

`add_prometheus_middleware(app, endpoint="/metrics", **kwargs)` adds
`PrometheusMiddleware` and registers `handle_metrics` on `endpoint`. The defaults it
applies (each overridable through `kwargs`) are:

| Option | Default |
|---|---|
| `group_paths` | `True` — label with the route template, e.g. `/items/{item_id}` |
| `app_name` | `app.title.lower().replace(" ", "_")` |
| `labels` | `{"server": socket.gethostname()}` |
| `always_use_int_status` | `True` |
| `filter_unhandled_paths` | `False` |
| `group_unhandled_paths` | `True` |

`GET /metrics` then exposes the `prometheus_client` text format, including
`starlette_requests_total`, `starlette_requests_created`,
`starlette_request_duration_seconds` (histogram) and `starlette_requests_in_progress`,
labelled with `app_name`, `method`, `path`, `status_code` and `server`.

To tune the middleware, disable it in `configure_app` and call the helper yourself:

```python
from fastapi_views.prometheus import add_prometheus_middleware

configure_app(app, enable_prometheus_middleware=False)
add_prometheus_middleware(app, endpoint="/internal/metrics", app_name="my_api")
```

### 2. OpenTelemetry metrics pipeline

Passing `prometheus_exporter_resource` calls
`add_prometheus_exporter(app, resource=...)`, which installs a `MeterProvider` with a
`PrometheusMetricReader` as the global meter provider and **mounts**
`prometheus_client.make_asgi_app()` at `/metrics`. Use this when your own code records
metrics through the OpenTelemetry metrics API and you want them scraped from the same
process.

```python
configure_app(
    app,
    enable_prometheus_middleware=False,
    prometheus_exporter_resource=resource,
)
```

This mode exposes only the metrics your instrumentation records (plus the default
`prometheus_client` process collectors) — there is no per-request HTTP middleware, so the
`starlette_*` series above are not produced. Because the endpoint is *mounted* rather than
routed, `GET /metrics` answers with a `307` redirect to `/metrics/`; point scrapers at the
trailing-slash form.

Both modes require `prometheus-client`, which ships with the `opentelemetry` extra and
is a dependency of `starlette-exporter`.

---

## Structured request logging

```python
configure_app(app, enable_request_logging_middleware=True)
```

`RequestLoggingMiddleware` logs through `structlog.get_logger("fastapi.access")`. On
construction it also silences duplicate output from uvicorn: `uvicorn.access` stops
propagating and `uvicorn.error` gets a filter dropping `Exception in ASGI application`
records (the middleware logs those itself, with context).

For every HTTP request it clears the `structlog` context vars and binds:

| Context var | Value |
|---|---|
| `request_id` | the incoming `X-Request-Id` header, or a fresh `uuid4()` |
| `client` | `"{host}:{port}"`, or `"unknown"` when the ASGI scope has no client |

Both are then attached to *all* log records emitted while handling the request, including
those from your own code. Non-HTTP scopes (lifespan, websocket) are passed straight
through.

Then up to two events are emitted, each bound with `method` and `path`:

| Event | Level | Fields |
|---|---|---|
| `request` | `INFO` | `query_params`, `headers` (filtered), plus anything returned by `extra_context` |
| `response` | derived from the status code | `status_code`, `duration_ms`, `headers` (filtered response headers) |
| `unhandled_exception` | `ERROR` with `exc_info` | `url`, `headers`, `query_params`, `duration_ms` — then the exception is re-raised |

The response level mapping is: `>= 500` → `ERROR`, `>= 400` → `WARNING`, everything else
(including a missing status code) → `INFO`. An exception that escapes the router replaces
the `response` event with `unhandled_exception`; the 500 body itself is rendered by
Starlette's `ServerErrorMiddleware` using the error handler installed by
`enable_error_handlers`.

### Middleware options

`configure_app` only forwards `request_header_filter`. To use the remaining options, keep
the flag off and register the middleware yourself:

```python
from fastapi import Request

from fastapi_views import configure_app
from fastapi_views.middlewares.structlog import RequestLoggingMiddleware


async def extra_context(request: Request) -> dict:
    return {"tenant": request.headers.get("X-Tenant")}


configure_app(app, enable_request_logging_middleware=False)
app.add_middleware(
    RequestLoggingMiddleware,
    exclude=("/healthcheck", "/metrics"),
    extra_context=extra_context,
)
```

| Option | Default |
|---|---|
| `exclude` | `("/healthcheck",)` — matched against `request.url.path`; excluded paths emit no events (context vars are still bound) |
| `extra_context` | `None` — async callable `(Request) -> dict`, merged into the `request` event |
| `request_header_filter` | `DEFAULT_REQUEST_HEADER_FILTER` |
| `response_header_filter` | `DEFAULT_RESPONSE_HEADER_FILTER` |

### Header filtering

`HeaderFilter` is an allow-list: anything outside it is dropped, so `authorization`,
`cookie`, `set-cookie` and API-key headers never reach the logs. Names are lower-cased and
`-` is replaced with `_`, so `X-Request-Id` is logged as `x_request_id`.

```python
from fastapi_views.headers import DEFAULT_REQUEST_HEADERS, HeaderFilter

configure_app(
    app,
    request_header_filter=HeaderFilter({*DEFAULT_REQUEST_HEADERS, "x-tenant-id"}),
)
```

`DEFAULT_REQUEST_HEADERS` covers the usual routing/negotiation headers (`host`, `origin`,
`referer`, `user-agent`, `content-type`, `content-length`, the `accept*` and
`access-control-request-*` families, `x-request-id` and the `x-forwarded-*` family).
`DEFAULT_RESPONSE_HEADERS` covers `content-type`, `content-length`, `vary` and the
`access-control-allow-*` / `-expose-headers` / `-max-age` family. The same filter is
handed to the unhandled-exception handler, so its `unhandled_exception` log record obeys
the identical allow-list.

Rendering is up to your application — `structlog` is configured once, at startup:

```python
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
```

---

## Concurrency limit

`RequestLimitMiddleware` wraps the application in an `anyio.CapacityLimiter`, so at most
`limits` HTTP/websocket requests are handled at once; the rest wait for a slot. It is
installed by default with `limits=1000`.

```python
from fastapi_views.middlewares.limits import RequestLimitMiddleware

configure_app(app, limits=200)          # or
configure_app(app, limits=None)         # skip the middleware entirely
app.add_middleware(RequestLimitMiddleware, 50)
```

Scopes other than `http` and `websocket` (i.e. `lifespan`) bypass the limiter.

---

## Lifespan helpers

### `merge_lifespans`

Compose several lifespan context managers into the single one FastAPI accepts. They are
entered in order and exited in reverse:

```python
from fastapi import FastAPI

from fastapi_views.lifespan import merge_lifespans

app = FastAPI(lifespan=merge_lifespans(db_lifespan, broker_lifespan))
```

### `StatefulLifespanMiddleware` and `FromScope`

`StatefulLifespanMiddleware` sets up app-scoped dependencies in the ASGI lifespan state.
Each keyword argument is an async context manager — or a factory returning one — entered
on startup and exited on shutdown; the entered value is stored in the lifespan state under
its keyword name. If startup fails, the dependencies already entered are still torn down.

`FromScope(key)` is a FastAPI dependency returning that value, so views never touch
`request.state` directly:

```python
from typing import Annotated

from fastapi_views.lifespan import FromScope
from fastapi_views.middlewares.lifespan import StatefulLifespanMiddleware

app.add_middleware(StatefulLifespanMiddleware, db=lambda: db_session_factory())


@app.get("/items")
async def list_items(db: Annotated[Database, FromScope("db")]) -> list[Item]:
    return await db.fetch_items()
```

Subclass `LifespanMiddleware` and implement `setup(state)` / `teardown()` for anything the
context-manager form does not cover.

---

## CLI

The `cli` extra installs `typer` and the `fastapi-views` entry point, which exports a
static OpenAPI document without starting a server. It exposes a single command, so the
application path is the first argument:

```shell
pip install 'fastapi-views[cli]'

fastapi-views myapp.main:app --out openapi.json
fastapi-views myapp.main:app --out openapi.yaml --format yaml
```

| Argument / option | Default | Notes |
|---|---|---|
| `app` | required | `module:attribute`, resolved with `importlib`; `.` is prepended to `sys.path` so relative imports from the current working directory work |
| `--out` | `./openapi.json` | Output file path |
| `--format` | `json` | `json` (indented, 4 spaces) or `yaml`; anything else raises `ValueError`. `yaml` requires `PyYAML` |

The target object must be a `FastAPI` instance (`TypeError` otherwise), and the document
is produced by `app.openapi()` — so with `configure_app`'s `custom_openapi` in place, the
exported file is OpenAPI 3.2.0 with the `422` responses stripped.

---

## Complete example

```python
--8<-- "examples/opentelemetry.py"
```
