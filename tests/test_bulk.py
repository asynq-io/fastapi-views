from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_CONTENT,
)

from fastapi_views import ViewRouter, configure_app
from fastapi_views.filters.models import BaseFilter
from fastapi_views.views.bulk import (
    AsyncBulkAPIViewSet,
    AsyncGenericBulkCreateAPIView,
    AsyncGenericBulkDestroyAPIView,
    BulkAPIViewSet,
)

from .utils import view_client

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class Item(BaseModel):
    id: UUID
    name: str


class CreateItem(BaseModel):
    name: str


class UpdateItem(BaseModel):
    id: UUID
    name: str


class NameFilter(BaseFilter):
    name: str | None = None


class RecordingAsyncRepository:
    def __init__(self) -> None:
        self.bulk_create_options: list[dict[str, Any]] = []
        self.bulk_update_options: list[dict[str, Any]] = []
        self.delete_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def bulk_create(
        self, items: Sequence[Mapping[str, Any]], **options: Any
    ) -> list[dict[str, Any]]:
        self.bulk_create_options.append(options)
        return [{"id": uuid4(), **item} for item in items]

    async def bulk_update(
        self, items: Sequence[Mapping[str, Any]], **options: Any
    ) -> list[dict[str, Any]]:
        self.bulk_update_options.append(options)
        return [dict(item) for item in items]

    async def delete(self, *args: Any, **kwargs: Any) -> None:
        self.delete_calls.append((args, kwargs))


class RecordingSyncRepository:
    def __init__(self) -> None:
        self.bulk_create_options: list[dict[str, Any]] = []
        self.bulk_update_options: list[dict[str, Any]] = []
        self.delete_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def bulk_create(
        self, items: Sequence[Mapping[str, Any]], **options: Any
    ) -> list[dict[str, Any]]:
        self.bulk_create_options.append(options)
        return [{"id": uuid4(), **item} for item in items]

    def bulk_update(
        self, items: Sequence[Mapping[str, Any]], **options: Any
    ) -> list[dict[str, Any]]:
        self.bulk_update_options.append(options)
        return [dict(item) for item in items]

    def delete(self, *args: Any, **kwargs: Any) -> None:
        self.delete_calls.append((args, kwargs))


def build_app(view: type, prefix: str = "/items") -> FastAPI:
    app = FastAPI()
    router = ViewRouter(prefix=prefix)
    router.register_view(view)
    app.include_router(router)
    return app


