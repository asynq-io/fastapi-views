from __future__ import annotations

from typing import Any

import pytest
from fastapi.responses import Response
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
)

from fastapi_views.exceptions import NotFound
from fastapi_views.models import BaseSchema
from fastapi_views.views.api import (
    APIView,
    CreateAPIView,
    DestroyAPIView,
    ListAPIView,
    PartialUpdateAPIView,
    RetrieveAPIView,
    ServerSentEventsAPIView,
    UpdateAPIView,
)
from fastapi_views.views.functools import get

from .utils import view_as_fixture


class DummySchema(BaseSchema):
    x: str


@view_as_fixture("sync_list_view")
class TestSyncListView(ListAPIView):
    response_schema = DummySchema

    def list(self) -> Any:
        return [{"x": "sync_item"}]


@pytest.mark.usefixtures("sync_list_view")
@pytest.mark.anyio
async def test_sync_list_view(client):
    response = await client.get("/test")
    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert data == [{"x": "sync_item"}]
    assert response.headers["Content-Type"] == "application/json"


@view_as_fixture("sync_retrieve_view")
class TestSyncRetrieveView(RetrieveAPIView):
    detail_route = ""
    response_schema = DummySchema

    def retrieve(self) -> Any:
        return {"x": "sync_retrieved"}


@pytest.mark.usefixtures("sync_retrieve_view")
@pytest.mark.anyio
async def test_sync_retrieve_view(client):
    response = await client.get("/test")
    assert response.status_code == HTTP_200_OK
    assert response.json()["x"] == "sync_retrieved"
    assert response.headers["Content-Type"] == "application/json"


@view_as_fixture("sync_retrieve_not_found_view")
class TestSyncRetrieveNotFoundView(RetrieveAPIView):
    detail_route = ""
    response_schema = DummySchema
    raise_on_none = True

    def retrieve(self) -> Any:
        return None


@pytest.mark.usefixtures("sync_retrieve_not_found_view")
@pytest.mark.anyio
async def test_sync_retrieve_raises_not_found(client):
    with pytest.raises(NotFound):
        await client.get("/test")


@view_as_fixture("sync_retrieve_none_ok_view")
class TestSyncRetrieveNoneOkView(RetrieveAPIView):
    detail_route = ""
    response_schema = DummySchema
    raise_on_none = False

    def retrieve(self) -> Any:
        return None


@pytest.mark.usefixtures("sync_retrieve_none_ok_view")
@pytest.mark.anyio
async def test_sync_retrieve_none_ok(client):
    response = await client.get("/test")
    assert response.status_code == HTTP_200_OK
    assert "Content-Type" not in response.headers


@view_as_fixture("sync_create_view")
class TestSyncCreateView(APIView):
    response_schema = DummySchema

    @get(path="")
    def create(self) -> DummySchema:
        return DummySchema(x="created")


@pytest.mark.usefixtures("sync_create_view")
@pytest.mark.anyio
async def test_sync_custom_get_view(client):
    response = await client.get("/test")
    assert response.status_code == HTTP_200_OK
    assert response.json()["x"] == "created"
    assert response.headers["Content-Type"] == "application/json"


@view_as_fixture("sync_create_201_view")
class TestSyncCreate201View(CreateAPIView):
    response_schema = DummySchema

    def create(self) -> Any:
        return {"x": "new_item"}


@pytest.mark.usefixtures("sync_create_201_view")
@pytest.mark.anyio
async def test_sync_create_201(client):
    response = await client.post("/test")
    assert response.status_code == HTTP_201_CREATED
    assert response.json()["x"] == "new_item"
    assert response.headers["Content-Type"] == "application/json"


@view_as_fixture("sync_create_no_return_view")
class TestSyncCreateNoReturnView(CreateAPIView):
    response_schema = DummySchema
    return_on_create = False

    def create(self) -> Any:
        return {"x": "not_returned"}


@pytest.mark.usefixtures("sync_create_no_return_view")
@pytest.mark.anyio
async def test_sync_create_no_return(client):
    response = await client.post("/test")
    assert response.status_code == HTTP_201_CREATED
    assert response.content == b""
    assert "Content-Type" not in response.headers


@view_as_fixture("sync_create_with_location_view")
class TestSyncCreateWithLocationView(CreateAPIView):
    response_schema = DummySchema

    def create(self) -> Any:
        return {"x": "located"}

    def get_location(self, _obj: Any) -> str:
        return "/test/1"


@pytest.mark.usefixtures("sync_create_with_location_view")
@pytest.mark.anyio
async def test_sync_create_with_location(client):
    response = await client.post("/test")
    assert response.status_code == HTTP_201_CREATED
    assert response.headers.get("location") == "/test/1"
    assert response.headers["Content-Type"] == "application/json"


@view_as_fixture("sync_update_view")
class TestSyncUpdateView(UpdateAPIView):
    detail_route = ""
    response_schema = DummySchema

    def update(self) -> Any:
        return {"x": "updated"}


