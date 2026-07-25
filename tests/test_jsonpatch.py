from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from fastapi_views.exceptions import BadRequest
from fastapi_views.models.jsonpatch import JsonPatchModel, apply
from fastapi_views.views.jsonpatch import (
    AsyncGenericJsonPatchAPIView,
    GenericJsonPatchAPIView,
)

from .utils import view_client


class ItemId(BaseModel):
    id: int


class Item(ItemId):
    name: str
    tags: list[str] = []
    updated_at: datetime | None = None


@pytest.mark.parametrize(
    "operations",
    [
        [{"op": "add", "path": "/a", "value": 1}],
        [{"op": "remove", "path": "/a"}],
        [{"op": "replace", "path": "/a", "value": 1}],
        [{"op": "move", "path": "/b", "from": "/a"}],
        [{"op": "copy", "path": "/b", "from": "/a"}],
        [{"op": "test", "path": "/a", "value": 1}],
    ],
)
def test_json_patch_model_accepts_rfc6902_operations(operations):
    assert JsonPatchModel.model_validate(operations).root == operations


@pytest.mark.parametrize(
    "operations",
    [
        [{"op": "unknown", "path": "/a"}],
        [{"op": "add", "path": "/a"}],
        [{"op": "move", "path": "/a"}],
        [{"path": "/a", "value": 1}],
        "not a list",
    ],
)
def test_json_patch_model_rejects_invalid_operations(operations):
    with pytest.raises(ValidationError):
        JsonPatchModel.model_validate(operations)


def test_apply_returns_patched_copy_and_keeps_original():
    doc = {"a": 1}
    patched = apply(doc, [{"op": "replace", "path": "/a", "value": 2}])
    assert patched == {"a": 2}
    assert doc == {"a": 1}


def test_apply_in_place_mutates_document():
    doc = {"a": 1}
    patched = apply(doc, [{"op": "replace", "path": "/a", "value": 2}], in_place=True)
    assert patched == {"a": 2}
    assert doc == {"a": 2}


def test_apply_returns_new_document_for_root_operation():
    patched = apply({"a": 1}, [{"op": "replace", "path": "", "value": {"b": 2}}])
    assert patched == {"b": 2}


