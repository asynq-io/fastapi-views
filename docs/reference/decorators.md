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

`@override` (alias for `@annotate`) sets route metadata on an existing CRUD action method (`list`, `retrieve`, `create`, …) — useful for overriding `status_code`, `path`, `summary`, `responses` or `dependencies` of a standard action.

Route metadata **merges** across stacked decorators, so `@override`, `@throws` and a route decorator compose in either order. The outer (later-applied) decorator wins on scalar keys such as `status_code` or `summary`, while `responses` maps are unioned — a status declared on both sides is shallow-merged. Every merge builds a fresh dict, so a decorator object reused across several methods never leaks metadata between them:

```python
class ItemView(APIView):
    @get("/{id}", responses=errors(Conflict))
    @throws(NotFound)
    async def get_item(self, id: int) -> ItemSchema:  # documents 404 and 409
        ...
```

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

Custom routes are documented exactly like the generated CRUD actions: the view's `get_response_headers()` headers (called with `action=None`), `ConditionalMixin`'s `ETag` / `Last-Modified` validators and — for safe methods — a `304 Not Modified` all land on the route's success response, resolved from the decorator's own `status_code` and `methods` (defaulting to `200` and `GET`).

## Error utilities

`errors(*exceptions)` builds a FastAPI-compatible `responses` dict from `APIError` subclasses. Bodies are documented as `application/problem+json`, and several *distinct* errors sharing a status code become an `anyOf` of their models.

`throws(*exceptions)` is a shorthand that wraps `errors` into an `@override` call. It works on standard CRUD actions and on methods that already carry a route decorator or another `@override` — the responses compose rather than replace, so stacking order does not matter.

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
