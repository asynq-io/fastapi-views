from logging import getLogger

from fastapi import Request
from fastapi.applications import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from .exceptions import APIError
from .models import BadRequestErrorDetails, InternalServerErrorDetails

logger = getLogger("exceptions.handler")


def api_error_handler(request: Request, exc: APIError) -> Response:
    model = exc.as_model()
    if model.instance is None:
        model.instance = request.url.path
    return Response(
        content=model.model_dump_json(),
        status_code=model.status,
        headers=exc.headers,
        media_type="application/json",
    )


def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    model = BadRequestErrorDetails(
        detail="Validation error",
        instance=request.url.path,
        errors=exc.errors(),
    )
    return Response(
        content=model.model_dump_json(),
        status_code=model.status,
        media_type="application/json",
    )


def exception_handler(request: Request, exc: Exception) -> Response:
    logger.exception("Unhandled exception", exc_info=exc)
    return Response(
        content=InternalServerErrorDetails(
            detail="Unhandled server error",
            instance=request.url.path,
        ).model_dump_json(),
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        media_type="application/json",
    )


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(Exception, exception_handler)
