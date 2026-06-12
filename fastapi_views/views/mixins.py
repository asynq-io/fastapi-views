from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn

from fastapi import Depends, Response
from starlette.status import HTTP_304_NOT_MODIFIED, HTTP_400_BAD_REQUEST

from fastapi_views.exceptions import APIError, NotFound

if TYPE_CHECKING:
    from fastapi import Request

    from fastapi_views.types import Action


class DependencyMixin:
    @classmethod
    def _patch_endpoint_signature(cls, endpoint: Any, method: Callable) -> None:
        old_signature = inspect.signature(method)
        old_parameters: list[inspect.Parameter] = list(
            old_signature.parameters.values(),
        )
        old_first_parameter = old_parameters[0]
        new_first_parameter = old_first_parameter.replace(default=Depends(cls))
        new_parameters = [new_first_parameter] + [
            parameter.replace(kind=inspect.Parameter.KEYWORD_ONLY)
            for parameter in old_parameters[1:]
        ]
        new_signature = old_signature.replace(parameters=new_parameters)
        endpoint.__signature__ = new_signature
        endpoint.__doc__ = method.__doc__
        endpoint.__name__ = method.__name__
        endpoint.kwargs = getattr(method, "kwargs", {})


class DetailViewMixin:
    detail_route: str = "/{id}"
    raise_on_none: bool = True
    request: Request
    get_name: Callable[..., str]
    error_message = "{} does not exist"

    @classmethod
    def get_detail_route(cls, action: Action) -> str:  # noqa: ARG003
        return cls.detail_route

    def raise_not_found_error(self) -> NoReturn:
        msg = self.error_message.format(self.get_name())
        raise NotFound(msg)


class _Sentinel(Exception):
    pass


class ErrorHandlerMixin:
    request: Request

    raises: ClassVar[dict[type[Exception], str | dict[str, Any]]] = {}

    def get_error_message(self, key: type[Exception]) -> str | dict[str, Any]:
        return self.raises.get(key, {})

    def handle_error(self, exc: Exception, **kwargs: Any) -> NoReturn:
        kw = self.get_error_message(type(exc))
        if isinstance(kw, str):
            kwargs["detail"] = kw
        elif isinstance(kw, Mapping):
            kwargs.update(kw)
        kwargs.setdefault("instance", self.request.url.path)
        kwargs.setdefault("title", type(exc).__name__)
        kwargs.setdefault("detail", str(exc))
        kwargs.setdefault("status", HTTP_400_BAD_REQUEST)
        raise APIError(**kwargs)

    def get_exception_class(self) -> tuple[type[Exception], ...] | type[Exception]:
        return tuple(self.raises.keys()) or _Sentinel


_SAFE_METHODS = ("GET", "HEAD")
# Headers a 304 is allowed/expected to carry over from the full response.
_REVALIDATION_HEADERS = (
    "etag",
    "last-modified",
    "cache-control",
    "expires",
    "vary",
    "x-cache",
)
_SUCCESS_MIN, _SUCCESS_MAX = 200, 300


def _strip_weak(tag: str) -> str:
    return tag.removeprefix("W/")


def _etag_matches(if_none_match: str, etag: str) -> bool:
    if if_none_match.strip() == "*":
        return True
    target = _strip_weak(etag)
    return any(_strip_weak(t.strip()) == target for t in if_none_match.split(","))


def _parse_http_date(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _to_utc_seconds(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    # HTTP dates have one-second resolution; drop anything finer.
    return value.astimezone(timezone.utc).replace(microsecond=0)


class ConditionalMixin:
    """ETag / ``Last-Modified`` validators and ``304 Not Modified`` handling.

    Opt in per view: set ``etag = True`` for a strong ETag hashed from the body,
    and/or override :meth:`get_last_modified`. Override :meth:`get_etag` for a
    custom validator (e.g. a version/updated_at column instead of a body hash).
    """

    request: Request
    etag: bool = False

    def get_etag(self, body: bytes) -> str | None:
        if self.etag:
            return f'"{hashlib.blake2b(body, digest_size=16).hexdigest()}"'
        return None

    def get_last_modified(self) -> datetime | None:
        return None

    def make_conditional(self, response: Response) -> Response:
        """Attach validators and downgrade to 304 when the client is current."""
        if not isinstance(response.body, bytes) or not (
            _SUCCESS_MIN <= response.status_code < _SUCCESS_MAX
        ):
            return response

        etag = self.get_etag(response.body)
        last_modified = self.get_last_modified()
        headers = response.headers
        if etag:
            headers["etag"] = etag
        if last_modified is not None:
            headers["last-modified"] = format_datetime(
                _to_utc_seconds(last_modified), usegmt=True
            )

        if self.request.method in _SAFE_METHODS and self._is_not_modified(
            etag, last_modified
        ):
            carried = {
                name: headers[name] for name in _REVALIDATION_HEADERS if name in headers
            }
            return Response(status_code=HTTP_304_NOT_MODIFIED, headers=carried)
        return response

    def _is_not_modified(
        self, etag: str | None, last_modified: datetime | None
    ) -> bool:
        headers = self.request.headers
        if_none_match = headers.get("if-none-match")
        if if_none_match is not None:
            # RFC 7232: If-Modified-Since is ignored when If-None-Match is present.
            return etag is not None and _etag_matches(if_none_match, etag)
        if_modified_since = headers.get("if-modified-since")
        if if_modified_since is not None and last_modified is not None:
            since = _parse_http_date(if_modified_since)
            return since is not None and _to_utc_seconds(last_modified) <= since
        return False
