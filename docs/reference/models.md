# Models

Shared Pydantic model base classes and the `ErrorDetails` / `ServerSentEvent` types. Import from `fastapi_views.models`.

## Base schemas

| Class | Description |
|-------|-------------|
| `BaseSchema` | Pydantic `BaseModel` with `use_enum_values`, `populate_by_name`, and `from_attributes` enabled |
| `CamelCaseSchema` | `BaseSchema` with `alias_generator = to_camel` for camelCase JSON keys |
| `IdSchema` | `BaseSchema` with a `UUID` `id` field |
| `CreatedUpdatedSchema` | `BaseSchema` with `created_at` and `updated_at` datetime fields |
| `IdCreatedUpdatedSchema` | Combines `IdSchema` and `CreatedUpdatedSchema` |

## Error model

`ErrorDetails` is the base Pydantic model for all RFC 9457 error responses. When OpenTelemetry is installed, it conditionally gains a `correlation_id` field populated from the active trace context.

## Server-Sent Events

`ServerSentEvent[D]` is the generic model that wraps each SSE payload. Its `get_openapi_schema()` class method returns an OpenAPI-compatible schema dict used by `ServerSentEventsAPIView` when registering routes.

---

::: fastapi_views.models
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
