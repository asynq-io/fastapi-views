from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import Request as FastAPIRequest
from fastapi import Response as FastAPIResponse
from httpx import Response
from pydantic import BaseModel, Field
from pydantic.type_adapter import TypeAdapter
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_304_NOT_MODIFIED,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from fastapi_views.exceptions import Conflict
from fastapi_views.models import ResponseHeaders
from fastapi_views.views import get
from fastapi_views.views.api import (
    AnyTypeAdapter,
    APIView,
    AsyncCreateAPIView,
    AsyncListAPIView,
    AsyncPartialUpdateAPIView,
    AsyncRetrieveAPIView,
    AsyncUpdateAPIView,
    View,
)
from fastapi_views.views.functools import override, throws
from fastapi_views.views.mixins import ConditionalMixin

from .utils import view_client

PROBLEM_JSON = "application/problem+json"


def validate_response_meta(response: Response, status_code: int = HTTP_200_OK):
    assert response.status_code == status_code
    assert response.headers["Content-Type"] == "application/json"
    assert "Content-Length" in response.headers


async def openapi_responses(
    view: type[View],
    method: str,
    path: str = "/test",
) -> dict[str, Any]:
    async with view_client(view) as client:
        response = await client.get("/openapi.json")
    assert response.status_code == HTTP_200_OK
    return response.json()["paths"][path][method]["responses"]


@pytest.mark.usefixtures("list_view")
@pytest.mark.anyio
async def test_list_api_view(client, dummy_data):
    response = await client.get("/test")
    assert response.json() == [dummy_data]
    validate_response_meta(response)


@pytest.mark.anyio
async def test_async_list_custom_status_code():
    class CustomStatusListView(AsyncListAPIView):
        response_schema = dict

        @override(status_code=206)
        async def list(self) -> list[dict[str, Any]]:
            return [{"x": "item"}]

    async with view_client(CustomStatusListView) as c:
        response = await c.get("/test")
        assert response.status_code == 206
        assert response.json() == [{"x": "item"}]


@pytest.mark.usefixtures("retrieve_view")
@pytest.mark.anyio
async def test_retrieve_api_view(client, dummy_data):
    response = await client.get("/test")
    assert response.json() == dummy_data
    validate_response_meta(response)


@pytest.mark.anyio
async def test_async_retrieve_custom_status_code():
    class CustomStatusRetrieveView(AsyncRetrieveAPIView):
        detail_route = ""
        response_schema = dict

        @override(status_code=203)
        async def retrieve(self) -> dict[str, Any]:
            return {"x": "item"}

    async with view_client(CustomStatusRetrieveView) as c:
        response = await c.get("/test")
        assert response.status_code == 203
        assert response.json() == {"x": "item"}


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
    assert "Content-Type" not in response.headers


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
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"


@pytest.mark.anyio
async def test_async_create_with_location():
    class LocationCreateView(AsyncCreateAPIView):
        def get_location(self, obj):
            return f"/items/{obj['id']}"

        async def create(self) -> dict[str, Any]:
            return {"id": 1, "name": "test"}

    async with view_client(LocationCreateView) as c:
        response = await c.post("/test")
        assert response.status_code == HTTP_201_CREATED
        assert response.headers.get("location") == "/items/1"
        assert response.headers["Content-Type"] == "application/json"


@pytest.mark.anyio
async def test_async_create_no_return():
    class NoReturnCreateView(AsyncCreateAPIView):
        return_on_create = False

        async def create(self) -> dict[str, Any]:
            return {"id": 1}

    async with view_client(NoReturnCreateView) as c:
        response = await c.post("/test")
        assert response.status_code == HTTP_201_CREATED
        assert response.content == b""
        assert "Content-Type" not in response.headers


@pytest.mark.anyio
async def test_async_update_no_return():
    class NoReturnUpdateView(AsyncUpdateAPIView):
        detail_route = ""
        return_on_update = False

        async def update(self) -> dict[str, Any]:
            return {"updated": True}

    async with view_client(NoReturnUpdateView) as c:
        response = await c.put("/test")
        assert response.status_code == HTTP_200_OK
        assert response.content == b""
        assert "Content-Type" not in response.headers


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
        assert response.headers["Content-Type"] == "application/problem+json"


@pytest.mark.anyio
async def test_async_update_no_return_still_raises_not_found():
    class NoReturnNotFoundUpdateView(AsyncUpdateAPIView):
        detail_route = ""
        return_on_update = False

        async def update(self) -> None:
            return None

    async with view_client(NoReturnNotFoundUpdateView, error_handlers=True) as c:
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
        assert response.headers["Content-Type"] == "application/problem+json"


@pytest.mark.anyio
async def test_async_partial_update_no_return():
    class NoReturnPartialView(AsyncPartialUpdateAPIView):
        detail_route = ""
        return_on_update = False

        async def partial_update(self) -> dict[str, Any]:
            return {"updated": True}

    async with view_client(NoReturnPartialView) as c:
        response = await c.patch("/test")
        assert response.status_code == HTTP_200_OK
        assert response.content == b""
        assert "Content-Type" not in response.headers


@pytest.mark.anyio
async def test_async_partial_update_no_return_still_raises_not_found():
    class NoReturnNotFoundPartialView(AsyncPartialUpdateAPIView):
        detail_route = ""
        return_on_update = False

        async def partial_update(self) -> None:
            return None

    async with view_client(NoReturnNotFoundPartialView, error_handlers=True) as c:
        response = await c.patch("/test")
        assert response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_async_partial_update_custom_status_code():
    class CustomStatusPartialView(AsyncPartialUpdateAPIView):
        detail_route = ""
        response_schema = dict

        @override(status_code=202)
        async def partial_update(self) -> dict[str, Any]:
            return {"updated": True}

    async with view_client(CustomStatusPartialView) as c:
        response = await c.patch("/test")
        assert response.status_code == 202
        assert response.json() == {"updated": True}


