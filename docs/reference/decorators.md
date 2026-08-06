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
| `@route(path, methods=[...], **kwargs)` | any (defaults to GET) | 200 |
| `@action(path, *, detail=False, **kwargs)` | any (defaults to GET) | 200 |
| `@sse_route(path, **kwargs)` | GET | 200 (SSE) |

Every decorator also accepts `response_headers=` (a `ResponseHeaders` subclass), which documents headers on the success response and is consumed by the view rather than forwarded to FastAPI.

`@override` (alias for `@annotate`) sets route metadata on an existing CRUD action method (`list`, `retrieve`, `create`, …) — useful for overriding `status_code`, `path`, `summary`, `responses` or `dependencies` of a standard action. It *replaces* the metadata previously attached to that method, so apply it once per method and do not stack it with `@throws` or a route decorator.

## `@action`

`@action` is DRF-style sugar over `@route` for adding an extra routable method to a view:

- the path defaults to the hyphenated method name (`mark_read` → `/mark-read`);
- `detail=True` nests the route under the view's detail route (`detail_route`, `/{id}` by default);
- `response_headers=` (a `ResponseHeaders` subclass) documents headers on the success response.

The response model comes from an explicit `response_model=` argument, otherwise from the method's return annotation, and finally from the view's `response_schema`. `Response` subclasses inside the annotation are ignored, so `-> Article | Response` still documents `Article`.

```python
from uuid import UUID
from fastapi_views.views.functools import action

class ArticleViewSet(AsyncAPIViewSet):
    @action(methods=["POST"], detail=True, response_headers=LocationHeaders)
    async def publish(self, id: UUID) -> Article:  # POST /{id}/publish
        ...
```

`response_headers` is available on every route decorator (`@get`/`@post`/`@route`/`@action`), and `ViewRouter(response_headers=...)` applies them to every route it registers.

## Error utilities

`errors(*exceptions)` builds a FastAPI-compatible `responses` dict from `APIError` subclasses. Bodies are documented as `application/problem+json`, and several errors sharing a status code become an `anyOf` of their models.

`throws(*exceptions)` is a shorthand that wraps `errors` into an `@override` call, so it applies to a **standard** action only — for a method that already has a route decorator, pass `responses=errors(...)` to that decorator instead.

## Exception catching decorators

`@catch(exc_type, **kwargs)` wraps a view method to catch a specific exception type (or a tuple of them) and convert it to an `APIError` response, reading error details from `self.raises` or from the keyword arguments.

`@catch_defined` is similar but catches all exception types listed in `self.raises` automatically.

Both work on sync and async methods and are applied *below* the route decorator:

```python
class ItemView(APIView):
    @get("/{id}")
    @catch(KeyError, status=404)
    async def get_item(self, id: int) -> Item: ...
```

---

::: fastapi_views.views.functools
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_signature_annotations: true
