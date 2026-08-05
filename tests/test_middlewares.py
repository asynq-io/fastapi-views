from __future__ import annotations

import logging

import pytest
import structlog
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from fastapi_views.middlewares.limits import RequestLimitMiddleware
from fastapi_views.middlewares.structlog import (
    RequestLoggingMiddleware,
    _get_log_level_for_status,
    _SuppressExceptionInASGI,
)


def make_http_scope(path="/", query_string=b"", headers=(), client=None):
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": list(headers),
        "client": client,
        "server": ("testserver", 80),
    }


def make_log_record(message):
    return logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=None,
        exc_info=None,
    )


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (None, logging.INFO),
        (200, logging.INFO),
        (400, logging.WARNING),
        (404, logging.WARNING),
        (500, logging.ERROR),
        (503, logging.ERROR),
    ],
)
def test_get_log_level_for_status(status_code, expected):
    assert _get_log_level_for_status(status_code) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Exception in ASGI application", False),
        ("Something happened: Exception in ASGI application!", False),
        ("Application startup complete.", True),
    ],
)
def test_suppress_exception_in_asgi_filter(message, expected):
    assert _SuppressExceptionInASGI().filter(make_log_record(message)) is expected


@pytest.mark.anyio
async def test_request_logging_middleware_passes_through_non_http_scope():
    calls = []

    async def asgi_app(scope, receive, send):
        calls.append((scope, receive, send))

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        calls.append(message)

    middleware = RequestLoggingMiddleware(asgi_app)
    scope = {"type": "lifespan"}

    with capture_logs() as logs:
        await middleware(scope, receive, send)

    assert calls == [(scope, receive, send)]
    assert logs == []


@pytest.mark.anyio
async def test_request_logging_middleware_logs_request_and_response(app):
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/items")
    async def get_items() -> dict:
        return structlog.contextvars.get_contextvars()

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with capture_logs() as logs:
                response = await client.get(
                    "/items?foo=bar",
                    headers={
                        "X-Request-Id": "test-request-id",
                        "Authorization": "Bearer secret",
                    },
                )

    assert response.status_code == 200
    context = response.json()
    assert context["request_id"] == "test-request-id"
    assert context["client"] == "127.0.0.1:123"

    request_log, response_log = logs
    assert request_log["event"] == "request"
    assert request_log["method"] == "GET"
    assert request_log["path"] == "/items"
    assert request_log["query_params"] == {"foo": "bar"}
    assert request_log["headers"]["x_request_id"] == "test-request-id"
    assert "authorization" not in request_log["headers"]

    assert response_log["event"] == "response"
    assert response_log["log_level"] == "info"
    assert response_log["status_code"] == 200
    assert response_log["duration_ms"] >= 0
    assert response_log["headers"]["content_type"] == "application/json"


@pytest.mark.anyio
async def test_request_logging_middleware_skips_excluded_path(app):
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/healthcheck")
    async def healthcheck() -> dict:
        return {"status": "ok"}

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with capture_logs() as logs:
                response = await client.get("/healthcheck")

    assert response.status_code == 200
    assert logs == []


@pytest.mark.anyio
async def test_request_logging_middleware_merges_extra_context(app):
    async def extra_context(request) -> dict:
        return {"tenant": request.headers.get("X-Tenant")}

    app.add_middleware(RequestLoggingMiddleware, extra_context=extra_context)

    @app.get("/items")
    async def get_items() -> dict:
        return {}

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with capture_logs() as logs:
                response = await client.get("/items", headers={"X-Tenant": "acme"})

    assert response.status_code == 200
    request_log = logs[0]
    assert request_log["event"] == "request"
    assert request_log["tenant"] == "acme"


@pytest.mark.anyio
async def test_request_logging_middleware_logs_and_reraises_unhandled_exception():
    async def failing_app(scope, receive, send):
        assert scope["type"] == "http"
        assert receive is not None
        assert send is not None
        raise ValueError("boom")

    async def receive():
        return {"type": "http.request", "body": b""}

    sent = []

    async def send(message):
        sent.append(message)

    middleware = RequestLoggingMiddleware(failing_app)
    scope = make_http_scope(path="/fail", query_string=b"x=1")

    with capture_logs() as logs, pytest.raises(ValueError, match="boom"):
        await middleware(scope, receive, send)

    context = structlog.contextvars.get_contextvars()
    assert context["client"] == "unknown"
    structlog.contextvars.clear_contextvars()

    request_log, exception_log = logs
    assert request_log["event"] == "request"
    assert exception_log["event"] == "unhandled_exception"
    assert exception_log["log_level"] == "error"
    assert exception_log["exc_info"] is True
    assert exception_log["url"] == "http://testserver/fail?x=1"
    assert exception_log["query_params"] == {"x": "1"}
    assert exception_log["duration_ms"] >= 0
    assert sent == []


@pytest.mark.anyio
async def test_request_limit_middleware_passes_through_non_http_scope():
    calls = []

    async def asgi_app(scope, receive, send):
        calls.append((scope, receive, send))

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        calls.append(message)

    middleware = RequestLimitMiddleware(asgi_app, limit=1)
    scope = {"type": "lifespan"}

    await middleware(scope, receive, send)

    assert calls == [(scope, receive, send)]


@pytest.mark.anyio
async def test_request_limit_middleware_handles_http_request(app):
    app.add_middleware(RequestLimitMiddleware, limit=2)

    @app.get("/items")
    async def get_items() -> dict:
        return {"ok": True}

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/items")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
