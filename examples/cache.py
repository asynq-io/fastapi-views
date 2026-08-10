from collections.abc import Sequence
from datetime import datetime, timezone
from typing import ClassVar
from uuid import UUID

from fastapi import FastAPI, Response
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.cache import (
    CacheControl,
    CacheHeaders,
    CacheMiddleware,
    ConditionalCachedAPIView,
    cache,
    use_cache,
)
from fastapi_views.cache.backends.memory import InMemoryCache
from fastapi_views.models import ResponseHeaders
from fastapi_views.types import Action
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


@cache("items:index", ttl=30)
async def load_index() -> dict[UUID, ItemSchema]:
    """Any async function can be cached; the result round-trips through JSON."""
    return _ITEMS


class ItemViewSet(ConditionalCachedAPIView, AsyncReadOnlyAPIViewSet):
    """Server-side caching plus ``ETag`` / ``Last-Modified`` revalidation.

    ``etag = True`` hashes a strong validator from the (possibly cached) body, so
    even a cache hit can be answered with ``304``; ``conditional_requests = True``
    documents the validators ``retrieve`` produces imperatively.
    """

    api_component_name = "Item"
    response_schema = ItemSchema

    # Vary the cache key per tenant so cached bodies are not shared across them.
    cache_key_headers: ClassVar[Sequence[str]] = ("X-Tenant-Id",)
    etag = True
    conditional_requests = True

    @classmethod
    def get_response_headers(
        cls, action: Action | None = None
    ) -> type[ResponseHeaders] | None:
        """Only ``list`` is cached, so only it emits the cache headers."""
        return CacheHeaders if action == "list" else None

    @use_cache(ttl=30, cache_control=CacheControl(private=True))
    async def list(self) -> list[ItemSchema]:
        """Cached for 30s; ``ttl`` fills in ``Cache-Control: private, max-age=30``."""
        return list(_ITEMS.values())

    async def retrieve(self, id: UUID) -> ItemSchema | Response | None:
        """Revalidate cheaply with ``Last-Modified`` before building the body."""
        item = (await load_index()).get(id)
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
