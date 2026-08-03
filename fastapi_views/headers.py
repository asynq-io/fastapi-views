from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

DEFAULT_REQUEST_HEADERS = frozenset(
    {
        "origin",
        "referer",
        "host",
        "user-agent",
        "content-type",
        "content-length",
        "accept",
        "accept-encoding",
        "accept-language",
        "access-control-request-method",
        "access-control-request-headers",
        "x-request-id",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
    }
)
DEFAULT_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "vary",
        "access-control-allow-origin",
        "access-control-allow-credentials",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-expose-headers",
        "access-control-max-age",
    }
)


class HeaderFilter:
    """Allow-list of header names safe to include in logs.

    Headers outside the allow-list are dropped, so credential-bearing headers
    (`authorization`, `cookie`, `set-cookie`, api keys) never reach the logs.
    """

    __slots__ = ("allowed",)

    def __init__(self, allowed: Collection[str] = DEFAULT_REQUEST_HEADERS) -> None:
        self.allowed = frozenset(name.lower() for name in allowed)

    def __call__(self, headers: Mapping[str, str]) -> dict[str, str]:
        """Return the allowed headers only, keyed by snake_case name."""
        return self._select(headers.items())

    def filter_raw(self, headers: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
        """Return the allowed headers only, from raw ASGI name/value pairs."""
        return self._select(
            (name.decode("latin-1"), value.decode("latin-1")) for name, value in headers
        )

    def _select(self, items: Iterable[tuple[str, str]]) -> dict[str, str]:
        lowered = ((name.lower(), value) for name, value in items)
        return {
            name.replace("-", "_"): value
            for name, value in lowered
            if name in self.allowed
        }


DEFAULT_REQUEST_HEADER_FILTER = HeaderFilter(DEFAULT_REQUEST_HEADERS)
DEFAULT_RESPONSE_HEADER_FILTER = HeaderFilter(DEFAULT_RESPONSE_HEADERS)
