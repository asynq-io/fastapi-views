# Basic usage

FastAPI Views provides two base classes for building views — `View` for maximum control and `APIView` for automatic serialization and error handling — plus a set of single-action `*APIView` mixins you can combine freely.

---

## `View` — low-level class-based view

`View` is the foundation. It gives you a class-based home for your endpoint logic without imposing any `response_schema` or error-handling conventions. You add routes using the `@get`, `@post`, `@put`, `@patch`, and `@delete` decorators, and you can return FastAPI `Response` objects directly — exactly as you would in a plain function-based route.

A returned `Response` is passed through untouched. Any other value is JSON-serialized with a Pydantic `TypeAdapter` built from the method's return annotation (or from an explicit `response_model=`), and `str`/`bytes` are sent as `text/plain`.

```python
from fastapi import Response
from fastapi_views.views import View, get, post

class BasicView(View):
    @get("")
    async def get_item(self) -> Response:
        return Response(content="hello", media_type="text/plain")

    @post("")
    async def create_item(self) -> Response:
        return Response(status_code=201)
```

### Route decorators

| Decorator | HTTP method | Default status code |
|-----------|------------|---------------------|
| `@get(path)` | GET | 200 |
| `@post(path)` | POST | 201 |
| `@put(path)` | PUT | 200 |
| `@patch(path)` | PATCH | 200 |
| `@delete(path)` | DELETE | 204 |
| `@route(path, methods=[...])` | any (defaults to GET) | 200 |
| `@action(path, *, detail=False)` | any (defaults to GET) | 200 |

All decorators accept the same keyword arguments as FastAPI's `@app.get` / `@router.get` (e.g., `status_code`, `response_model`, `tags`, `summary`, `responses`, `dependencies`), plus `response_headers=` (a `ResponseHeaders` subclass) to document headers on the success response.

