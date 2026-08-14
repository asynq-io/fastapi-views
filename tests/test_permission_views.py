from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from joserfc import jwk
from pydantic import BaseModel, Field
from starlette.status import (
    HTTP_200_OK,
    HTTP_204_NO_CONTENT,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)

from fastapi_views import ViewRouter
from fastapi_views.auth.jwt import JWTAuth, JWTConfig
from fastapi_views.handlers import add_error_handlers
from fastapi_views.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
    IsOwner,
    set_app_auth,
)
from fastapi_views.permissions.views import AsyncProtectedGenericViewSet

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Sequence

    from fastapi_views.filters.models import BasePaginationFilter
    from fastapi_views.views.generics import Page


OWNER_ID = UUID(int=1)
OTHER_ID = UUID(int=2)


class ItemId(BaseModel):
    id: UUID


class Item(ItemId):
    name: str
    owner_id: UUID


class CreateItem(BaseModel):
    name: str
    owner_id: UUID


class UpdateItem(BaseModel):
    name: str


class User(BaseModel):
    user_id: UUID
    permissions: list[str] = Field(default_factory=list)


def make_user(token: dict[str, Any]) -> User:
    return User(user_id=UUID(token["sub"]))


class ItemRepository:
    """In-memory repository that records how often it is read from."""

    def __init__(self) -> None:
        self.items: dict[UUID, Item] = {}
        self.get_calls = 0

    async def create(self, **kwargs: Any) -> Item | None:
        item = Item(id=uuid4(), **kwargs)
        self.items[item.id] = item
        return item

    async def get(self, **kwargs: Any) -> Item | None:
        self.get_calls += 1
        return self.items.get(kwargs["id"])

    async def get_filtered_page(
        self, filter: BasePaginationFilter, **_: Any
    ) -> Page[Item]:
        raise NotImplementedError

    async def list(self, **_: Any) -> Sequence[Item]:
        return list(self.items.values())

    async def delete_one(self, **kwargs: Any) -> Item | None:
        return self.items.pop(kwargs["id"], None)

    async def update_one(self, values: dict[str, Any], **kwargs: Any) -> Item | None:
        item = self.items.get(kwargs["id"])
        if item is None:
            return None
        updated = item.model_copy(update=values)
        self.items[item.id] = updated
        return updated


_repository = ItemRepository()
_open_repository = ItemRepository()
_idempotent_repository = ItemRepository()
_authenticated_repository = ItemRepository()
_composite_owner_repository = ItemRepository()
_composite_request_repository = ItemRepository()


class ProtectedItemViewSet(AsyncProtectedGenericViewSet):
    api_component_name = "Item"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = UpdateItem
    partial_update_schema = UpdateItem
    filter = None
    from_attributes = True
    repository = _repository
    permission_classes: ClassVar = [IsOwner("user_id", "owner_id")]


class OpenItemViewSet(AsyncProtectedGenericViewSet):
    api_component_name = "OpenItem"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = UpdateItem
    partial_update_schema = UpdateItem
    filter = None
    from_attributes = True
    repository = _open_repository


class IdempotentItemViewSet(AsyncProtectedGenericViewSet):
    api_component_name = "IdempotentItem"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = UpdateItem
    partial_update_schema = UpdateItem
    filter = None
    from_attributes = True
    raise_on_none = False
    repository = _idempotent_repository
    permission_classes: ClassVar = [IsOwner("user_id", "owner_id")]


class AuthenticatedItemViewSet(AsyncProtectedGenericViewSet):
    api_component_name = "AuthenticatedItem"
    primary_key = ItemId
    response_schema = Item
    create_schema = CreateItem
    update_schema = UpdateItem
    partial_update_schema = UpdateItem
    filter = None
    from_attributes = True
    repository = _authenticated_repository
    permission_classes: ClassVar = [IsAuthenticated]


class CompositeOwnerItemViewSet(AuthenticatedItemViewSet):
    api_component_name = "CompositeOwnerItem"
    repository = _composite_owner_repository
    permission_classes: ClassVar = [IsAuthenticated & IsOwner("user_id", "owner_id")]


