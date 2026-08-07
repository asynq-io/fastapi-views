# Exceptions

HTTP error classes following [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html). Import from `fastapi_views.exceptions`.

Every `APIError` subclass automatically:

- generates a typed Pydantic model (`cls.model`, an [`ErrorDetails`](models.md#error-model) subclass) with constant `status`, `title`, and `type` fields
- is documented as an `application/problem+json` response for any route that declares it (via the view's `errors` attribute, or `errors()` / `throws()` — see [Decorators](decorators.md))
- is converted to a problem-details response by the handlers installed by `add_error_handlers` (called by `configure_app` unless `enable_error_handlers=False`)

## Built-in error classes

| Class | Status | `title` | `type` |
|-------|--------|---------|--------|
| `BadRequest` | 400 | `Bad Request` | RFC 7231 §6.5.1 |
| `Unauthorized` | 401 | `Unauthorized` | RFC 7235 §3.1 |
| `Forbidden` | 403 | `Forbidden` | RFC 7231 §6.5.3 |
| `NotFound` | 404 | `Not Found` | RFC 7231 §6.5.4 |
| `Conflict` | 409 | `Conflict` | RFC 7231 §6.5.8 |
| `UnprocessableEntity` | 422 | `Unprocessable Entity` | RFC 4918 §11.2 |
| `Throttled` | 429 | `Too Many Requests` | RFC 6585 §4 |
| `InternalServerError` | 500 | `Internal Server Error` | RFC 7231 §6.6.1 |
| `Unavailable` | 503 | `Service Unavailable` | RFC 7231 §6.6.4 |

`APIError` itself is raiseable and defaults to status `400`; pass `status=` to pick another code.

## Raising errors

```python
from fastapi_views.exceptions import NotFound, Throttled

raise NotFound("Item 42 does not exist")

# extra response headers are copied onto the HTTP response
raise Throttled("Slow down", headers={"Retry-After": "30"})
```

The constructor signature is `APIError(detail=None, *, headers=None, **kwargs)`:

- `detail` — overrides the model's default `detail`
- `headers` — a `Mapping[str, str]` attached to the outgoing response (not part of the JSON body)
- remaining keyword arguments populate the error model: `instance`, `errors`, plus any extra fields declared on the subclass

Useful members: `as_model()` returns the populated `ErrorDetails` instance, `status_code` the response status, `get_status()` the class-level status, and `set_default_instance(path)` fills `instance` only if it is still `None` (this is how the handler injects the request path).

## Response shape

Errors are serialized as `application/problem+json`:

```json
{
  "type": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.4",
  "title": "Not Found",
  "status": 404,
  "detail": "Item 42 does not exist",
  "instance": "/items/42",
  "correlation_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "errors": []
}
```

- `instance` is set to the request path by the handler when not supplied explicitly.
- `correlation_id` exists as a field only when `opentelemetry-instrumentation-fastapi` is importable, and is filled from the active trace context. When no span is active it is **omitted from the payload entirely** rather than serialized as `null` — `ErrorDetails` overrides `model_dump` / `model_dump_json` to add it to `exclude` (any `exclude` you pass is preserved). The field is still documented in the OpenAPI schema.
- `errors` is a free-form list used for nested error details (request validation failures land here).
- Extra fields declared on a subclass are appended after `errors`.
- `detail` is passed through the i18n `translate()` helper, so error messages participate in [translations](../usage/i18n.md).

## Defining custom errors

Subclass `APIError` (or one of the built-ins) and set `status`. `title` is derived from the class name by splitting CamelCase, and `type` from the status code's RFC mapping (falling back to `about:blank` for statuses that are not mapped). The class docstring becomes the model docstring and the OpenAPI response description.

```python
from fastapi_views.exceptions import APIError, NotFound
from starlette.status import HTTP_402_PAYMENT_REQUIRED


class PaymentRequired(APIError):
    """Payment is required to access this resource."""

    status = HTTP_402_PAYMENT_REQUIRED
    # title -> "Payment Required", type -> "about:blank" (402 is not in the RFC map)


class ItemNotFound(NotFound):
    """No item matches the requested id."""
    # status inherited (404), title -> "Item Not Found", type -> RFC 7231 §6.5.4
```

`title` derivation keeps runs of capitals together, so acronyms survive:

| Class name | Derived `title` |
|------------|-----------------|
| `UserNotFound` | `User Not Found` |
| `HTTPError` | `HTTP Error` |
| `APIKeyInvalid` | `API Key Invalid` |
| `S3BucketMissing` | `S3 Bucket Missing` |
| `HTTP` | `HTTP` |

The one remaining edge case is a lowercase letter *inside* a leading acronym, which still
splits: `OAuth2TokenExpired` becomes `O Auth2 Token Expired`. Set `title` explicitly in
that case.

Set `title`, `type`, or `detail` explicitly to override any of the derived values — an
explicit `title` always wins over derivation:

```python
class HTTPBackendError(InternalServerError):
    title = "Upstream Backend Error"        # instead of the derived "HTTP Backend Error"
    type = "https://example.com/errors/backend"
    detail = "The upstream backend failed"  # default detail when none is passed
```

When `detail` is left unset, the model default is the standard `http.HTTPStatus` description for the status code, falling back to the status **phrase** when that description is empty. No built-in error has an empty default `detail`: `UnprocessableEntity()`, whose `HTTPStatus` description is `""`, yields `detail: "Unprocessable Entity"`.

### Extra model fields

Plain annotations on the subclass become fields of the generated error model:

```python
from typing import ClassVar


class OutOfStock(NotFound):
    """Item is out of stock."""

    sku: str                          # required — must be passed when raising
    error_code: str = "OUT_OF_STOCK"  # annotation + scalar default -> constant field
    meta: dict = {}                   # optional field with a mutable default
    warehouse: ClassVar[str] = "eu-1" # class attribute, never serialized


raise OutOfStock("Item is no longer available", sku="ABC-1")
```

```json
{
  "type": "https://datatracker.ietf.org/doc/html/rfc7231#section-6.5.4",
  "title": "Out Of Stock",
  "status": 404,
  "detail": "Item is no longer available",
  "instance": "/items/ABC-1",
  "errors": [],
  "sku": "ABC-1",
  "error_code": "OUT_OF_STOCK",
  "meta": {}
}
```

Rules applied to annotations:

| Declaration | Result |
|-------------|--------|
| `sku: str` | required model field — must be passed when raising |
| `meta: dict = {}` / `tags: list = []` / `codes: set = set()` | optional model field with that mutable default |
| `error_code: str = "OUT_OF_STOCK"` | `Literal["OUT_OF_STOCK"]` constant — this is the discriminator feature: documented as `const` in OpenAPI and rejected if a different value is passed. Any non-mutable default behaves this way |
| `warehouse: ClassVar[str] = "eu-1"` | stays a plain class attribute: never a model field, never serialized, and **not** settable through constructor keywords (a `warehouse=...` kwarg is silently ignored) |
| `lazy: ClassVar[str]` (no default) | ignored entirely |
| `type`, `title`, `status`, `detail`, `model` | not treated as extra fields (they configure the generated model instead) |
| names starting with `_` | ignored |

The `ClassVar` rule is uniform across annotation types — `ClassVar[str] = "x"` and
`ClassVar[list] = []` both stay class attributes. Both bare and string (PEP 563 /
`from __future__ import annotations`) forms of `ClassVar` are detected. Unannotated class
attributes are not inspected at all.

Subclassing composes: the generated model uses the parent's model as its base, so a subclass inherits its parent's extra fields and may narrow constants further.

## Registered handlers

`add_error_handlers(app, header_filter=DEFAULT_REQUEST_HEADER_FILTER)` registers, and `configure_app` calls it:

| Exception | Handler | Result |
|-----------|---------|--------|
| `APIError` | `api_error_handler` | the error's own status/model, with `instance` defaulted to the request path |
| `RequestValidationError` | `request_validation_handler` | `400 Bad Request` with `detail: "Request validation error"` and the pydantic errors under `errors` |
| `starlette.exceptions.HTTPException` | `http_exception_handler` | problem-details body built from `exc.status_code`, `exc.detail` and `exc.headers` |
| `ResponseValidationError` | unhandled-exception handler | `500` `Internal Server Error` |
| `Exception` | unhandled-exception handler | `500` `Internal Server Error`, logged as `unhandled_exception` on the `exceptions.handler` logger |

Note that request validation failures are reported as **400**, not 422 — `configure_app` also strips FastAPI's automatic `422` entries (and the `HTTPValidationError` schemas) from the OpenAPI document.

`create_exception_handler(header_filter)` builds the unhandled-exception handler; the module-level `exception_handler` is the instance using the default filter.

This handler is the **only** place a traceback is emitted: `RequestLoggingMiddleware` logs no `exc_info`, and it filters uvicorn's own `Exception in ASGI application` record to avoid a duplicate. Disabling `enable_error_handlers` therefore also removes the traceback — see [Observability](../usage/opentelemetry.md#structured-request-logging).

## Logging headers safely

The unhandled-exception handler logs the request URL, query parameters and headers. Headers pass through a `HeaderFilter` (`fastapi_views.headers`) — an allow-list, so credential-bearing headers such as `authorization`, `proxy-authorization`, `cookie` or API-key headers never reach the logs. Names are lower-cased and emitted as snake_case keys (`user-agent` becomes `user_agent`).

```python
from fastapi_views import configure_app
from fastapi_views.headers import HeaderFilter

configure_app(app, request_header_filter=HeaderFilter({"x-tenant-id", "user-agent"}))
```

| Object | Purpose |
|--------|---------|
| `DEFAULT_REQUEST_HEADERS` | default allow-list for request headers (`origin`, `referer`, `host`, `user-agent`, `content-type`, `content-length`, `accept*`, `access-control-request-*`, `x-request-id`, `x-forwarded-*`) |
| `DEFAULT_RESPONSE_HEADERS` | default allow-list for response headers (`content-type`, `content-length`, `vary`, `access-control-allow-*`, `access-control-expose-headers`, `access-control-max-age`) |
| `DEFAULT_REQUEST_HEADER_FILTER` | `HeaderFilter(DEFAULT_REQUEST_HEADERS)` — default for `add_error_handlers` and `configure_app` |
| `DEFAULT_RESPONSE_HEADER_FILTER` | `HeaderFilter(DEFAULT_RESPONSE_HEADERS)` |

`HeaderFilter` is callable on any `Mapping[str, str]` (e.g. `request.headers`) and exposes `filter_raw()` for raw ASGI `(bytes, bytes)` header pairs. The same filters are reused by the request-logging middleware.

---

::: fastapi_views.exceptions
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

::: fastapi_views.handlers
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_signature_annotations: true

---

::: fastapi_views.headers
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_signature_annotations: true
