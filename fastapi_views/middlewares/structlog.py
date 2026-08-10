import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import uuid4

import structlog
from starlette.requests import Request
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fastapi_views.headers import (
    DEFAULT_REQUEST_HEADER_FILTER,
    DEFAULT_RESPONSE_HEADER_FILTER,
    HeaderFilter,
)

logger = structlog.get_logger("fastapi.access")


class _SuppressExceptionInASGI(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Exception in ASGI application" not in record.getMessage()


def _get_log_level_for_status(status_code: int | None) -> int:
    if status_code is None:
        return logging.INFO
    if status_code >= HTTP_500_INTERNAL_SERVER_ERROR:
        return logging.ERROR
    if status_code >= HTTP_400_BAD_REQUEST:
        return logging.WARNING
    return logging.INFO


class RequestLoggingMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        exclude: Sequence[str] = ("/healthcheck",),
        extra_context: Callable[[Request], Awaitable[dict[str, Any]]] | None = None,
        request_header_filter: HeaderFilter = DEFAULT_REQUEST_HEADER_FILTER,
        response_header_filter: HeaderFilter = DEFAULT_RESPONSE_HEADER_FILTER,
    ) -> None:
        self.app = app
        self._excluded = exclude
        self._extra_context = extra_context
        self._request_header_filter = request_header_filter
        self._response_header_filter = response_header_filter
        logging.getLogger("uvicorn.access").propagate = False
        logging.getLogger("uvicorn.error").addFilter(_SuppressExceptionInASGI())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        start_time = time.monotonic()
        structlog.contextvars.clear_contextvars()

        context: dict[str, Any] = {
            "request_id": request.headers.get("X-Request-Id", str(uuid4())),
            "client": f"{request.client.host}:{request.client.port}"
            if request.client
            else "unknown",
        }

        structlog.contextvars.bind_contextvars(**context)

        request_logger = logger.bind(method=request.method, path=request.url.path)
        excluded = request.url.path in self._excluded
        if not excluded:
            extra = {}
            if self._extra_context:
                extra = await self._extra_context(request)
            query_params = dict(request.query_params)
            request_logger.info(
                "request",
                query_params=query_params,
                headers=self._request_header_filter(request.headers),
                **extra,
            )

        status_code: int | None = None
        response_headers: dict[str, str] = {}

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = self._response_header_filter.filter_raw(
                    message.get("headers", ())
                )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            if status_code is None:
                status_code = HTTP_500_INTERNAL_SERVER_ERROR
            raise
        finally:
            if not excluded:
                request_logger.log(
                    _get_log_level_for_status(status_code),
                    "response",
                    status_code=status_code,
                    duration_ms=round((time.monotonic() - start_time) * 1000, 2),
                    headers=response_headers,
                )