`@action` additionally defaults the path to the hyphenated method name and can nest under the detail route — see [ViewSets](viewset.md#custom-actions-with-action).

To change route options of a *standard* CRUD action (`list`, `retrieve`, `create`, …) — which has no decorator of its own — use `@override` (an alias of `@annotate`):

```python
from fastapi_views.views import AsyncCreateAPIView, override

class ItemView(AsyncCreateAPIView):
    response_schema = ItemSchema

    @override(status_code=200, summary="Upsert an item")
    async def create(self, item: ItemSchema) -> ItemSchema:
        ...
```

### Accessing the request and response

Every view instance receives `request` and `response` objects injected by FastAPI's dependency system:

```python
from fastapi import Response
from fastapi_views.views import View, get

class EchoView(View):
    @get("/echo")
    async def echo(self) -> Response:
        user_agent = self.request.headers.get("user-agent", "unknown")
        return Response(content=f"Your UA: {user_agent}")
```

### Using FastAPI dependencies

Inject dependencies by overriding `__init__`:

```python
from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse
from fastapi_views.views import View, get

class Database:
    def get_user(self, user_id: int) -> dict:
        return {"id": user_id, "name": "Alice"}

def get_db() -> Database:
    return Database()

class UserView(View):
    def __init__(
        self,
        request: Request,
        response: Response,
        db: Database = Depends(get_db),
    ) -> None:
        super().__init__(request, response)
        self.db = db

    @get("/{user_id}")
    async def get_user(self, user_id: int) -> Response:
        user = self.db.get_user(user_id)
        return JSONResponse(user)
```

---

## `APIView` — view with automatic serialization

`APIView` extends `View` with alias-aware Pydantic v2 serialization, per-action dependencies, OpenAPI error documentation and exception handling. Set `response_schema` to a Pydantic model and return plain dicts or model instances — the view converts them to a validated JSON response automatically.

`response_schema` is the schema of the standard CRUD actions and the OpenAPI fallback for custom routes; a custom route serializes against its own return annotation (or `response_model=`) when it has one.

```python
from pydantic import BaseModel
from fastapi_views.views import APIView, get

class ItemSchema(BaseModel):
    id: int
    name: str

class ItemAPIView(APIView):
    response_schema = ItemSchema

    @get("")
    async def get_item(self) -> ItemSchema:
        # Return a dict — it will be validated against ItemSchema
        return {"id": 1, "name": "Widget"}
```

### Serialization settings

| Attribute | Default | Purpose |
|-----------|---------|---------|
| `response_schema` | `None` | Schema used to validate and serialize response bodies |
| `validate_response` | `True` | Validate the returned value before dumping it; set to `False` to dump without validation |
| `from_attributes` | `None` | Read values off arbitrary objects (ORM instances) during validation |
| `default_serializer_options` | `{"by_alias": True}` | Pydantic dump options; copied onto `self.serializer_options` per request |

`self.serializer_options` and `self.validation_context` are per-request, so a handler can adjust them before returning:

```python
class ItemAPIView(APIView):
    response_schema = ItemSchema

    @get("")
    async def get_item(self) -> ItemSchema:
        self.serializer_options["exclude_none"] = True
        return {"id": 1, "name": "Widget"}
```

### Returning `None` triggers 404

When a detail view inherits `DetailViewMixin` (used internally by retrieve/update/destroy views), returning `None` from your handler automatically raises a `404 Not Found` response.

```python
from typing import Optional
from fastapi_views.views import AsyncRetrieveAPIView

class ItemView(AsyncRetrieveAPIView):
    response_schema = ItemSchema

    async def retrieve(self, id: int) -> Optional[ItemSchema]:
        item = db.get(id)
        return item  # None → 404 Not Found
```

`DetailViewMixin` is also what defines the detail path and the 404 message:

| Attribute | Default | Purpose |
|-----------|---------|---------|
| `detail_route` | `"/{id}"` | Path suffix appended for detail actions (and `@action(detail=True)`) |
| `raise_on_none` | `True` | Raise `NotFound` when the handler returns `None` |
| `error_message` | `"{} does not exist"` | Message template, formatted with the view name |

Override `get_detail_route(action)` if a single view needs different detail paths per action.

### Error handling with `raises`

Define a mapping from Python exceptions to API error details using the `raises` class variable, then use the `@catch` decorator on individual methods:

```python
from typing import ClassVar

from fastapi_views.views import APIView, get
from fastapi_views.views.functools import catch, catch_defined

class ItemAPIView(APIView):
    response_schema = ItemSchema
    raises: ClassVar[dict] = {
        KeyError: {"status": 404, "detail": "Item not found"},
        PermissionError: {"status": 403, "detail": "Access denied"},
    }

    @get("/{id}")
    @catch(KeyError)
    async def get_item(self, id: int) -> ItemSchema:
        return items[id]  # KeyError → 404 Not Found

    @get("/{id}/related")
    @catch_defined
    async def get_related(self, id: int) -> ItemSchema:
        # every exception type listed in ``raises`` is caught here
        return items[id]
```

A `raises` value may also be a plain string, which is used as the `detail` (the status then defaults to `400`).

You can also pass error details directly to `@catch`:

```python
from fastapi_views.views.functools import catch

class ItemAPIView(APIView):
    response_schema = ItemSchema

    @get("/{id}")
    @catch(KeyError, status=404, detail="Item not found")
    async def get_item(self, id: int) -> ItemSchema:
        return items[id]
```

Both decorators work on sync and async methods, and go *below* the route decorator.

### Documenting errors in OpenAPI

`errors` is a class attribute listing `APIError` subclasses documented on **every** route of the view. On top of it, `APIView.default_errors` (`BadRequest`) is always documented, and the CRUD actions add the errors they can raise themselves (`NotFound` for retrieve/update, `Conflict` for create).

```python
from fastapi_views.exceptions import Conflict, Forbidden
from fastapi_views.views import AsyncRetrieveAPIView, throws

class ItemView(AsyncRetrieveAPIView):
    response_schema = ItemSchema
    errors = (Forbidden,)

    @throws(Conflict)
    async def retrieve(self, id: int) -> ItemSchema | None:
        ...
```

`@throws(*exceptions)` documents extra errors for a single **standard** action. For methods that already carry a route decorator, pass the responses to that decorator instead — `errors(*exceptions)` builds the mapping:

```python
from fastapi_views.exceptions import NotFound
from fastapi_views.views import APIView, get
from fastapi_views.views.functools import errors

class ItemAPIView(APIView):
    response_schema = ItemSchema

    @get("/{id}", responses=errors(NotFound))
    async def get_item(self, id: int) -> ItemSchema:
        ...
```

Error bodies are documented as `application/problem+json`, and several errors sharing a status code are documented as an `anyOf`. A `responses` mapping given on a method (directly or via `@throws`) *replaces* the entries the action generates by itself (the default `400`, and `404`/`409` for detail/create actions), so list every error you want documented there. The class-level `errors` tuple is always merged in.

---

## Per-action dependencies

`action_dependencies` maps an action name to route-level dependencies, so each generated route only gets the dependencies that belong to it. Router-level dependencies passed to `register_view` are merged with these, not replaced.

```python
from typing import ClassVar

from fastapi import Depends
from fastapi_views.views import AsyncListAPIView, AsyncCreateAPIView

class ItemView(AsyncListAPIView, AsyncCreateAPIView):
    response_schema = ItemSchema
    action_dependencies: ClassVar = {
        "list": [Depends(read_only)],
        "create": [Depends(require_editor)],
    }
```

Override the `get_dependencies(action)` classmethod for fully dynamic behaviour. See [Authentication](auth.md#per-action-dependencies) for scope-based examples.

---

## Documenting response headers

Override the `get_response_headers(action)` classmethod to attach a `ResponseHeaders` model to an action's success response in the OpenAPI schema:

```python
from fastapi_views.models import ResponseHeaders
from fastapi_views.views import AsyncListAPIView

class PaginationHeaders(ResponseHeaders):
    x_total_count: int

class ItemView(AsyncListAPIView):
    response_schema = ItemSchema

    @classmethod
    def get_response_headers(cls, action=None):
        return PaginationHeaders if action == "list" else None

    async def list(self) -> list[ItemSchema]:
        items = db.list_items()
        self.response.headers["x-total-count"] = str(len(items))
        return items
```

Headers can also be declared per route with `response_headers=` on any route decorator, or for a whole router with `ViewRouter(response_headers=...)`.

---

## Conditional requests

`ConditionalMixin` adds `ETag` / `Last-Modified` validators and `304 Not Modified` handling to any view, with no cache backend involved. The cheapest form compares a validator you already have (a version column, `updated_at`) and short-circuits before the body is built:

```python
from fastapi import Response
from fastapi_views.views import AsyncRetrieveAPIView
from fastapi_views.views.mixins import ConditionalMixin

class ItemView(ConditionalMixin, AsyncRetrieveAPIView):
    response_schema = ItemSchema

    async def retrieve(self, id: int) -> ItemSchema | Response | None:
        item = db.get(id)
        if item is None:
            return None
        # 304 when the client's copy is current, otherwise stamp Last-Modified
        return self.check_last_modified(item.updated_at) or item
```

`check_etag(etag)` is the `ETag` counterpart, and `not_modified(...)`, `etag_matches(...)`, `not_modified_since(...)` are available for hand-rolled logic. See [Caching](cache.md#conditional-requests-with-conditionalmixin) for the automatic (body-hashing) variant and OpenAPI documentation.

---

## Composing views from mixins

Rather than using a full `APIViewSet`, you can combine individual action mixins to expose only the HTTP methods your resource needs:

```python
from fastapi import Depends, Request, Response
from pydantic import BaseModel
from fastapi_views.views.api import AsyncListAPIView, AsyncRetrieveAPIView

class APIModel(BaseModel):
    id: int
    name: str

class Database:
    def list_items(self):
        return [{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}]

def get_db() -> Database:
    return Database()

class ReadAPIView(AsyncListAPIView, AsyncRetrieveAPIView):
    response_schema = APIModel

    def __init__(
        self, request: Request, response: Response, db: Database = Depends(get_db)
    ) -> None:
        super().__init__(request, response)
        self.db = db

    async def list(self) -> list[APIModel]:
        # Response model is automatically list[APIModel]
        return self.db.list_items()

    async def retrieve(self, id: int) -> APIModel | None:
        for item in self.db.list_items():
            if item["id"] == id:
                return item
        return None  # Triggers 404 Not Found
```

Available async action mixins (paths are relative to the prefix passed to `register_view`):

| Mixin | Action | HTTP method | Path | Status |
|-------|--------|------------|------|--------|
| `AsyncListAPIView` | `list` | GET | *(prefix)* | 200 |
| `AsyncCreateAPIView` | `create` | POST | *(prefix)* | 201 |
| `AsyncRetrieveAPIView` | `retrieve` | GET | `/{id}` | 200 |
| `AsyncUpdateAPIView` | `update` | PUT | `/{id}` | 200 |
| `AsyncPartialUpdateAPIView` | `partial_update` | PATCH | `/{id}` | 200 |
| `AsyncDestroyAPIView` | `destroy` | DELETE | `/{id}` | 204 |

Each mixin has a synchronous counterpart without the `Async` prefix (e.g., `ListAPIView`, `RetrieveAPIView`).

A few extra hooks come with these mixins:

- `AsyncListAPIView.response_schema_as_list` (default `True`) wraps the schema in `list[...]` for the `list` action — set it to `False` when `list` returns an envelope such as a paginated page.
- `AsyncCreateAPIView.get_location(obj)` returns a URL to send as the `Location` header of a `201`; `return_on_create = False` responds with an empty body instead of the created object.
- `return_on_update = False` does the same for `update` / `partial_update`.

---

## Registering views with `ViewRouter`

`ViewRouter` extends FastAPI's `APIRouter`. Use `register_view` to add all of a view's routes at once:

```python
from fastapi import FastAPI
from fastapi_views import ViewRouter, configure_app

router = ViewRouter(prefix="/items")
router.register_view(ReadAPIView)

app = FastAPI()
app.include_router(router)
configure_app(app)
```

You can pass extra keyword arguments to `register_view` — they are forwarded to every route registered from that view (e.g., `tags`, `dependencies`):

```python
from fastapi import Depends
from fastapi.security import HTTPBearer

security = HTTPBearer()

router.register_view(ReadAPIView, dependencies=[Depends(security)])
```

`dependencies` are **merged** with the view's own `action_dependencies` (router-level ones run first) instead of replacing them.

Two more things `ViewRouter` does for you:

- **Route ordering** — routes are registered most-specific-first, so a static route such as `/items/stats` is never shadowed by `/items/{id}`.
- **Router-wide response headers** — `ViewRouter(response_headers=...)` documents a `ResponseHeaders` model on the success response of every route it registers:

```python
from fastapi_views import ViewRouter
from fastapi_views.models import ResponseHeaders

class TracingHeaders(ResponseHeaders):
    x_request_id: str

router = ViewRouter(prefix="/items", response_headers=TracingHeaders)
router.register_view(ReadAPIView)
```

Registering an abstract view (one with unimplemented action methods) raises a `TypeError`.

---

## Complete example

```python
--8<-- "examples/basic.py"
```