class CompositeRequestItemViewSet(AuthenticatedItemViewSet):
    api_component_name = "CompositeRequestItem"
    repository = _composite_request_repository
    permission_classes: ClassVar = [IsAuthenticated & IsAuthenticatedOrReadOnly]


@pytest.fixture(autouse=True)
def _reset_repositories() -> Generator[None, None, None]:
    for repo in (
        _repository,
        _open_repository,
        _idempotent_repository,
        _authenticated_repository,
        _composite_owner_repository,
        _composite_request_repository,
    ):
        repo.items.clear()
        repo.get_calls = 0
    yield
    set_app_auth(None)


@pytest.fixture
def auth() -> JWTAuth:
    jwt_auth = JWTAuth(
        JWTConfig(key=jwk.OctKey.generate_key(256), algorithms=["HS256"]),
        custom_class=make_user,
    )
    set_app_auth(jwt_auth)
    return jwt_auth


def bearer(auth: JWTAuth, user_id: UUID) -> dict[str, str]:
    token = auth.create_access_token({"sub": str(user_id)}).access_token
    return {"Authorization": f"Bearer {token}"}


async def make_client(view_cls: type) -> AsyncGenerator[AsyncClient, None]:
    app = FastAPI()
    add_error_handlers(app)
    router = ViewRouter()
    router.register_view(view_cls, prefix="/items")
    app.include_router(router)
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
async def client(auth) -> AsyncGenerator[AsyncClient, None]:
    async for c in make_client(ProtectedItemViewSet):
        yield c


@pytest.fixture
async def open_client() -> AsyncGenerator[AsyncClient, None]:
    async for c in make_client(OpenItemViewSet):
        yield c


@pytest.fixture
async def idempotent_client(auth) -> AsyncGenerator[AsyncClient, None]:
    async for c in make_client(IdempotentItemViewSet):
        yield c


@pytest.fixture
async def authenticated_client(auth) -> AsyncGenerator[AsyncClient, None]:
    async for c in make_client(AuthenticatedItemViewSet):
        yield c


@pytest.fixture
async def composite_owner_client(auth) -> AsyncGenerator[AsyncClient, None]:
    async for c in make_client(CompositeOwnerItemViewSet):
        yield c


@pytest.fixture
async def composite_request_client(auth) -> AsyncGenerator[AsyncClient, None]:
    async for c in make_client(CompositeRequestItemViewSet):
        yield c


def seed(owner_id: UUID = OWNER_ID, repo: ItemRepository | None = None) -> Item:
    item = Item(id=uuid4(), name="original", owner_id=owner_id)
    (repo or _repository).items[item.id] = item
    return item


@pytest.mark.anyio
async def test_update_as_owner_succeeds(client, auth):
    item = seed()
    response = await client.put(
        f"/items/{item.id}", json={"name": "renamed"}, headers=bearer(auth, OWNER_ID)
    )
    assert response.status_code == HTTP_200_OK
    assert response.json()["name"] == "renamed"
    assert _repository.items[item.id].name == "renamed"


@pytest.mark.anyio
async def test_partial_update_as_owner_succeeds(client, auth):
    item = seed()
    response = await client.patch(
        f"/items/{item.id}", json={"name": "patched"}, headers=bearer(auth, OWNER_ID)
    )
    assert response.status_code == HTTP_200_OK
    assert _repository.items[item.id].name == "patched"


@pytest.mark.anyio
async def test_destroy_as_owner_succeeds(client, auth):
    item = seed()
    response = await client.delete(f"/items/{item.id}", headers=bearer(auth, OWNER_ID))
    assert response.status_code == HTTP_204_NO_CONTENT
    assert item.id not in _repository.items


