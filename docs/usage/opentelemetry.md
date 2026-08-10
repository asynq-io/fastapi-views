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
| `enable_prometheus_middleware` | `None` | Adds `starlette-exporter`'s `PrometheusMiddleware` and a `/metrics` route. `None` means "on unless `prometheus_exporter_resource` is set"; pass `True`/`False` to decide explicitly |
| `enable_request_logging_middleware` | `False` | Adds `RequestLoggingMiddleware` (requires the `structlog` extra) |
| `prometheus_exporter_resource` | `None` | When set, installs the OpenTelemetry metrics pipeline instead and registers `/metrics` for it. Selects exporter mode on its own; only an explicit `enable_prometheus_middleware=True` alongside it is an error |
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

!!! note
    `limits` is typed `float | None`, but the underlying `anyio.CapacityLimiter` only
    accepts an integer or `math.inf` — use `math.inf` for "no limit" rather than a
    fractional value.

### Middleware order

`add_middleware` prepends to the stack, so the middleware added last is the first to see a
request. With every feature enabled, a request travels outermost → innermost:

```text
RequestLoggingMiddleware   -> RequestLimitMiddleware -> PrometheusMiddleware
-> GZipMiddleware          -> LocaleMiddleware       -> router
```

Consequences worth knowing:

- request logging observes the final status code and the compressed response headers;
- the concurrency limiter sits *outside* Prometheus, gzip and locale detection, so a
  request queued for a slot does not hold those layers open. The Prometheus histogram
  therefore measures post-admission handling only — queue wait time shows up in the
  `duration_ms` field of the logging middleware's `response` event, which is the outermost
  layer;
- because the limiter wraps everything below it — including the `/metrics` route, which is
  a normal route of the application in both metrics modes — scrapes are gated by the
  limiter too. If they must survive saturation, skip `limits` and register
  `RequestLimitMiddleware` yourself around a sub-app, or expose metrics from a separate
  ASGI app.

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

Two mutually exclusive backends are available, and `enable_prometheus_middleware=None`
(the default) picks between them: the middleware is enabled unless a
`prometheus_exporter_resource` is given.

```python
configure_app(app)                                         # middleware mode
configure_app(app, prometheus_exporter_resource=resource)   # exporter mode
configure_app(app, enable_prometheus_middleware=False)      # no metrics at all
```

Only asking for both *explicitly* is an error:

```python
configure_app(
    app,
    enable_prometheus_middleware=True,
    prometheus_exporter_resource=resource,
)  # ValueError: Only one prometheus exporter can be configured
```

In both modes `/metrics` is a plain route registered with `app.add_route`, so a bare
`GET /metrics` answers `200` with no redirect, the response is compressed by
`GZipMiddleware` like any other, and the endpoint is kept out of the OpenAPI document
(it is a Starlette `Route`, not an `APIRoute`).

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