@pytest.mark.anyio
async def test_partial_update_documents_not_found_and_bad_request():
    class MissingPartialView(AsyncPartialUpdateAPIView):
        detail_route = ""
        response_schema = dict

        async def partial_update(self) -> None:
            return None

    responses = await openapi_responses(MissingPartialView, "patch")
    assert PROBLEM_JSON in responses[str(HTTP_404_NOT_FOUND)]["content"]
    assert PROBLEM_JSON in responses[str(HTTP_400_BAD_REQUEST)]["content"]

    async with view_client(MissingPartialView, error_handlers=True) as client:
        response = await client.patch("/test")
    assert response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_partial_update_documents_bad_request_once():
    class DedupedPartialView(AsyncPartialUpdateAPIView):
        detail_route = ""
        response_schema = dict

        async def partial_update(self) -> dict[str, Any]:
            return {"x": "item"}

    responses = await openapi_responses(DedupedPartialView, "patch")
    bad_request = responses[str(HTTP_400_BAD_REQUEST)]
    assert bad_request["description"] == "Bad Request"
    assert "anyOf" not in bad_request["content"][PROBLEM_JSON]["schema"]


@pytest.mark.anyio
async def test_method_level_responses_keep_generated_errors():
    class ConflictRetrieveView(AsyncRetrieveAPIView):
        detail_route = ""
        response_schema = dict

        @throws(Conflict)
        async def retrieve(self) -> dict[str, Any]:
            return {"x": "item"}

    responses = await openapi_responses(ConflictRetrieveView, "get")
    assert PROBLEM_JSON in responses[str(HTTP_409_CONFLICT)]["content"]
    assert PROBLEM_JSON in responses[str(HTTP_404_NOT_FOUND)]["content"]
    assert PROBLEM_JSON in responses[str(HTTP_400_BAD_REQUEST)]["content"]


@pytest.mark.anyio
async def test_method_level_responses_override_generated_entry():
    class CustomNotFoundView(AsyncRetrieveAPIView):
        detail_route = ""
        response_schema = dict

        @override(
            responses={
                HTTP_404_NOT_FOUND: {
                    "description": "Item is gone",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
            },
        )
        async def retrieve(self) -> dict[str, Any]:
            return {"x": "item"}

    responses = await openapi_responses(CustomNotFoundView, "get")
    not_found = responses[str(HTTP_404_NOT_FOUND)]
    assert not_found["description"] == "Item is gone"
    assert list(not_found["content"]) == ["application/json"]
    assert PROBLEM_JSON in responses[str(HTTP_400_BAD_REQUEST)]["content"]


@pytest.mark.anyio
async def test_method_level_response_model_replaces_generated_content():
    class Missing(BaseModel):
        reason: str

    class ModelNotFoundView(AsyncRetrieveAPIView):
        detail_route = ""
        response_schema = dict

        @override(responses={HTTP_404_NOT_FOUND: {"model": Missing}})
        async def retrieve(self) -> dict[str, Any]:
            return {"x": "item"}

    responses = await openapi_responses(ModelNotFoundView, "get")
    assert list(responses[str(HTTP_404_NOT_FOUND)]["content"]) == ["application/json"]


class TotalHeaders(ResponseHeaders):
    x_total_count: int = Field(description="Total number of items")


@pytest.mark.anyio
async def test_method_level_responses_keep_headers_and_conditional_responses():
    class DocumentedRetrieveView(ConditionalMixin, AsyncRetrieveAPIView):
        detail_route = ""
        response_schema = dict
        etag = True

        @classmethod
        def get_response_headers(cls, _action: Any = None) -> type[ResponseHeaders]:
            return TotalHeaders

        @throws(Conflict)
        @override(responses={HTTP_200_OK: {"description": "Custom success"}})
        async def retrieve(self) -> dict[str, Any]:
            return {"x": "item"}

    responses = await openapi_responses(DocumentedRetrieveView, "get")
    success = responses[str(HTTP_200_OK)]
    assert success["description"] == "Custom success"
    assert set(success["headers"]) == {"x_total_count", "ETag"}
    assert "application/json" in success["content"]
    assert "ETag" in responses[str(HTTP_304_NOT_MODIFIED)]["headers"]
    assert PROBLEM_JSON in responses[str(HTTP_409_CONFLICT)]["content"]
    assert PROBLEM_JSON in responses[str(HTTP_404_NOT_FOUND)]["content"]


@pytest.mark.anyio
async def test_custom_route_documents_headers_and_conditional_responses():
    class CustomRouteView(ConditionalMixin, APIView):
        response_schema = dict
        etag = True

        @classmethod
        def get_response_headers(cls, _action: Any = None) -> type[ResponseHeaders]:
            return TotalHeaders

        @get(path="/custom")
        async def custom(self) -> dict[str, Any]:
            return {"x": "item"}

    responses = await openapi_responses(CustomRouteView, "get", path="/test/custom")
    success = responses[str(HTTP_200_OK)]
    assert set(success["headers"]) == {"x_total_count", "ETag"}
    assert "ETag" in responses[str(HTTP_304_NOT_MODIFIED)]["headers"]


def test_base_list_api_view_get_response_schema_non_list_action():
    class MyListView(AsyncListAPIView):
        response_schema = dict

        async def list(self) -> list[dict[str, Any]]:
            return []

    assert MyListView.get_response_schema(action=None) is dict
    assert MyListView.get_response_schema(action="retrieve") is dict
