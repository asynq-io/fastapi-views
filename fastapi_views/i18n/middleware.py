from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from .translations import TranslationManager


class LocaleMiddleware:
    def __init__(self, app: ASGIApp, manager: TranslationManager) -> None:
        self.app = app
        self.manager = manager

    def _detect_best_locale(self, request: Request) -> tuple[str, bool]:
        """
        Determines the user's preferred locale by checking:
        1. Query parameter (`?lang=xx`)
        2. Stored cookie (`preferred_locale`)
        3. Accept-Language header
        4. Default locale (fallback)
        returns best match and flag for setting cookie

        Each candidate tag is resolved to a supported locale by the translation
        manager (exact match, configured fallback, then language subtag).
        """
        locale_query = request.query_params.get("lang")
        if locale_query and (match := self.manager.match_supported(locale_query)):
            return match, True
        preferred = request.cookies.get("locale")
        if preferred and (match := self.manager.match_supported(preferred)):
            return match, False
        accept_language = request.headers.get("Accept-Language", "")
        for locale_tag in self._parse_accept_language(accept_language):
            if match := self.manager.match_supported(locale_tag):
                return match, False

        return self.manager.default, False

    @staticmethod
    def _parse_accept_language(header: str) -> list[str]:
        """Return the header's language tags ordered best-first by ``q`` value.

        Tags are sorted by quality (descending); ties keep their original order.
        Tags with ``q=0`` (or a malformed quality) are dropped, as is the ``*``
        wildcard.
        """
        parsed: list[tuple[float, int, str]] = []
        for index, part in enumerate(header.split(",")):
            tag, _, params = part.strip().partition(";")
            tag = tag.strip()
            if not tag or tag == "*":
                continue
            quality = 1.0
            for param in params.split(";"):
                name, _, value = param.partition("=")
                if name.strip() == "q":
                    try:
                        quality = float(value.strip())
                    except ValueError:
                        quality = 0.0
            if quality > 0:
                # negate quality so natural tuple ordering puts the highest
                # quality first, with the original index breaking ties
                parsed.append((-quality, index, tag))
        parsed.sort()
        return [tag for _, _, tag in parsed]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Detect the locale from query param, cookie or header.
        request = Request(scope)
        locale, set_cookie = self._detect_best_locale(request)
        self.manager.set_locale(locale)

        # Build the Set-Cookie header once, reusing Starlette's serialization.
        # `secure` tracks the request scheme so the cookie hardens over HTTPS
        # without breaking plain-HTTP local development.
        cookie_header: str | None = None
        if set_cookie:
            holder = Response()
            holder.set_cookie(
                "locale",
                locale,
                max_age=30 * 24 * 3600,
                samesite="lax",
                secure=request.url.scheme == "https",
            )
            cookie_header = holder.headers["set-cookie"]

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Language"] = locale
                if cookie_header is not None:
                    headers.append("set-cookie", cookie_header)
            await send(message)

        await self.app(scope, receive, send_wrapper)
