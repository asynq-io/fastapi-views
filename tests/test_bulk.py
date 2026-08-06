from __future__ import annotations

import inspect
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
    AsyncGenericUpdateManyAPIView,
    BulkAPIViewSet,
    GenericBulkDestroyAPIView,
    GenericUpdateManyAPIView,
)

from .utils import view_client

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import cast

    from fastapi_views.views.bulk import AsyncBulkRepository, BulkRepository


class Item(BaseModel):
    id: UUID
    name: str


class CreateItem(BaseModel):
    name: str


class UpdateItem(BaseModel):
    id: UUID
    name: str


class ItemValues(BaseModel):
    name: str


class NameFilter(BaseFilter):
    name: str | None = None


class RecordingAsyncRepository:
    def __init__(self) -> None:
        self.bulk_create_options: list[dict[str, Any]] = []
        self.bulk_update_items: list[list[dict[str, Any]]] = []
        self.bulk_update_options: list[dict[str, Any]] = []
        self.update_many_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.delete_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def create_many(
        self, items: Sequence[Mapping[str, Any]], /, **options: Any
    ) -> list[dict[str, Any]]:
        self.bulk_create_options.append(options)
        return [{"id": uuid4(), **item} for item in items]

    async def update_many(
        self, values: Mapping[str, Any], *args: Any, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.update_many_calls.append((dict(values), kwargs))
        return [{"id": uuid4(), **values}]

    async def bulk_update(
        self, items: Sequence[Mapping[str, Any]], /, **options: Any
    ) -> None:
        self.bulk_update_items.append([dict(item) for item in items])
        self.bulk_update_options.append(options)

    async def delete_many(self, *args: Any, **kwargs: Any) -> None:
        self.delete_calls.append((args, kwargs))


class RecordingSyncRepository:
    def __init__(self) -> None:
        self.bulk_create_options: list[dict[str, Any]] = []
        self.bulk_update_items: list[list[dict[str, Any]]] = []
        self.bulk_update_options: list[dict[str, Any]] = []
        self.update_many_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.delete_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def create_many(
        self, items: Sequence[Mapping[str, Any]], /, **options: Any
    ) -> list[dict[str, Any]]:
        self.bulk_create_options.append(options)
        return [{"id": uuid4(), **item} for item in items]

    def update_many(
        self, values: Mapping[str, Any], *args: Any, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.update_many_calls.append((dict(values), kwargs))
        return [{"id": uuid4(), **values}]

    def bulk_update(
        self, items: Sequence[Mapping[str, Any]], /, **options: Any
    ) -> None:
        self.bulk_update_items.append([dict(item) for item in items])
        self.bulk_update_options.append(options)

    def delete_many(self, *args: Any, **kwargs: Any) -> None:
        self.delete_calls.append((args, kwargs))


class StrictAsyncBulkRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def create_many(
        self, items: Sequence[Mapping[str, Any]], /, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.calls.append(("create_many", kwargs))
        return [{"id": uuid4(), **item} for item in items]

    async def update_many(
        self, values: Mapping[str, Any], /, *args: Any, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.calls.append(("update_many", kwargs))
        return [{"id": uuid4(), **values}]

    async def bulk_update(
        self, items: Sequence[Mapping[str, Any]], /, **kwargs: Any
    ) -> None:
        self.calls.append(("bulk_update", kwargs))

    async def delete_many(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("delete_many", kwargs))


class StrictSyncBulkRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_many(
        self, items: Sequence[Mapping[str, Any]], /, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.calls.append(("create_many", kwargs))
        return [{"id": uuid4(), **item} for item in items]

    def update_many(
        self, values: Mapping[str, Any], /, *args: Any, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.calls.append(("update_many", kwargs))
        return [{"id": uuid4(), **values}]

    def bulk_update(self, items: Sequence[Mapping[str, Any]], /, **kwargs: Any) -> None:
        self.calls.append(("bulk_update", kwargs))

    def delete_many(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("delete_many", kwargs))


if TYPE_CHECKING:
    _async_protocol_check: AsyncBulkRepository[dict[str, Any]] = cast(
        "StrictAsyncBulkRepository", None
    )
    _sync_protocol_check: BulkRepository[dict[str, Any]] = cast(
        "StrictSyncBulkRepository", None
    )


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
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingAsyncRepository()

    async with view_client(ItemViewSet) as client:
        response = await client.post("/test/bulk", json=[{"name": "a"}, {"name": "b"}])
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert [item["name"] for item in data] == ["a", "b"]
        assert all(UUID(item["id"]) for item in data)


@pytest.mark.anyio
async def test_async_bulk_update():
    repo = RecordingAsyncRepository()

    class ItemViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    item_id = uuid4()
    async with view_client(ItemViewSet) as client:
        response = await client.put(
            "/test/bulk", json=[{"id": str(item_id), "name": "updated"}]
        )
        assert response.status_code == HTTP_204_NO_CONTENT
        assert response.content == b""
        assert repo.bulk_update_items == [[{"id": item_id, "name": "updated"}]]


@pytest.mark.anyio
async def test_async_update_many():
    repo = RecordingAsyncRepository()

    class ItemViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(ItemViewSet) as client:
        response = await client.patch(
            "/test/bulk", params={"name": "old"}, json={"name": "new"}
        )
        assert response.status_code == HTTP_200_OK
        assert [item["name"] for item in response.json()] == ["new"]
        assert repo.update_many_calls == [({"name": "new"}, {"name": "old"})]


@pytest.mark.anyio
async def test_async_bulk_delete_forwards_filter_kwargs():
    repo = RecordingAsyncRepository()

    class ItemViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(ItemViewSet) as client:
        response = await client.delete("/test/bulk", params={"name": "widget"})
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
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingAsyncRepository()

    async with view_client(ItemViewSet) as client:
        response = await client.post("/test/bulk", json=[{"name": "a"}])
        assert response.status_code == HTTP_201_CREATED
        assert response.content == b""


@pytest.mark.anyio
async def test_update_many_without_return():
    class ItemViewSet(AsyncBulkAPIViewSet):
        return_on_update = False
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingAsyncRepository()

    async with view_client(ItemViewSet) as client:
        response = await client.patch(
            "/test/bulk", params={"name": "a"}, json={"name": "b"}
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
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(SyncItemViewSet) as client:
        created = await client.post("/test/bulk", json=[{"name": "a"}])
        assert created.status_code == HTTP_201_CREATED
        assert [item["name"] for item in created.json()] == ["a"]

        item_id = created.json()[0]["id"]
        updated = await client.put("/test/bulk", json=[{"id": item_id, "name": "b"}])
        assert updated.status_code == HTTP_204_NO_CONTENT
        assert repo.bulk_update_items == [[{"id": UUID(item_id), "name": "b"}]]

        patched = await client.patch(
            "/test/bulk", params={"name": "b"}, json={"name": "c"}
        )
        assert patched.status_code == HTTP_200_OK
        assert [item["name"] for item in patched.json()] == ["c"]
        assert repo.update_many_calls == [({"name": "c"}, {"name": "b"})]

        deleted = await client.delete("/test/bulk", params={"name": "c"})
        assert deleted.status_code == HTTP_204_NO_CONTENT
        assert repo.delete_calls == [((), {"name": "c"})]


@pytest.mark.anyio
async def test_sync_bulk_viewset_without_return():
    class SyncNoReturnViewSet(BulkAPIViewSet):
        return_on_create = False
        return_on_update = False
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingSyncRepository()

    async with view_client(SyncNoReturnViewSet) as client:
        created = await client.post("/test/bulk", json=[{"name": "a"}])
        assert created.status_code == HTTP_201_CREATED
        assert created.content == b""

        patched = await client.patch(
            "/test/bulk", params={"name": "a"}, json={"name": "b"}
        )
        assert patched.status_code == HTTP_200_OK
        assert patched.content == b""


def test_async_generic_bulk_create_view_registers_only_bulk_create():
    class CreateOnlyView(AsyncGenericBulkCreateAPIView):
        response_schema = Item
        create_schema = CreateItem
        repository = RecordingAsyncRepository()

    app = build_app(CreateOnlyView)
    paths = app.openapi()["paths"]
    assert set(paths) == {"/items/bulk"}
    assert set(paths["/items/bulk"]) == {"post"}


def test_bulk_viewset_registers_all_actions_on_one_route():
    class ItemViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingAsyncRepository()

    app = build_app(ItemViewSet)
    paths = app.openapi()["paths"]
    assert set(paths) == {"/items/bulk"}
    assert set(paths["/items/bulk"]) == {"post", "put", "patch", "delete"}


@pytest.mark.anyio
async def test_bulk_route_override():
    class BatchCreateView(AsyncGenericBulkCreateAPIView):
        bulk_route = "/batch"
        response_schema = Item
        create_schema = CreateItem
        repository = RecordingAsyncRepository()

    async with view_client(BatchCreateView) as client:
        response = await client.post("/test/batch", json=[{"name": "a"}])
        assert response.status_code == HTTP_201_CREATED
        missed = await client.post("/test/bulk", json=[])
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
        response = await client.delete("/test/bulk")
        assert response.status_code == HTTP_204_NO_CONTENT
        assert repo.delete_calls == [((), {"tenant_id": 1})]


@pytest.mark.anyio
async def test_bulk_hooks_receive_expected_arguments():
    calls: list[tuple[str, Any]] = []

    class HookedViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingAsyncRepository()

        async def before_bulk_create(self, data):
            calls.append(("before_create", data))

        async def after_bulk_create(self, objs):
            calls.append(("after_create", list(objs)))

        async def before_bulk_update(self, data):
            calls.append(("before_update", data))

        async def after_bulk_update(self):
            calls.append(("after_update", None))

        async def before_update_many(self, values):
            calls.append(("before_update_many", values))

        async def after_update_many(self, objs):
            calls.append(("after_update_many", list(objs)))

        async def before_bulk_delete(self):
            calls.append(("before_delete", None))

        async def after_bulk_delete(self):
            calls.append(("after_delete", None))

    item_id = uuid4()
    async with view_client(HookedViewSet) as client:
        await client.post("/test/bulk", json=[{"name": "a"}])
        await client.put("/test/bulk", json=[{"id": str(item_id), "name": "b"}])
        await client.patch("/test/bulk", params={"name": "b"}, json={"name": "c"})
        await client.delete("/test/bulk", params={"name": "c"})

    assert calls[0] == ("before_create", [{"name": "a"}])
    assert calls[1][0] == "after_create"
    assert [obj["name"] for obj in calls[1][1]] == ["a"]
    assert calls[2] == ("before_update", [{"id": item_id, "name": "b"}])
    assert calls[3] == ("after_update", None)
    assert calls[4] == ("before_update_many", {"name": "c"})
    assert calls[5][0] == "after_update_many"
    assert [obj["name"] for obj in calls[5][1]] == ["c"]
    assert calls[6] == ("before_delete", None)
    assert calls[7] == ("after_delete", None)


@pytest.mark.parametrize(
    "view_cls",
    [AsyncBulkAPIViewSet, BulkAPIViewSet],
    ids=["async", "sync"],
)
@pytest.mark.parametrize("hook", ["after_bulk_create", "after_update_many"])
def test_object_hooks_share_one_parameter_name(view_cls: type, hook: str):
    signature = inspect.signature(getattr(view_cls, hook))
    assert list(signature.parameters) == ["self", "objs"]


@pytest.mark.anyio
async def test_object_hooks_are_invokable_by_keyword():
    class AsyncKeywordHookViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingAsyncRepository()

    class SyncKeywordHookViewSet(BulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingSyncRepository()

    async_view = AsyncKeywordHookViewSet.__new__(AsyncKeywordHookViewSet)
    sync_view = SyncKeywordHookViewSet.__new__(SyncKeywordHookViewSet)

    assert await async_view.after_bulk_create(objs=[]) is None
    assert await async_view.after_update_many(objs=[]) is None
    assert sync_view.after_bulk_create(objs=[]) is None
    assert sync_view.after_update_many(objs=[]) is None


@pytest.mark.anyio
async def test_keyword_hook_overrides_are_called_for_both_flavours():
    seen: list[tuple[str, list[Any]]] = []

    class AsyncKeywordOverrides(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingAsyncRepository()

        async def after_bulk_create(self, objs):
            seen.append(("async_create", list(objs)))

        async def after_update_many(self, objs):
            seen.append(("async_update_many", list(objs)))

    class SyncKeywordOverrides(BulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingSyncRepository()

        def after_bulk_create(self, objs):
            seen.append(("sync_create", list(objs)))

        def after_update_many(self, objs):
            seen.append(("sync_update_many", list(objs)))

    async with view_client(AsyncKeywordOverrides) as client:
        await client.post("/test/bulk", json=[{"name": "a"}])
        await client.patch("/test/bulk", params={"name": "a"}, json={"name": "b"})

    async with view_client(SyncKeywordOverrides) as client:
        await client.post("/test/bulk", json=[{"name": "c"}])
        await client.patch("/test/bulk", params={"name": "c"}, json={"name": "d"})

    assert [name for name, _ in seen] == [
        "async_create",
        "async_update_many",
        "sync_create",
        "sync_update_many",
    ]
    assert [obj["name"] for _, objects in seen for obj in objects] == [
        "a",
        "b",
        "c",
        "d",
    ]


@pytest.mark.anyio
async def test_repository_options_forwarded_to_repository():
    repo = RecordingAsyncRepository()

    class OptionsViewSet(AsyncBulkAPIViewSet):
        repository_options: ClassVar[dict[str, Any]] = {"batch_size": 2}
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(OptionsViewSet) as client:
        await client.post("/test/bulk", json=[{"name": "a"}])
        await client.put("/test/bulk", json=[{"id": str(uuid4()), "name": "b"}])

    assert repo.bulk_create_options == [{"batch_size": 2}]
    assert repo.bulk_update_options == [{"batch_size": 2}]


@pytest.mark.anyio
async def test_repository_options_reach_all_four_actions_via_viewset():
    repo = RecordingAsyncRepository()

    class OptionsViewSet(AsyncBulkAPIViewSet):
        repository_options: ClassVar[dict[str, Any]] = {"batch_size": 7}
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(OptionsViewSet) as client:
        await client.post("/test/bulk", json=[{"name": "a"}])
        await client.put("/test/bulk", json=[{"id": str(uuid4()), "name": "b"}])
        await client.patch("/test/bulk", params={"name": "b"}, json={"name": "c"})
        await client.delete("/test/bulk", params={"name": "c"})

    assert repo.bulk_create_options == [{"batch_size": 7}]
    assert repo.bulk_update_options == [{"batch_size": 7}]
    assert repo.update_many_calls == [({"name": "c"}, {"name": "b", "batch_size": 7})]
    assert repo.delete_calls == [((), {"name": "c", "batch_size": 7})]


@pytest.mark.anyio
async def test_repository_options_reach_all_four_actions_via_sync_viewset():
    repo = RecordingSyncRepository()

    class SyncOptionsViewSet(BulkAPIViewSet):
        repository_options: ClassVar[dict[str, Any]] = {"batch_size": 3}
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(SyncOptionsViewSet) as client:
        await client.post("/test/bulk", json=[{"name": "a"}])
        await client.put("/test/bulk", json=[{"id": str(uuid4()), "name": "b"}])
        await client.patch("/test/bulk", params={"name": "b"}, json={"name": "c"})
        await client.delete("/test/bulk", params={"name": "c"})

    assert repo.bulk_create_options == [{"batch_size": 3}]
    assert repo.bulk_update_options == [{"batch_size": 3}]
    assert repo.update_many_calls == [({"name": "c"}, {"name": "b", "batch_size": 3})]
    assert repo.delete_calls == [((), {"name": "c", "batch_size": 3})]


@pytest.mark.anyio
async def test_protocol_conforming_async_repository_accepts_repository_options():
    repo = StrictAsyncBulkRepository()

    class StrictOptionsViewSet(AsyncBulkAPIViewSet):
        repository_options: ClassVar[dict[str, Any]] = {"batch_size": 11}
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(StrictOptionsViewSet) as client:
        created = await client.post("/test/bulk", json=[{"name": "a"}])
        assert created.status_code == HTTP_201_CREATED
        updated = await client.put(
            "/test/bulk", json=[{"id": str(uuid4()), "name": "b"}]
        )
        assert updated.status_code == HTTP_204_NO_CONTENT
        patched = await client.patch(
            "/test/bulk", params={"name": "b"}, json={"name": "c"}
        )
        assert patched.status_code == HTTP_200_OK
        deleted = await client.delete("/test/bulk", params={"name": "c"})
        assert deleted.status_code == HTTP_204_NO_CONTENT

    assert repo.calls == [
        ("create_many", {"batch_size": 11}),
        ("bulk_update", {"batch_size": 11}),
        ("update_many", {"name": "b", "batch_size": 11}),
        ("delete_many", {"name": "c", "batch_size": 11}),
    ]


@pytest.mark.anyio
async def test_protocol_conforming_sync_repository_accepts_repository_options():
    repo = StrictSyncBulkRepository()

    class StrictSyncOptionsViewSet(BulkAPIViewSet):
        repository_options: ClassVar[dict[str, Any]] = {"batch_size": 13}
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(StrictSyncOptionsViewSet) as client:
        created = await client.post("/test/bulk", json=[{"name": "a"}])
        assert created.status_code == HTTP_201_CREATED
        updated = await client.put(
            "/test/bulk", json=[{"id": str(uuid4()), "name": "b"}]
        )
        assert updated.status_code == HTTP_204_NO_CONTENT
        patched = await client.patch(
            "/test/bulk", params={"name": "b"}, json={"name": "c"}
        )
        assert patched.status_code == HTTP_200_OK
        deleted = await client.delete("/test/bulk", params={"name": "c"})
        assert deleted.status_code == HTTP_204_NO_CONTENT

    assert repo.calls == [
        ("create_many", {"batch_size": 13}),
        ("bulk_update", {"batch_size": 13}),
        ("update_many", {"name": "b", "batch_size": 13}),
        ("delete_many", {"name": "c", "batch_size": 13}),
    ]


@pytest.mark.anyio
async def test_repository_options_reach_standalone_async_update_many():
    repo = RecordingAsyncRepository()

    class UpdateManyOnlyView(AsyncGenericUpdateManyAPIView):
        repository_options: ClassVar[dict[str, Any]] = {"synchronize_session": False}
        response_schema = Item
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(UpdateManyOnlyView) as client:
        response = await client.patch(
            "/test/bulk", params={"name": "old"}, json={"name": "new"}
        )
        assert response.status_code == HTTP_200_OK

    assert repo.update_many_calls == [
        ({"name": "new"}, {"name": "old", "synchronize_session": False})
    ]


@pytest.mark.anyio
async def test_repository_options_reach_standalone_async_bulk_delete():
    repo = RecordingAsyncRepository()

    class DeleteOnlyView(AsyncGenericBulkDestroyAPIView):
        repository_options: ClassVar[dict[str, Any]] = {"synchronize_session": False}
        filter = NameFilter
        repository = repo

    async with view_client(DeleteOnlyView) as client:
        response = await client.delete("/test/bulk", params={"name": "gone"})
        assert response.status_code == HTTP_204_NO_CONTENT

    assert repo.delete_calls == [
        ((), {"name": "gone", "synchronize_session": False}),
    ]


@pytest.mark.anyio
async def test_repository_options_reach_standalone_sync_filtered_views():
    update_repo = RecordingSyncRepository()
    delete_repo = RecordingSyncRepository()

    class SyncUpdateManyOnlyView(GenericUpdateManyAPIView):
        repository_options: ClassVar[dict[str, Any]] = {"batch_size": 5}
        response_schema = Item
        update_schema = ItemValues
        filter = NameFilter
        repository = update_repo

    class SyncDeleteOnlyView(GenericBulkDestroyAPIView):
        repository_options: ClassVar[dict[str, Any]] = {"batch_size": 5}
        filter = NameFilter
        repository = delete_repo

    async with view_client(SyncUpdateManyOnlyView) as client:
        await client.patch("/test/bulk", params={"name": "old"}, json={"name": "new"})

    async with view_client(SyncDeleteOnlyView) as client:
        await client.delete("/test/bulk", params={"name": "gone"})

    assert update_repo.update_many_calls == [
        ({"name": "new"}, {"name": "old", "batch_size": 5})
    ]
    assert delete_repo.delete_calls == [((), {"name": "gone", "batch_size": 5})]


@pytest.mark.anyio
async def test_repository_options_can_vary_per_action():
    repo = RecordingAsyncRepository()

    class PerActionViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

        def get_repository_options(self, action=None):
            return {"action": action}

    async with view_client(PerActionViewSet) as client:
        await client.patch("/test/bulk", params={"name": "b"}, json={"name": "c"})
        await client.delete("/test/bulk", params={"name": "c"})

    assert repo.update_many_calls == [
        ({"name": "c"}, {"name": "b", "action": "update_many"})
    ]
    assert repo.delete_calls == [((), {"name": "c", "action": "bulk_delete"})]


def test_merge_repository_options_raises_on_filter_key_collision():
    class CollidingView(AsyncGenericBulkDestroyAPIView):
        repository_options: ClassVar[dict[str, Any]] = {"name": "override"}
        filter = NameFilter
        repository = RecordingAsyncRepository()

    view = CollidingView.__new__(CollidingView)
    with pytest.raises(TypeError, match="'name'"):
        view.merge_repository_options({"name": "from-filter"}, "bulk_delete")


@pytest.mark.anyio
async def test_colliding_option_key_raises_on_filtered_actions():
    repo = RecordingAsyncRepository()

    class CollidingViewSet(AsyncBulkAPIViewSet):
        repository_options: ClassVar[dict[str, Any]] = {"name": "override"}
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(CollidingViewSet) as client:
        with pytest.raises(TypeError, match="collide with the filter criteria"):
            await client.patch("/test/bulk", params={"name": "b"}, json={"name": "c"})
        with pytest.raises(TypeError, match="collide with the filter criteria"):
            await client.delete("/test/bulk", params={"name": "c"})

    assert repo.update_many_calls == []
    assert repo.delete_calls == []


@pytest.mark.anyio
async def test_colliding_option_key_is_inert_while_filter_field_unset():
    repo = RecordingAsyncRepository()

    class CollidingViewSet(AsyncBulkAPIViewSet):
        repository_options: ClassVar[dict[str, Any]] = {"name": "override"}
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = repo

    async with view_client(CollidingViewSet) as client:
        response = await client.delete("/test/bulk")
        assert response.status_code == HTTP_204_NO_CONTENT

    assert repo.delete_calls == [((), {"name": "override"})]


class AlphaItem(BaseModel):
    id: UUID
    name: str


class CreateAlpha(BaseModel):
    name: str


class UpdateAlpha(BaseModel):
    id: UUID
    name: str


class ValuesAlpha(BaseModel):
    name: str


class BetaItem(BaseModel):
    id: UUID
    title: str


class CreateBeta(BaseModel):
    title: str


class UpdateBeta(BaseModel):
    id: UUID
    title: str


class ValuesBeta(BaseModel):
    title: str


class AlphaViewSet(AsyncBulkAPIViewSet):
    api_component_name = "Alpha"
    response_schema = AlphaItem
    create_schema = CreateAlpha
    bulk_update_schema = UpdateAlpha
    update_schema = ValuesAlpha
    filter = None
    repository = RecordingAsyncRepository()


class BetaViewSet(AsyncBulkAPIViewSet):
    api_component_name = "Beta"
    response_schema = BetaItem
    create_schema = CreateBeta
    bulk_update_schema = UpdateBeta
    update_schema = ValuesBeta
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

    assert body_item_ref("/a/bulk", "post") == "#/components/schemas/CreateAlpha"
    assert body_item_ref("/b/bulk", "post") == "#/components/schemas/CreateBeta"
    assert body_item_ref("/a/bulk", "put") == "#/components/schemas/UpdateAlpha"
    assert body_item_ref("/b/bulk", "put") == "#/components/schemas/UpdateBeta"

    def body_ref(path: str, method: str) -> str:
        operation = spec["paths"][path][method]
        return operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]

    assert body_ref("/a/bulk", "patch") == "#/components/schemas/ValuesAlpha"
    assert body_ref("/b/bulk", "patch") == "#/components/schemas/ValuesBeta"

    def response_item_ref(path: str, method: str, status: int) -> str:
        operation = spec["paths"][path][method]
        schema = operation["responses"][str(status)]["content"]["application/json"][
            "schema"
        ]
        assert schema["type"] == "array"
        return schema["items"]["$ref"]

    assert (
        response_item_ref("/a/bulk", "post", HTTP_201_CREATED)
        == "#/components/schemas/AlphaItem"
    )
    assert (
        response_item_ref("/b/bulk", "post", HTTP_201_CREATED)
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
        invalid = await client.post("/a/bulk", json=[{"title": "x"}])
        assert invalid.status_code == HTTP_422_UNPROCESSABLE_CONTENT

        valid = await client.post("/a/bulk", json=[{"name": "x"}])
        assert valid.status_code == HTTP_201_CREATED
        assert valid.json()[0]["name"] == "x"


def test_bulk_openapi_documents_status_codes():
    class DocumentedViewSet(AsyncBulkAPIViewSet):
        response_schema = Item
        create_schema = CreateItem
        bulk_update_schema = UpdateItem
        update_schema = ItemValues
        filter = NameFilter
        repository = RecordingAsyncRepository()

    app = build_app(DocumentedViewSet)
    spec = app.openapi()

    create_responses = spec["paths"]["/items/bulk"]["post"]["responses"]
    schema = create_responses["201"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["$ref"] == "#/components/schemas/Item"

    update_responses = spec["paths"]["/items/bulk"]["put"]["responses"]
    assert "204" in update_responses

    patch_responses = spec["paths"]["/items/bulk"]["patch"]["responses"]
    schema = patch_responses["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["$ref"] == "#/components/schemas/Item"

    delete_responses = spec["paths"]["/items/bulk"]["delete"]["responses"]
    assert "204" in delete_responses
