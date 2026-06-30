from collections.abc import Sequence
from datetime import datetime, timezone
from typing import ClassVar
from uuid import UUID

from fastapi import FastAPI, Response
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.cache import (
    CacheMiddleware,
    ConditionalCachedAPIView,
    use_cache,
)
from fastapi_views.cache.backends.memory import InMemoryCache
from fastapi_views.views.viewsets import AsyncReadOnlyAPIViewSet


class ItemSchema(BaseModel):
    id: UUID
    name: str
    price: int
    updated_at: datetime


_ITEMS: dict[UUID, ItemSchema] = {
    UUID(int=1): ItemSchema(
        id=UUID(int=1),
        name="Widget",
        price=10,
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    ),
}


class ItemViewSet(ConditionalCachedAPIView, AsyncReadOnlyAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema

    # Vary the cache key per tenant so cached bodies are not shared across them.
    cache_key_headers: ClassVar[Sequence[str]] = ("X-Tenant-Id",)
    # Document the 304 response and validator headers in the OpenAPI schema.
    conditional_requests = True

    @use_cache(ttl=30)
    async def list(self) -> list[ItemSchema]:
        """Cached for 30s; responses carry ``X-Cache`` and ``Cache-Control``."""
        return list(_ITEMS.values())

    async def retrieve(self, id: UUID) -> ItemSchema | Response | None:
        """Revalidate cheaply with ``Last-Modified`` before building the body."""
        item = _ITEMS.get(id)
        if item is None:
            return None
        # If the client's copy is current, return 304 and skip serialisation;
        # otherwise stamp ``Last-Modified`` on the 200 and return the item.
        return self.check_last_modified(item.updated_at) or item


router = ViewRouter(prefix="/items")
router.register_view(ItemViewSet)

app = FastAPI(title="Cache Example")
# The backend is shared by every cached view via the global cache.
app.add_middleware(CacheMiddleware, backend=InMemoryCache())
app.include_router(router)

configure_app(app)