@pytest.mark.anyio
async def test_async_bulk_create():
    class ItemViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = RecordingAsyncRepository()

    async with view_client(ItemViewSet) as client:
        response = await client.post(
            "/test/bulk-create", json=[{"name": "a"}, {"name": "b"}]
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert [item["name"] for item in data] == ["a", "b"]
        assert all(UUID(item["id"]) for item in data)


@pytest.mark.anyio
async def test_async_bulk_update():
    class ItemViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = RecordingAsyncRepository()

    item_id = str(uuid4())
    async with view_client(ItemViewSet) as client:
        response = await client.put(
            "/test/bulk-update", json=[{"id": item_id, "name": "updated"}]
        )
        assert response.status_code == HTTP_200_OK
        assert response.json() == [{"id": item_id, "name": "updated"}]


@pytest.mark.anyio
async def test_async_bulk_delete_forwards_filter_kwargs():
    repo = RecordingAsyncRepository()

    class ItemViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = repo

    async with view_client(ItemViewSet) as client:
        response = await client.delete("/test/bulk-delete", params={"name": "widget"})
        assert response.status_code == HTTP_204_NO_CONTENT
        assert response.content == b""
        assert repo.delete_calls == [((), {"name": "widget"})]


@pytest.mark.anyio
async def test_bulk_create_without_return():
    class ItemViewSet(AsyncBulkAPIViewSet):
        return_on_create = False
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = RecordingAsyncRepository()

    async with view_client(ItemViewSet) as client:
        response = await client.post("/test/bulk-create", json=[{"name": "a"}])
        assert response.status_code == HTTP_201_CREATED
        assert response.content == b""


@pytest.mark.anyio
async def test_bulk_update_without_return():
    class ItemViewSet(AsyncBulkAPIViewSet):
        return_on_update = False
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = RecordingAsyncRepository()

    async with view_client(ItemViewSet) as client:
        response = await client.put(
            "/test/bulk-update", json=[{"id": str(uuid4()), "name": "a"}]
        )
        assert response.status_code == HTTP_200_OK
        assert response.content == b""


@pytest.mark.anyio
async def test_sync_bulk_viewset_end_to_end():
    repo = RecordingSyncRepository()

    class SyncItemViewSet(BulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = repo

    async with view_client(SyncItemViewSet) as client:
        created = await client.post("/test/bulk-create", json=[{"name": "a"}])
        assert created.status_code == HTTP_201_CREATED
        assert [item["name"] for item in created.json()] == ["a"]

        item_id = created.json()[0]["id"]
        updated = await client.put(
            "/test/bulk-update", json=[{"id": item_id, "name": "b"}]
        )
        assert updated.status_code == HTTP_200_OK
        assert updated.json() == [{"id": item_id, "name": "b"}]

        deleted = await client.delete("/test/bulk-delete", params={"name": "b"})
        assert deleted.status_code == HTTP_204_NO_CONTENT
        assert repo.delete_calls == [((), {"name": "b"})]


@pytest.mark.anyio
async def test_sync_bulk_viewset_without_return():
    class SyncNoReturnViewSet(BulkAPIViewSet):
        return_on_create = False
        return_on_update = False
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = RecordingSyncRepository()

    async with view_client(SyncNoReturnViewSet) as client:
        created = await client.post("/test/bulk-create", json=[{"name": "a"}])
        assert created.status_code == HTTP_201_CREATED
        assert created.content == b""

        updated = await client.put(
            "/test/bulk-update", json=[{"id": str(uuid4()), "name": "b"}]
        )
        assert updated.status_code == HTTP_200_OK
        assert updated.content == b""


def test_async_generic_bulk_create_view_registers_only_bulk_create():
    class CreateOnlyView(AsyncGenericBulkCreateAPIView):
        response_schema = Item
        create_schema = CreateItem
        repository = RecordingAsyncRepository()

    app = build_app(CreateOnlyView)
    paths = app.openapi()["paths"]
    assert set(paths) == {"/items/bulk-create"}
    assert set(paths["/items/bulk-create"]) == {"post"}


@pytest.mark.anyio
async def test_bulk_create_route_override():
    class BatchCreateView(AsyncGenericBulkCreateAPIView):
        bulk_create_route = "/batch"
        response_schema = Item
        create_schema = CreateItem
        repository = RecordingAsyncRepository()

    async with view_client(BatchCreateView) as client:
        response = await client.post("/test/batch", json=[{"name": "a"}])
        assert response.status_code == HTTP_201_CREATED
        missed = await client.post("/test/bulk-create", json=[])
        assert missed.status_code == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_bulk_delete_without_filter_uses_get_kwargs():
    repo = RecordingAsyncRepository()

    class TenantBulkDeleteView(AsyncGenericBulkDestroyAPIView):
        filter = None
        repository = repo

        def get_kwargs(self, _action=None, /):
            return {"tenant_id": 1}

    async with view_client(TenantBulkDeleteView) as client:
        response = await client.delete("/test/bulk-delete")
        assert response.status_code == HTTP_204_NO_CONTENT
        assert repo.delete_calls == [((), {"tenant_id": 1})]


@pytest.mark.anyio
async def test_bulk_hooks_receive_expected_arguments():
    calls: list[tuple[str, Any]] = []

    class HookedViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = RecordingAsyncRepository()

        async def before_bulk_create(self, data):
            calls.append(("before_create", data))

        async def after_bulk_create(self, objects):
            calls.append(("after_create", list(objects)))

        async def before_bulk_update(self, data):
            calls.append(("before_update", data))

        async def after_bulk_update(self, objs):
            calls.append(("after_update", list(objs)))

        async def before_bulk_delete(self, filter):
            calls.append(("before_delete", filter))

        async def after_bulk_delete(self, filter):
            calls.append(("after_delete", filter))

    item_id = uuid4()
    async with view_client(HookedViewSet) as client:
        await client.post("/test/bulk-create", json=[{"name": "a"}])
        await client.put("/test/bulk-update", json=[{"id": str(item_id), "name": "b"}])
        await client.delete("/test/bulk-delete", params={"name": "b"})

    assert calls[0] == ("before_create", [{"name": "a"}])
    assert calls[1][0] == "after_create"
    assert [obj["name"] for obj in calls[1][1]] == ["a"]
    assert calls[2] == ("before_update", [{"id": item_id, "name": "b"}])
    assert calls[3] == ("after_update", [{"id": item_id, "name": "b"}])
    assert calls[4][0] == "before_delete"
    assert isinstance(calls[4][1], NameFilter)
    assert calls[4][1].name == "b"
    assert calls[5][0] == "after_delete"
    assert calls[5][1] is calls[4][1]


@pytest.mark.anyio
async def test_repository_options_forwarded_to_repository():
    repo = RecordingAsyncRepository()

    class OptionsViewSet(AsyncBulkAPIViewSet):
        repository_options: ClassVar[dict[str, Any]] = {"batch_size": 2}
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = repo

    async with view_client(OptionsViewSet) as client:
        await client.post("/test/bulk-create", json=[{"name": "a"}])
        await client.put("/test/bulk-update", json=[{"id": str(uuid4()), "name": "b"}])

    assert repo.bulk_create_options == [{"batch_size": 2}]
    assert repo.bulk_update_options == [{"batch_size": 2}]


# --------------------------------------------------------------------------- #
# Regression: schemas of one bulk viewset must not clobber another's          #
# --------------------------------------------------------------------------- #


class AlphaItem(BaseModel):
    id: UUID
    name: str


class CreateAlpha(BaseModel):
    name: str


class UpdateAlpha(BaseModel):
    id: UUID
    name: str


class BetaItem(BaseModel):
    id: UUID
    title: str


class CreateBeta(BaseModel):
    title: str


class UpdateBeta(BaseModel):
    id: UUID
    title: str


class AlphaViewSet(AsyncBulkAPIViewSet):
    api_component_name = "Alpha"
    response_schema = AlphaItem
    create_schema = CreateAlpha
    bulk_update_schema = UpdateAlpha
    filter = None
    repository = RecordingAsyncRepository()


class BetaViewSet(AsyncBulkAPIViewSet):
    api_component_name = "Beta"
    response_schema = BetaItem
    create_schema = CreateBeta
    bulk_update_schema = UpdateBeta
    filter = None
    repository = RecordingAsyncRepository()


def build_alpha_beta_app() -> FastAPI:
    app = FastAPI()
    for prefix, view in (("/a", AlphaViewSet), ("/b", BetaViewSet)):
        router = ViewRouter(prefix=prefix)
        router.register_view(view)
        app.include_router(router)
    return app


def test_two_bulk_viewsets_document_their_own_schemas():
    app = build_alpha_beta_app()
    configure_app(app)
    spec = app.openapi()

    def body_item_ref(path: str, method: str) -> str:
        operation = spec["paths"][path][method]
        return operation["requestBody"]["content"]["application/json"]["schema"][
            "items"
        ]["$ref"]

    assert body_item_ref("/a/bulk-create", "post") == "#/components/schemas/CreateAlpha"
    assert body_item_ref("/b/bulk-create", "post") == "#/components/schemas/CreateBeta"
    assert body_item_ref("/a/bulk-update", "put") == "#/components/schemas/UpdateAlpha"
    assert body_item_ref("/b/bulk-update", "put") == "#/components/schemas/UpdateBeta"

    def response_item_ref(path: str, method: str, status: int) -> str:
        operation = spec["paths"][path][method]
        schema = operation["responses"][str(status)]["content"]["application/json"][
            "schema"
        ]
        assert schema["type"] == "array"
        return schema["items"]["$ref"]

    assert (
        response_item_ref("/a/bulk-create", "post", HTTP_201_CREATED)
        == "#/components/schemas/AlphaItem"
    )
    assert (
        response_item_ref("/b/bulk-create", "post", HTTP_201_CREATED)
        == "#/components/schemas/BetaItem"
    )


@pytest.mark.anyio
async def test_bulk_create_validates_against_own_schema():
    app = build_alpha_beta_app()
    async with (
        LifespanManager(app, startup_timeout=30),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        # Valid for CreateBeta but not for CreateAlpha
        invalid = await client.post("/a/bulk-create", json=[{"title": "x"}])
        assert invalid.status_code == HTTP_422_UNPROCESSABLE_CONTENT

        valid = await client.post("/a/bulk-create", json=[{"name": "x"}])
        assert valid.status_code == HTTP_201_CREATED
        assert valid.json()[0]["name"] == "x"


def test_bulk_openapi_documents_status_codes():
    class DocumentedViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        filter = NameFilter
        repository = RecordingAsyncRepository()

    app = build_app(DocumentedViewSet)
    spec = app.openapi()

    create_responses = spec["paths"]["/items/bulk-create"]["post"]["responses"]
    schema = create_responses["201"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["$ref"] == "#/components/schemas/Item"

    delete_responses = spec["paths"]["/items/bulk-delete"]["delete"]["responses"]
    assert "204" in delete_responses
