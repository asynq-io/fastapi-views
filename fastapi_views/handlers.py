from logging import getLogger

from fastapi import Request
from fastapi.applications import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException
from typing_extensions import Never

from .exceptions import APIError, BadRequest, InternalServerError

logger = getLogger("exceptions.handler")


def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    error = APIError(
        exc.detail,
        status=exc.status_code,
        instance=request.url.path,
    )
    return Response(
        content=error.as_model().model_dump_json(),
        status_code=exc.status_code,
        headers=exc.headers,
        media_type="application/json",
    )


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


def request_validation_handler(request: Request, exc: RequestValidationError) -> Never:
    msg = "Request validation error"
    raise BadRequest(
        msg,
        instance=request.url.path,
        errors=jsonable_encoder(exc.errors()),
    )


def exception_handler(request: Request, exc: Exception) -> Never:
    msg = "Unhandled server error"
    logger.exception(msg, exc_info=exc)
    raise InternalServerError(
        msg,
        instance=request.url.path,
    )


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type, unused-ignore]
    app.add_exception_handler(RequestValidationError, request_validation_handler)  # type: ignore[arg-type, unused-ignore]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type, unused-ignore]
    app.add_exception_handler(ResponseValidationError, exception_handler)
    app.add_exception_handler(Exception, exception_handler)