`GET /metrics` then exposes the `prometheus_client` text format
(`text/plain; version=1.0.0`, regardless of the request's `Accept` header), including
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
`add_prometheus_exporter(app, resource=..., endpoint="/metrics")`, which installs a
`MeterProvider` with a `PrometheusMetricReader` as the global meter provider and registers
a route serving `render_metrics`. Use this when your own code records metrics through the
OpenTelemetry metrics API and you want them scraped from the same process.

```python
configure_app(app, prometheus_exporter_resource=resource)
```

`render_metrics(request)` is public: it renders the default `prometheus_client.REGISTRY`
through `choose_encoder(request.headers["accept"])`, so the exposition format is
content-negotiated — `Accept: application/openmetrics-text; version=1.0.0` yields
OpenMetrics, and anything else falls back to `text/plain; version=0.0.4`. Call the helper
yourself to serve the metrics from a different path:

```python
from fastapi_views.prometheus import add_prometheus_exporter

configure_app(app, enable_prometheus_middleware=False)
add_prometheus_exporter(app, resource=resource, endpoint="/internal/metrics")
```

This mode exposes only the metrics your instrumentation records (plus the default
`prometheus_client` process collectors) — there is no per-request HTTP middleware, so the
`starlette_*` series above are not produced.

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
records, which would otherwise duplicate the traceback already emitted by the
`exceptions.handler` record from `handlers.py`.

!!! warning
    Combining `enable_request_logging_middleware=True` with `enable_error_handlers=False`
    removes the only remaining traceback: the middleware never logs `exc_info`, and the
    uvicorn filter suppresses uvicorn's own record. Unhandled exceptions then appear as a
    `response` event with `status_code=500` and nothing else. Keep the error handlers on,
    or install your own logging exception handler.

For every HTTP request it clears the `structlog` context vars and binds:

| Context var | Value |
|---|---|
| `request_id` | the incoming `X-Request-Id` header, or a fresh `uuid4()` |
| `client` | `"{host}:{port}"`, or `"unknown"` when the ASGI scope has no client |

Both are then attached to *all* log records emitted while handling the request, including
those from your own code. Non-HTTP scopes (lifespan, websocket) are passed straight
through.

Then exactly two events are emitted per non-excluded request, each bound with `method` and
`path`:

| Event | Level | Fields |
|---|---|---|
| `request` | `INFO` | `query_params`, `headers` (filtered), plus anything returned by `extra_context` |
| `response` | derived from the status code | `status_code`, `duration_ms`, `headers` (filtered response headers) |

The response level mapping is: `>= 500` → `ERROR`, `>= 400` → `WARNING`, everything else
(including a missing status code) → `INFO`.

`response` is emitted from a `finally` block, so it is logged even when the request fails:

- an exception that escapes the router is re-raised after the event is logged. If the
  response never started, `status_code` is backfilled with `500` (`ERROR`); if a status was
  already sent before the exception, that status is reported instead;
- a cancelled or aborted request logs `response` with `status_code: null` at `INFO`;
- the traceback itself is logged exactly once, by the `exceptions.handler` stdlib logger in
  `handlers.py`, not by this middleware — there is no `unhandled_exception` structlog
  event. The 500 body is rendered by Starlette's `ServerErrorMiddleware` using the handler
  installed by `enable_error_handlers`.

### Middleware options

`configure_app` only forwards `request_header_filter`. To use the remaining options, keep
the flag off and register the middleware yourself:

```python
from typing import Any

from fastapi import Request

from fastapi_views import configure_app
from fastapi_views.middlewares.structlog import RequestLoggingMiddleware


async def extra_context(request: Request) -> dict[str, Any]:
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
`access-control-allow-*` / `-expose-headers` / `-max-age` family.

Inside the middleware, `request_header_filter` applies to the `request` event only —
response headers go through `response_header_filter`. `configure_app` hands the same
`request_header_filter` to `add_error_handlers`, so the `unhandled_exception` record
emitted by `handlers.py` obeys the identical allow-list.

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
import math

from fastapi_views.middlewares.limits import RequestLimitMiddleware

configure_app(app, limits=200)          # or
configure_app(app, limits=math.inf)     # installed, but unbounded
configure_app(app, limits=None)         # skip the middleware entirely
app.add_middleware(RequestLimitMiddleware, 50)
```

Scopes other than `http` and `websocket` (i.e. `lifespan`) bypass the limiter. Everything
below the limiter — Prometheus, gzip, locale detection and the router, `/metrics` included
— only runs once a slot has been acquired.

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
static OpenAPI document without starting a server. `docs` is a real subcommand, so the
application path comes after it:

```console
$ pip install 'fastapi-views[cli]'

$ fastapi-views docs myapp:app
$ fastapi-views docs myapp:app --out openapi.json
$ fastapi-views docs myapp:app --out openapi.yaml --format yaml
```

`myapp:app` is `<importable.module>:<FastAPI attribute>`. Running `fastapi-views` with no
arguments prints the help text.

!!! warning
    The old collapsed form, `fastapi-views myapp:app --out openapi.json`, no longer works:
    the app path is now parsed as a command name, so it exits with code `2` and
    `No such command`. Insert `docs`.

| Argument / option | Default | Notes |
|---|---|---|
| `app` | required | `module:attribute`, resolved with `importlib`; `.` is prepended to `sys.path` so imports relative to the current working directory work |
| `--out` | `./openapi.json` | Output file path |
| `--format` | `json` | `json` (indented, 4 spaces) or `yaml`; anything else raises `ValueError` |

The target object must be a `FastAPI` instance (`TypeError` otherwise), and the document
is produced by `app.openapi()` — so with `configure_app`'s `custom_openapi` in place, the
exported file is OpenAPI 3.2.0 with the `422` responses stripped.

!!! note
    `--format yaml` needs `PyYAML` **in your own project**. It is deliberately not a
    declared dependency of `fastapi-views`, so if it is missing the command fails with an
    actionable `BadParameter` error (`PyYAML is required for '--format yaml'. Install it
    with 'pip install pyyaml' (or 'uv add pyyaml')`) and exit code `2`, rather than a raw
    `ModuleNotFoundError`.

---

## Complete example

```python
--8<-- "examples/opentelemetry.py"
```
