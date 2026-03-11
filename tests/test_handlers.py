from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)

from fastapi_views.exceptions import APIError, BadRequest, InternalServerError
from fastapi_views.handlers import (
    add_error_handlers,
    api_error_handler,
    http_exception_handler,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
def handler_app():
    app = FastAPI()
    add_error_handlers(app)

    class Body(BaseModel):
        name: str

    @app.get("/api-error")
    def raise_api_error():
        msg = "test error"
        raise BadRequest(msg)

    @app.get("/api-error-no-instance")
    def raise_api_error_no_instance():
        # Raise without instance to test the None-instance path in api_error_handler
        msg = "no instance error"
        raise BadRequest(msg)

    @app.get("/http-error")
    def raise_http_error():
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="not found")

    @app.get("/http-error-with-headers")
    def raise_http_error_with_headers():
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="forbidden",
            headers={"x-reason": "denied"},
        )

    @app.get("/unhandled")
    def raise_unhandled():
        msg = "unhandled error"
        raise RuntimeError(msg)

    @app.post("/validation-error")
    def validate_body(body: Body):
        return body

    return app


@pytest.fixture
async def handler_client(handler_app) -> AsyncGenerator[AsyncClient, None]:
    async with (
        LifespanManager(handler_app, startup_timeout=30),
        AsyncClient(
            transport=ASGITransport(app=handler_app),
            base_url="http://test",
        ) as client,
    ):
        yield client


@pytest.mark.anyio
async def test_api_error_handler_response(handler_client):
    response = await handler_client.get("/api-error")
    assert response.status_code == HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["detail"] == "test error"
    assert data["status"] == HTTP_400_BAD_REQUEST
    assert data["instance"] == "/api-error"


@pytest.mark.anyio
async def test_api_error_handler_sets_instance(handler_client):
    response = await handler_client.get("/api-error-no-instance")
    assert response.status_code == HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["instance"] == "/api-error-no-instance"


@pytest.mark.anyio
async def test_http_exception_handler(handler_client):
    response = await handler_client.get("/http-error")
    assert response.status_code == HTTP_404_NOT_FOUND
    data = response.json()
    assert "not found" in data["detail"]
    assert data["status"] == HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_http_exception_handler_with_headers(handler_client):
    response = await handler_client.get("/http-error-with-headers")
    assert response.status_code == HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_request_validation_handler(handler_client):
    response = await handler_client.post("/validation-error", json={"invalid": "data"})
    assert response.status_code == HTTP_400_BAD_REQUEST
    data = response.json()
    assert "errors" in data
    assert len(data["errors"]) > 0


@pytest.mark.anyio
async def test_unhandled_exception_handler(handler_client):
    # exception_handler raises InternalServerError which propagates from the handler
    with pytest.raises(InternalServerError):
        await handler_client.get("/unhandled")


@pytest.mark.anyio
async def test_add_error_handlers_registers_all(handler_app):
    # Verify error handlers are registered by checking exception handlers
    exception_handlers = handler_app.exception_handlers
    assert APIError in exception_handlers or len(exception_handlers) >= 4


def test_api_error_handler_direct():
    request = MagicMock()
    request.url.path = "/test"

    err = BadRequest("direct test")
    response = api_error_handler(request, err)
    assert response.status_code == HTTP_400_BAD_REQUEST


def test_http_exception_handler_direct():
    request = MagicMock()
    request.url.path = "/test"

    exc = HTTPException(status_code=HTTP_404_NOT_FOUND, detail="not found")
    response = http_exception_handler(request, exc)
    assert response.status_code == HTTP_404_NOT_FOUND


def test_api_error_handler_with_instance_already_set():
    request = MagicMock()
    request.url.path = "/test"

    err = BadRequest("with instance", instance="/custom/path")
    response = api_error_handler(request, err)
    assert response.status_code == HTTP_400_BAD_REQUEST