@pytest.mark.usefixtures("sync_update_view")
@pytest.mark.anyio
async def test_sync_update_view(client):
    response = await client.put("/test")
    assert response.status_code == HTTP_200_OK
    assert response.json()["x"] == "updated"
    assert response.headers["Content-Type"] == "application/json"


@view_as_fixture("sync_update_no_return_view")
class TestSyncUpdateNoReturnView(UpdateAPIView):
    detail_route = ""
    response_schema = DummySchema
    return_on_update = False

    def update(self) -> Any:
        return {"x": "not_returned"}


@pytest.mark.usefixtures("sync_update_no_return_view")
@pytest.mark.anyio
async def test_sync_update_no_return(client):
    response = await client.put("/test")
    assert response.status_code == HTTP_200_OK
    assert response.content == b""
    assert "Content-Type" not in response.headers


@view_as_fixture("sync_update_not_found_view")
class TestSyncUpdateNotFoundView(UpdateAPIView):
    detail_route = ""
    response_schema = DummySchema
    raise_on_none = True

    def update(self) -> Any:
        return None


@pytest.mark.usefixtures("sync_update_not_found_view")
@pytest.mark.anyio
async def test_sync_update_raises_not_found(client):
    with pytest.raises(NotFound):
        await client.put("/test")


@view_as_fixture("sync_patch_view")
class TestSyncPatchView(PartialUpdateAPIView):
    detail_route = ""
    response_schema = DummySchema

    def partial_update(self) -> Any:
        return {"x": "patched"}


@pytest.mark.usefixtures("sync_patch_view")
@pytest.mark.anyio
async def test_sync_partial_update_view(client):
    response = await client.patch("/test")
    assert response.status_code == HTTP_200_OK
    assert response.json()["x"] == "patched"
    assert response.headers["Content-Type"] == "application/json"


@view_as_fixture("sync_patch_no_return_view")
class TestSyncPatchNoReturnView(PartialUpdateAPIView):
    detail_route = ""
    response_schema = DummySchema
    return_on_update = False

    def partial_update(self) -> Any:
        return {"x": "patched"}


@pytest.mark.usefixtures("sync_patch_no_return_view")
@pytest.mark.anyio
async def test_sync_partial_update_no_return(client):
    response = await client.patch("/test")
    assert response.status_code == HTTP_200_OK
    assert response.content == b""
    assert "Content-Type" not in response.headers


@view_as_fixture("sync_patch_not_found_view")
class TestSyncPatchNotFoundView(PartialUpdateAPIView):
    detail_route = ""
    response_schema = DummySchema
    raise_on_none = True

    def partial_update(self) -> Any:
        return None


@pytest.mark.usefixtures("sync_patch_not_found_view")
@pytest.mark.anyio
async def test_sync_partial_update_raises_not_found(client):
    with pytest.raises(NotFound):
        await client.patch("/test")


@view_as_fixture("sync_destroy_view")
class TestSyncDestroyView(DestroyAPIView):
    detail_route = ""

    def destroy(self) -> None:
        pass


@pytest.mark.usefixtures("sync_destroy_view")
@pytest.mark.anyio
async def test_sync_destroy_view(client):
    response = await client.delete("/test")
    assert response.status_code == HTTP_204_NO_CONTENT
    assert "Content-Type" not in response.headers


@view_as_fixture("sse_events_view")
class TestSSEView(ServerSentEventsAPIView):
    response_schema = DummySchema

    async def events(self):
        yield "data_event", {"x": "first"}
        yield "data_event", {"x": "second"}


@pytest.mark.usefixtures("sse_events_view")
@pytest.mark.anyio
async def test_sse_view_response(client):
    response = await client.get("/test")
    assert response.status_code == HTTP_200_OK
    assert "text/event-stream" in response.headers["content-type"]
    content = response.text
    assert "event: data_event" in content
    assert "first" in content
    assert "second" in content


@view_as_fixture("bytes_view")
class TestBytesView(APIView):
    @get(path="")
    async def get_bytes(self) -> Any:
        return b'{"x": "bytes"}'


@pytest.mark.usefixtures("bytes_view")
@pytest.mark.anyio
async def test_view_returns_bytes(client):
    response = await client.get("/test")
    assert response.status_code == HTTP_200_OK


@view_as_fixture("response_view")
class TestResponseView(APIView):
    @get(path="")
    async def direct_response(self) -> Any:
        return Response(content=b'{"x": "direct"}', status_code=200)


@pytest.mark.usefixtures("response_view")
@pytest.mark.anyio
async def test_view_returns_response(client):
    response = await client.get("/test")
    assert response.status_code == HTTP_200_OK


@view_as_fixture("no_validate_view")
class TestNoValidateView(ListAPIView):
    response_schema = DummySchema
    validate_response = False

    def list(self) -> Any:
        return [{"x": "no_validate"}]


@pytest.mark.usefixtures("no_validate_view")
@pytest.mark.anyio
async def test_no_validate_response(client):
    response = await client.get("/test")
    assert response.status_code == HTTP_200_OK
