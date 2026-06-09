import logging
import time
from collections.abc import Sequence

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR
from starlette.types import ASGIApp

logger = structlog.get_logger("fastapi_views.access")


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


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app: ASGIApp, exclude: Sequence[str] = ("/healthcheck",)
    ) -> None:
        super().__init__(app, None)
        self._excluded = exclude
        logging.getLogger("uvicorn.access").propagate = False
        logging.getLogger("uvicorn.error").addFilter(_SuppressExceptionInASGI())

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start_time = time.monotonic()
        structlog.contextvars.clear_contextvars()

        client = (
            f"{request.client.host}:{request.client.port}"
            if request.client
            else "unknown"
        )
        url_path = request.url.path
        request_logger = logger.bind(
            method=request.method,
            path=url_path,
        )
        excluded = url_path in self._excluded
        if excluded:
            return await call_next(request)
        user_agent = request.headers.get("User-Agent", "unknown")
        request_logger.info("request", user_agent=user_agent, client=client)
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            request_logger.log(
                _get_log_level_for_status(status_code),
                "response",
                status_code=status_code,
                duration_ms=duration_ms,
            )
