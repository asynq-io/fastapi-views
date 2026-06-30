from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn

from fastapi import Depends, Response
from pydantic import Field
from starlette.status import HTTP_304_NOT_MODIFIED, HTTP_400_BAD_REQUEST

from fastapi_views.exceptions import APIError, NotFound
from fastapi_views.models import ResponseHeaders

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def _format_etag(value: str) -> str:
    """Wrap a raw validator in the double quotes an ETag requires (RFC 9110).

    Already-formatted tags (quoted, or weak ``W/"..."``) are returned unchanged,
    so callers may pass either ``saved.version`` or a full ``'"v1"'``.
    """
    if value.startswith(('"', "W/")):
        return value
    return f'"{value}"'


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


class ConditionalHeaders(ResponseHeaders):
    """Validator headers attached to conditional (``304``-capable) responses."""

    etag: str | None = Field(
        default=None,
        alias="ETag",
        description="Validator for the returned representation",
    )
    last_modified: str | None = Field(
        default=None,
        alias="Last-Modified",
        description="Time the representation was last modified",
        json_schema_extra={"format": "http-date"},
    )


class ConditionalMixin:
    """ETag / ``Last-Modified`` validators and ``304 Not Modified`` handling.

    Two ways to opt in:

    * **Automatic** — set ``etag = True`` for a strong ETag hashed from the
      serialised body, and/or set ``last_modified = True`` and override
      :meth:`get_last_modified`. The body is built, then downgraded to a ``304``
      if the client is current.
    * **Manual / cheap** — compare a cheaply obtained validator (a version
      column, ``updated_at``) inside the view and short-circuit before building
      the body, returning :meth:`not_modified`::

          conditional_requests = True  # so the 304 is documented in OpenAPI

          async def retrieve(self, item_id: int) -> Item | Response:
              item = await self.get_item(item_id)
              if self.not_modified_since(item.updated_at):
                  return self.not_modified(last_modified=item.updated_at)
              return item

      or, for versioned models, with an ETag::

          async def retrieve(self, item_id: int) -> Item | Response:
              item = await self.get_item(item_id)
              etag = f'"{item.version}"'
              if self.etag_matches(etag):
                  return self.not_modified(etag=etag)
              return item
    """

    request: Request
    response: Response
    etag: bool = False
    last_modified: bool = False
    conditional_requests: bool = False

    def finalize_response(self, response: Response) -> Response:
        return self.make_conditional(response)

    def get_etag(self, body: bytes) -> str | None:
        if self.etag:
            return hashlib.blake2b(body, digest_size=16).hexdigest()
        return None

    @property
    def if_none_match(self) -> str | None:
        """The request's ``If-None-Match`` validator, if sent."""
        return self.request.headers.get("if-none-match")

    @property
    def if_modified_since(self) -> datetime | None:
        """The request's parsed ``If-Modified-Since`` timestamp, if sent."""
        value = self.request.headers.get("if-modified-since")
        return _parse_http_date(value) if value is not None else None

    def etag_matches(self, etag: str) -> bool:
        """Whether ``If-None-Match`` matches ``etag`` (handles ``*`` and lists).

        ``etag`` may be a raw value (e.g. ``str(version)``); it is quoted to a
        valid entity-tag before comparison.
        """
        if_none_match = self.if_none_match
        return if_none_match is not None and _etag_matches(
            if_none_match, _format_etag(etag)
        )

    def not_modified_since(self, last_modified: datetime) -> bool:
        """Whether ``last_modified`` is not newer than ``If-Modified-Since``."""
        since = self.if_modified_since
        return since is not None and _to_utc_seconds(last_modified) <= since

    def not_modified(
        self,
        *,
        etag: str | None = None,
        last_modified: datetime | None = None,
    ) -> Response:
        """Build a ``304 Not Modified`` response, echoing any given validators.

        Return this from a view to skip building and serialising the body once
        you have determined the client's cached copy is still current.
        """
        headers: dict[str, str] = {}
        if etag is not None:
            headers["etag"] = _format_etag(etag)
        if last_modified is not None:
            headers["last-modified"] = format_datetime(
                _to_utc_seconds(last_modified), usegmt=True
            )
        return Response(status_code=HTTP_304_NOT_MODIFIED, headers=headers)

    def set_etag(self, etag: str) -> None:
        """Send ``etag`` as the ``ETag`` header on this request's response.

        A raw value (e.g. ``str(version)``) is quoted to a valid entity-tag.
        """
        self.response.headers["etag"] = _format_etag(etag)

    def set_last_modified(self, last_modified: datetime) -> None:
        """Send ``last_modified`` as the ``Last-Modified`` header on the response."""
        self.response.headers["last-modified"] = format_datetime(
            _to_utc_seconds(last_modified), usegmt=True
        )

    def check_etag(self, etag: str) -> Response | None:
        """Return a ``304`` when the client's copy matches ``etag``.

        Otherwise stamp ``etag`` on the upcoming response and return ``None``,
        so ``return self.check_etag(tag) or item`` skips serialising the body
        when the client is current and sends the validator on the body response.
        """
        if self.etag_matches(etag):
            return self.not_modified(etag=etag)
        self.set_etag(etag)
        return None

    def check_last_modified(self, last_modified: datetime) -> Response | None:
        """``Last-Modified`` counterpart of :meth:`check_etag`."""
        if self.not_modified_since(last_modified):
            return self.not_modified(last_modified=last_modified)
        self.set_last_modified(last_modified)
        return None

    def get_last_modified(self) -> datetime | None:
        return None

    @classmethod
    def supports_conditional_requests(cls) -> bool:
        """Whether the view emits validators (an ETag or ``Last-Modified``)."""
        return cls.etag or cls.last_modified or cls.conditional_requests

    @classmethod
    def _conditional_response_headers(cls) -> dict[str, Any]:
        schema = ConditionalHeaders.get_openapi_schema()
        headers: dict[str, Any] = {}
        if cls.etag or cls.conditional_requests:
            headers["ETag"] = schema["ETag"]
        if cls.last_modified or cls.conditional_requests:
            headers["Last-Modified"] = schema["Last-Modified"]
        return headers

    @classmethod
    def get_conditional_responses(
        cls,
        *,
        action: Action | None = None,  # noqa: ARG003
        status_code: int | None = None,
        methods: Sequence[str] | None = None,
    ) -> dict[int | str, dict[str, Any]]:
        """Document validator headers and a ``304 Not Modified`` response.

        ``ETag`` / ``Last-Modified`` are documented on the success response and,
        for safe methods, a ``304`` is added — but only when the view actually
        emits a validator, so views that set none are not documented with
        headers or a ``304`` they will never return.
        """
        headers = cls._conditional_response_headers()
        if not headers:
            return {}
        responses: dict[int | str, dict[str, Any]] = {}
        if status_code is not None:
            responses[status_code] = {"headers": headers}
        if methods and any(method in _SAFE_METHODS for method in methods):
            responses[HTTP_304_NOT_MODIFIED] = {
                "description": "Not Modified",
                "headers": headers,
            }
        return responses

    def make_conditional(self, response: Response) -> Response:
        """Attach validators and downgrade to 304 when the client is current."""
        if not isinstance(response.body, bytes) or not (
            _SUCCESS_MIN <= response.status_code < _SUCCESS_MAX
        ):
            return response

        etag = self.get_etag(response.body)
        if etag is not None:
            etag = _format_etag(etag)
        last_modified = self.get_last_modified() if self.last_modified else None
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
        if self.if_none_match is not None:
            # RFC 7232: If-Modified-Since is ignored when If-None-Match is present.
            return etag is not None and self.etag_matches(etag)
        return last_modified is not None and self.not_modified_since(last_modified)
