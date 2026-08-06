# Models

Shared Pydantic model base classes, the RFC 9457 `ErrorDetails` model, response-header schemas and the Server-Sent Event types. Import from `fastapi_views.models`.

## Exports

`fastapi_views.models` re-exports:

| Name | Kind |
|------|------|
| `BaseSchema` | base model |
| `CamelCaseSchema`, `IdSchema`, `CreatedUpdatedSchema`, `IdCreatedUpdatedSchema` | common models |
| `ErrorDetails`, `ErrorDetailsType`, `const_type`, `create_error_model` | error model + helpers |
| `ResponseHeaders` | OpenAPI response-header schema |
| `BaseServerSentEvent`, `IdBaseServerSentEvent`, `AnyServerSentEvent` | SSE event models |

Two more model modules are **not** re-exported and must be imported from their submodule:

- `fastapi_views.models.base.OpenAPIBase` — the self-documenting schema base
- `fastapi_views.models.jsonpatch` — `JsonPatchModel`, `JsonPatch`, `PatchOperation`, `apply()` (see [JSON Patch](../usage/jsonpatch.md))
- `fastapi_views.models.streaming` — `ResponseStarted` / `ResponseResult` / `ResponseError` / `ResponseCancelled` / `ResponseFinished` and the `ResponseEvent` union used for streaming responses (see [Server Side Events](../usage/sse.md))

## Base schemas

| Class | Description |
|-------|-------------|
| `BaseSchema` | Pydantic `BaseModel` with `use_enum_values`, `populate_by_name`, and `from_attributes` enabled |
| `OpenAPIBase` | `BaseSchema` that can render itself as OpenAPI content, keyed by its `__content_type__` |
| `CamelCaseSchema` | `BaseSchema` with `alias_generator = to_camel` for camelCase JSON keys |
| `IdSchema` | `BaseSchema` with a `UUID` `id` field |
| `CreatedUpdatedSchema` | `BaseSchema` with `created_at` and `updated_at` datetime fields |
| `IdCreatedUpdatedSchema` | Combines `IdSchema` and `CreatedUpdatedSchema` |

### OpenAPIBase

`OpenAPIBase` declares the media type a schema is documented and served under, and turns itself into an OpenAPI response entry. It is the base of `ErrorDetails`, `ResponseHeaders` and the SSE event models.

| Member | Description |
|--------|-------------|
| `__content_type__` | media type used when rendering OpenAPI content (default `application/json`) |
| `get_openapi_schema(title=None)` | JSON schema in serialization mode, with `$ref`s pointing at `#/components/schemas/{model}` and nested models in `$defs`; `title` overrides the schema title |
| `get_openapi_content(title=None)` | `{__content_type__: {"schema": ...}}`, ready to drop into a route's `responses` |

`$defs` produced this way are relocated into the application's `components/schemas` by `custom_openapi`, which `configure_app` installs, so the references stay resolvable.

## Error model

`ErrorDetails` is the base model for all [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html) problem-details responses; its `__content_type__` is `application/problem+json`.

| Field | Type | Default |
|-------|------|---------|
| `type` | `Url \| Literal["about:blank"]` | `"about:blank"` |
| `title` | `str` | required |
| `status` | `int` | required |
| `detail` | `str` | required |
| `instance` | `str \| None` | `None` |
| `correlation_id` | `str \| None` | only present when OpenTelemetry is installed; defaults to the active trace's correlation id |
| `errors` | `list[Any]` | `[]` |

`ErrorDetails.new(detail, **kwargs)` is a convenience constructor that takes `detail` positionally. `ErrorDetailsType` is the alias `type[ErrorDetails]`.

Two helpers build error models dynamically — they are what [`APIError`](exceptions.md) subclassing uses internally:

- `const_type(value, description=None, **kwargs)` returns a `(Literal[value], Field(value, ...))` tuple, i.e. a constant field definition for `create_model`.
- `create_error_model(status, type="about:blank", name=None, title=None, detail=None, **kwargs)` builds an `ErrorDetails` subclass whose `title`, `status` and `type` are constants. `title` defaults to the `HTTPStatus` phrase, `name` to that phrase without spaces, and `detail` to the `HTTPStatus` description. Extra keyword arguments are passed to `create_model` as field definitions; `__base__` selects a different `ErrorDetails` subclass to inherit from.

```python
from fastapi_views.models import create_error_model

NotFoundModel = create_error_model(404)                     # name "NotFound", title "Not Found"
Custom = create_error_model(400, name="QuotaExceeded", title="Quota Exceeded")
```

## Response headers

`ResponseHeaders` is a schema whose fields describe HTTP **response** headers. `get_openapi_headers()` renders it as a mapping of OpenAPI [Header Objects](https://spec.openapis.org/oas/v3.1.0#header-object): `description` is lifted to the top level, the remaining JSON schema is nested under `schema`, required fields get `required: true`, and nullable unions (`X | None`) are collapsed to `X` since a response header is never null.

```python
from pydantic import Field

from fastapi_views.models import ResponseHeaders


class LocationHeaders(ResponseHeaders):
    location: str = Field(description="URL of the created resource")
    x_request_id: str | None = None
```

```python
>>> LocationHeaders.get_openapi_headers()
{'location': {'description': 'URL of the created resource',
              'required': True,
              'schema': {'type': 'string'}},
 'x_request_id': {'schema': {'type': 'string'}}}
```

Note that the field name is used verbatim as the header name, so declare headers exactly as they should appear.

Three places consume a `ResponseHeaders` subclass:

| Where | How |
|-------|-----|
| Route decorators | `@get(...)`, `@post(...)`, `@route(...)`, `@action(...)` accept `response_headers=` — see [Decorators](decorators.md) |
| `ViewRouter` | `ViewRouter(prefix="/items", response_headers=...)` documents them on every route it registers |
| Views | override `get_response_headers(action)` to return the class per action; the headers are documented on that action's success status code |

Both `CacheHeaders` (from the [caching](cache.md) view mixin) and `ConditionalHeaders` (ETag/`Last-Modified` support) are `ResponseHeaders` subclasses.

## Server-Sent Events

| Class | Fields |
|-------|--------|
| `BaseServerSentEvent` | `retry: int \| None`; `__content_type__ = "text/event-stream"` |
| `IdBaseServerSentEvent` | adds `id: UUID` (defaults to `uuid4()`) |
| `AnyServerSentEvent` | adds `id: str` (random UUID string), `event: str`, `data: Any` |

Subclass `BaseServerSentEvent` (or `IdBaseServerSentEvent`) with a literal `event` and a typed `data` field for a strongly typed stream. `get_openapi_schema()` — inherited from `OpenAPIBase` — is what `ServerSentEventsAPIView` uses when registering the route. See [Server Side Events](../usage/sse.md).

---

::: fastapi_views.models
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

::: fastapi_views.models.base
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
