from unittest.mock import MagicMock

import pytest
from fastapi import Request as FastAPIRequest
from fastapi import Response as FastAPIResponse
from httpx import Response
from pydantic.type_adapter import TypeAdapter
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_404_NOT_FOUND,
)

from fastapi_views.views.api import (
    AnyTypeAdapter,
    AsyncCreateAPIView,
    AsyncPartialUpdateAPIView,
    AsyncRetrieveAPIView,
    AsyncUpdateAPIView,
    View,
)

from .utils import view_client


def validate_response_meta(response: Response, status_code: int = HTTP_200_OK):
    assert response.status_code == status_code
    assert response.headers["Content-Type"] == "application/json"
    assert "Content-Length" in response.headers


@pytest.mark.usefixtures("list_view")
@pytest.mark.anyio
async def test_list_api_view(client, dummy_data):
    response = await client.get("/test")
    assert response.json() == [dummy_data]
    validate_response_meta(response)


@pytest.mark.usefixtures("retrieve_view")
@pytest.mark.anyio
async def test_retrieve_api_view(client, dummy_data):
    response = await client.get("/test")
    assert response.json() == dummy_data
    validate_response_meta(response)


@pytest.mark.usefixtures("create_view")
@pytest.mark.anyio
async def test_create_api_view(client, dummy_data):
    response = await client.post("/test")
    assert response.json() == dummy_data
    validate_response_meta(response, HTTP_201_CREATED)


@pytest.mark.usefixtures("destroy_view")
@pytest.mark.anyio
async def test_destroy_api_view(client):
    response = await client.delete("/test")
    assert response.status_code == HTTP_204_NO_CONTENT


@pytest.mark.usefixtures("custom_retrieve_view")
@pytest.mark.anyio
async def test_custom_retrieve_api_view(client, dummy_data):
    response = await client.get("/test/custom")
    assert response.json() == dummy_data
    validate_response_meta(response)


def test_view_get_serializer_none_schema():
    class ConcreteView(View):
        pass

    view = ConcreteView.__new__(ConcreteView)
    view.request = MagicMock(spec=FastAPIRequest)
    view.response = MagicMock(spec=FastAPIResponse)
    assert view.get_serializer(None) is AnyTypeAdapter


def test_view_get_json_content_validate():
    class ConcreteView(View):
        validate_response = True
        from_attributes = False

    view = ConcreteView.__new__(ConcreteView)
    view.request = MagicMock(spec=FastAPIRequest)
    view.response = MagicMock(spec=FastAPIResponse)
    assert view.get_json_content(content=42, serializer=TypeAdapter(int)) == b"42"


@pytest.mark.anyio
async def test_async_view_returns_string():
    class StringView(AsyncRetrieveAPIView):
        detail_route = ""

        async def retrieve(self):
            return "hello string"

    async with view_client(StringView) as c:
        response = await c.get("/test")
        assert response.status_code == HTTP_200_OK
        assert "hello string" in response.text


@pytest.mark.anyio
async def test_async_create_with_location():
    class LocationCreateView(AsyncCreateAPIView):
        def get_location(self, obj):
            return f"/items/{obj['id']}"

        async def create(self) -> dict:
            return {"id": 1, "name": "test"}

    async with view_client(LocationCreateView) as c:
        response = await c.post("/test")
        assert response.status_code == HTTP_201_CREATED
        assert response.headers.get("location") == "/items/1"


@pytest.mark.anyio
async def test_async_create_no_return():
    class NoReturnCreateView(AsyncCreateAPIView):
        return_on_create = False

        async def create(self) -> dict:
            return {"id": 1}

    async with view_client(NoReturnCreateView) as c:
        response = await c.post("/test")
        assert response.status_code == HTTP_201_CREATED
        assert response.content == b""


@pytest.mark.anyio
async def test_async_update_no_return():
    class NoReturnUpdateView(AsyncUpdateAPIView):
        detail_route = ""
        return_on_update = False

        async def update(self) -> dict:
            return {"updated": True}

    async with view_client(NoReturnUpdateView) as c:
        response = await c.put("/test")
        assert response.status_code == HTTP_200_OK
        assert response.content == b""


@pytest.mark.anyio
async def test_async_update_raise_on_none():
    class RaiseOnNoneUpdateView(AsyncUpdateAPIView):
        detail_route = ""
        raise_on_none = True

        async def update(self) -> None:
            return None

    async with view_client(RaiseOnNoneUpdateView, error_handlers=True) as c:
        response = await c.put("/test")
        assert response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_async_partial_update_raise_on_none():
    class RaiseOnNonePartialView(AsyncPartialUpdateAPIView):
        detail_route = ""
        raise_on_none = True

        async def partial_update(self) -> None:
            return None

    async with view_client(RaiseOnNonePartialView, error_handlers=True) as c:
        response = await c.patch("/test")
        assert response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_async_partial_update_no_return():
    class NoReturnPartialView(AsyncPartialUpdateAPIView):
        detail_route = ""
        return_on_update = False

        async def partial_update(self) -> dict:
            return {"updated": True}

    async with view_client(NoReturnPartialView) as c:
        response = await c.patch("/test")
        assert response.status_code == HTTP_200_OK
        assert response.content == b""
