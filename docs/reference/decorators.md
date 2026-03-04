# Decorators and utilities

Route decorators, error utilities, and SSE helpers used inside view classes. Import from `fastapi_views.views` or `fastapi_views.views.functools`.

## Route decorators

Use these inside any `View` or `APIView` subclass to register additional endpoints. They accept the same keyword arguments as FastAPI's `@app.get` / `@router.post` etc.

| Decorator | HTTP method | Default status |
|-----------|------------|----------------|
| `@get(path, **kwargs)` | GET | 200 |
| `@post(path, **kwargs)` | POST | 201 |
| `@put(path, **kwargs)` | PUT | 200 |
| `@patch(path, **kwargs)` | PATCH | 200 |
| `@delete(path, **kwargs)` | DELETE | 204 |
| `@route(path, methods, **kwargs)` | Any | — |
| `@sse_route(path, **kwargs)` | GET | 200 (SSE) |

`@override` (alias for `@annotate`) sets metadata on an existing CRUD action method — useful for overriding `status_code` or adding `responses` to a standard action.

## Error utilities

`errors(*exceptions)` builds a FastAPI-compatible `responses` dict from a list of `APIError` subclasses. `throws(*exceptions)` is a shorthand that wraps `errors` into an `@override` call.

## Exception catching decorators

`@catch(exc_type, **kwargs)` wraps a view method to catch a specific exception type and convert it to an `APIError` response, reading error details from `self.raises` or the keyword arguments.

`@catch_defined` is similar but catches all exception types listed in `self.raises` automatically.

---

::: fastapi_views.views.functools
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_signature_annotations: true
