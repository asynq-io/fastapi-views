# Basic usage

FastAPI Views provides three base classes for building views, each with a different level of abstraction. Start with `View` for maximum control, or jump straight to `APIView` for automatic serialization.

---

## `View` — low-level class-based view

`View` is the foundation. It gives you a class-based home for your endpoint logic without imposing any serialization or error-handling conventions. You add routes using the `@get`, `@post`, `@put`, `@patch`, and `@delete` decorators, and you return FastAPI `Response` objects directly — exactly as you would in a plain function-based route.

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

All decorators accept the same keyword arguments as FastAPI's `@app.get` / `@router.get` (e.g., `status_code`, `response_model`, `tags`, `summary`, `dependencies`).

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
        import json
        user = self.db.get_user(user_id)
        return Response(content=json.dumps(user), media_type="application/json")
```

---

## `APIView` — view with automatic serialization

`APIView` extends `View` with Pydantic v2 serialization and built-in error handling. Set `response_schema` to a Pydantic model and return plain dicts or model instances — the view converts them to a validated JSON response automatically.

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

### Error handling with `raises`

Define a mapping from Python exceptions to API error details using the `raises` class variable, then use the `@catch` decorator on individual methods:

```python
from fastapi_views.views import APIView, get
from fastapi_views.views.functools import catch

class ItemAPIView(APIView):
    response_schema = ItemSchema
    raises = {
        KeyError: {"status": 404, "detail": "Item not found"},
        PermissionError: {"status": 403, "detail": "Access denied"},
    }

    @get("/{id}")
    @catch(KeyError)
    async def get_item(self, id: int) -> ItemSchema:
        return items[id]  # KeyError → 404 Not Found
```

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

Available async action mixins:

| Mixin | HTTP method | Path |
|-------|------------|------|
| `AsyncListAPIView` | GET | `/` |
| `AsyncCreateAPIView` | POST | `/` |
| `AsyncRetrieveAPIView` | GET | `/{id}` |
| `AsyncUpdateAPIView` | PUT | `/{id}` |
| `AsyncPartialUpdateAPIView` | PATCH | `/{id}` |
| `AsyncDestroyAPIView` | DELETE | `/{id}` |

Each mixin has a synchronous counterpart without the `Async` prefix (e.g., `ListAPIView`, `RetrieveAPIView`).

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

---

## Complete example

```python
--8<-- "examples/basic.py"
```