class ItemRepository:
    def __init__(self, items: dict[int, dict[str, Any]]) -> None:
        self.items = items
        self.updates: list[dict[str, Any]] = []

    async def get(self, **kwargs: Any) -> dict[str, Any] | None:
        return self.items.get(kwargs["id"])

    async def update_one(
        self, values: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        item = self.items.get(kwargs["id"])
        if item is None:
            return None
        self.updates.append(values)
        item.update(values)
        return item


class SyncItemRepository:
    def __init__(self, items: dict[int, dict[str, Any]]) -> None:
        self.items = items
        self.updates: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> dict[str, Any] | None:
        return self.items.get(kwargs["id"])

    def update_one(
        self, values: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        item = self.items.get(kwargs["id"])
        if item is None:
            return None
        self.updates.append(values)
        item.update(values)
        return item


@pytest.fixture
def items() -> dict[int, dict[str, Any]]:
    return {
        1: {
            "id": 1,
            "name": "first",
            "tags": ["a"],
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
    }


@pytest.fixture
def repository(items) -> ItemRepository:
    return ItemRepository(items)


@pytest.fixture
def view(repository):
    repo = repository

    class ItemJsonPatchView(AsyncGenericJsonPatchAPIView):
        api_component_name = "PatchedItem"
        response_schema = Item
        partial_update_schema = Item
        primary_key = ItemId
        repository = repo

    return ItemJsonPatchView


@pytest.fixture
def sync_view(items):
    repo = SyncItemRepository(items)

    class SyncItemJsonPatchView(GenericJsonPatchAPIView):
        api_component_name = "SyncPatchedItem"
        response_schema = Item
        partial_update_schema = Item
        primary_key = ItemId
        repository = repo

    return SyncItemJsonPatchView


@pytest.mark.anyio
async def test_patch_replaces_field(view):
    async with view_client(view) as client:
        response = await client.patch(
            "/test/1", json=[{"op": "replace", "path": "/name", "value": "second"}]
        )
    assert response.status_code == HTTP_200_OK
    assert response.json()["name"] == "second"


@pytest.mark.anyio
async def test_patch_updates_only_changed_fields(view, repository):
    async with view_client(view) as client:
        response = await client.patch(
            "/test/1", json=[{"op": "add", "path": "/tags/-", "value": "b"}]
        )
    assert response.status_code == HTTP_200_OK
    assert repository.updates == [{"tags": ["a", "b"]}]


@pytest.mark.anyio
async def test_patch_noop_sends_no_updates(view, repository):
    async with view_client(view) as client:
        response = await client.patch(
            "/test/1", json=[{"op": "test", "path": "/name", "value": "first"}]
        )
    assert response.status_code == HTTP_200_OK
    assert repository.updates == [{}]


@pytest.mark.anyio
async def test_patch_compares_json_values(view):
    operations = [
        {"op": "test", "path": "/updated_at", "value": "2026-01-01T00:00:00Z"},
        {"op": "replace", "path": "/updated_at", "value": "2026-02-01T00:00:00Z"},
    ]
    async with view_client(view) as client:
        response = await client.patch("/test/1", json=operations)
    assert response.status_code == HTTP_200_OK
    assert response.json()["updated_at"] == "2026-02-01T00:00:00Z"


@pytest.mark.anyio
async def test_patch_coerces_values_before_update(view, repository):
    operations = [
        {"op": "replace", "path": "/updated_at", "value": "2026-02-01T00:00:00Z"}
    ]
    async with view_client(view) as client:
        await client.patch("/test/1", json=operations)
    assert repository.updates == [
        {"updated_at": datetime(2026, 2, 1, tzinfo=timezone.utc)}
    ]


@pytest.mark.anyio
async def test_patch_writes_default_back_on_remove(view, repository):
    async with view_client(view) as client:
        response = await client.patch(
            "/test/1", json=[{"op": "remove", "path": "/tags"}]
        )
    assert response.status_code == HTTP_200_OK
    assert repository.updates == [{"tags": []}]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operations",
    [
        [{"op": "replace", "path": "/missing", "value": 1}],
        [{"op": "replace", "path": "no-slash", "value": 1}],
        [{"op": "test", "path": "/name", "value": "other"}],
        [{"op": "remove", "path": "/name"}],
        [{"op": "replace", "path": "/name", "value": {"bad": "type"}}],
    ],
)
async def test_patch_invalid_operations_return_bad_request(view, operations):
    async with view_client(view, error_handlers=True) as client:
        response = await client.patch("/test/1", json=operations)
    assert response.status_code == HTTP_400_BAD_REQUEST


@pytest.mark.anyio
async def test_patch_malformed_document_returns_unprocessable(view):
    async with view_client(view) as client:
        response = await client.patch(
            "/test/1", json=[{"op": "unknown", "path": "/name"}]
        )
    assert response.status_code == HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.anyio
async def test_patch_missing_item_returns_not_found(view):
    async with view_client(view, error_handlers=True) as client:
        response = await client.patch(
            "/test/42", json=[{"op": "replace", "path": "/name", "value": "x"}]
        )
    assert response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_sync_patch_replaces_field(sync_view):
    async with view_client(sync_view) as client:
        response = await client.patch(
            "/test/1", json=[{"op": "replace", "path": "/name", "value": "second"}]
        )
    assert response.status_code == HTTP_200_OK
    assert response.json()["name"] == "second"


@pytest.mark.anyio
async def test_sync_patch_invalid_operations_return_bad_request(sync_view):
    async with view_client(sync_view, error_handlers=True) as client:
        response = await client.patch(
            "/test/1", json=[{"op": "test", "path": "/name", "value": "other"}]
        )
    assert response.status_code == HTTP_400_BAD_REQUEST


def test_apply_patch_validation_error_on_source_object_is_not_bad_request(view):
    instance = view.__new__(view)
    with pytest.raises(ValidationError):
        instance.apply_patch({"id": 1}, JsonPatchModel([]))


def test_apply_patch_rejects_root_replace_with_non_object(view):
    instance = view.__new__(view)
    operations = JsonPatchModel([{"op": "replace", "path": "", "value": [1, 2]}])
    with pytest.raises(BadRequest):
        instance.apply_patch({"id": 1, "name": "first"}, operations)
