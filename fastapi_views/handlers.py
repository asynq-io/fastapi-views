from fastapi import Request
from fastapi.applications import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException

from .exceptions import APIError, BadRequest, InternalServerError
from .i18n import gettext_lazy as _
from .logging._compat import get_logger

logger = get_logger("exceptions.handler")


def _api_error_to_response(error: APIError) -> Response:
    model = error.as_model()
    return Response(
        content=model.model_dump_json(),
        status_code=error.status_code,
        media_type="application/json",
        headers=error.headers,
    )


def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    error = APIError(
        _(exc.detail),
        status=exc.status_code,
        instance=request.url.path,
        headers=exc.headers,
    )
    return _api_error_to_response(error)


def api_error_handler(request: Request, exc: APIError) -> Response:
    exc.set_default_instance(request.url.path)
    return _api_error_to_response(exc)


def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    return _api_error_to_response(
        BadRequest(
            _("Request validation error"),
            instance=request.url.path,
            errors=jsonable_encoder(exc.errors()),
        )
    )


def exception_handler(request: Request, exc: Exception) -> Response:
    logger.exception(
        "unhandled_exception",
        exc_info=exc,
        url=request.url,
        headers=dict(request.headers),
        query_params=dict(request.query_params),
    )
    return _api_error_to_response(
        InternalServerError(
            _("Unhandled server error"),
            instance=request.url.path,
        )
    )


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type, unused-ignore]
    app.add_exception_handler(RequestValidationError, request_validation_handler)  # type: ignore[arg-type, unused-ignore]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type, unused-ignore]
    app.add_exception_handler(ResponseValidationError, exception_handler)
    app.add_exception_handler(Exception, exception_handler)