@pytest.mark.anyio
async def test_update_as_non_owner_is_forbidden(client, auth):
    item = seed()
    response = await client.put(
        f"/items/{item.id}", json={"name": "renamed"}, headers=bearer(auth, OTHER_ID)
    )
    assert response.status_code == HTTP_403_FORBIDDEN
    assert _repository.items[item.id].name == "original"


@pytest.mark.anyio
async def test_partial_update_as_non_owner_is_forbidden(client, auth):
    item = seed()
    response = await client.patch(
        f"/items/{item.id}", json={"name": "patched"}, headers=bearer(auth, OTHER_ID)
    )
    assert response.status_code == HTTP_403_FORBIDDEN
    assert _repository.items[item.id].name == "original"


@pytest.mark.anyio
async def test_destroy_as_non_owner_is_forbidden(client, auth):
    item = seed()
    response = await client.delete(f"/items/{item.id}", headers=bearer(auth, OTHER_ID))
    assert response.status_code == HTTP_403_FORBIDDEN
    assert item.id in _repository.items


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("put", {"json": {"name": "renamed"}}),
        ("patch", {"json": {"name": "patched"}}),
        ("delete", {}),
    ],
)
async def test_missing_object_returns_404(client, auth, method, kwargs):
    response = await getattr(client, method)(
        f"/items/{uuid4()}", headers=bearer(auth, OWNER_ID), **kwargs
    )
    assert response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_destroy_without_permissions_skips_object_fetch(open_client):
    item = seed(repo=_open_repository)
    response = await open_client.delete(f"/items/{item.id}")
    assert response.status_code == HTTP_204_NO_CONTENT
    assert _open_repository.get_calls == 0
    assert item.id not in _open_repository.items


@pytest.mark.anyio
async def test_update_without_permissions_skips_object_fetch(open_client):
    item = seed(repo=_open_repository)
    response = await open_client.put(f"/items/{item.id}", json={"name": "renamed"})
    assert response.status_code == HTTP_200_OK
    assert _open_repository.get_calls == 0
    assert _open_repository.items[item.id].name == "renamed"


@pytest.mark.anyio
async def test_destroy_missing_object_without_raise_on_none_is_noop(
    idempotent_client, auth
):
    response = await idempotent_client.delete(
        f"/items/{uuid4()}", headers=bearer(auth, OWNER_ID)
    )
    assert response.status_code == HTTP_204_NO_CONTENT


@pytest.mark.anyio
async def test_update_with_request_level_permission_skips_object_fetch(
    authenticated_client, auth
):
    item = seed(repo=_authenticated_repository)
    response = await authenticated_client.put(
        f"/items/{item.id}", json={"name": "renamed"}, headers=bearer(auth, OWNER_ID)
    )
    assert response.status_code == HTTP_200_OK
    assert _authenticated_repository.get_calls == 0
    assert _authenticated_repository.items[item.id].name == "renamed"


@pytest.mark.anyio
async def test_update_with_object_permission_fetches_object(client, auth):
    item = seed()
    response = await client.put(
        f"/items/{item.id}", json={"name": "renamed"}, headers=bearer(auth, OWNER_ID)
    )
    assert response.status_code == HTTP_200_OK
    assert _repository.get_calls == 1


@pytest.mark.anyio
async def test_composite_with_object_child_is_enforced(composite_owner_client, auth):
    item = seed(repo=_composite_owner_repository)
    response = await composite_owner_client.put(
        f"/items/{item.id}", json={"name": "renamed"}, headers=bearer(auth, OTHER_ID)
    )
    assert response.status_code == HTTP_403_FORBIDDEN
    assert _composite_owner_repository.get_calls == 1
    assert _composite_owner_repository.items[item.id].name == "original"


@pytest.mark.anyio
async def test_composite_of_request_level_children_skips_object_fetch(
    composite_request_client, auth
):
    item = seed(repo=_composite_request_repository)
    response = await composite_request_client.put(
        f"/items/{item.id}", json={"name": "renamed"}, headers=bearer(auth, OTHER_ID)
    )
    assert response.status_code == HTTP_200_OK
    assert _composite_request_repository.get_calls == 0
