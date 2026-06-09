from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .locale import set_locale

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp


class LocaleMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        default_locale: str = "en",
        supported_locales: Sequence[str] | None = None,
    ) -> None:
        super().__init__(app, None)
        self.default_locale = default_locale
        self.supported_locales = supported_locales or (default_locale,)

    def _detect_best_locale(self, request: Request) -> tuple[str, bool]:
        """
        Determines the user's preferred locale by checking:
        1. Query parameter (`?lang=xx`)
        2. Stored cookie (`preferred_locale`)
        3. Accept-Language header
        4. Default locale (fallback)
        returns best match and flag for setting cookie
        """
        locale_query = request.query_params.get("lang")
        if locale_query and locale_query in self.supported_locales:
            return locale_query, True
        preffered = request.cookies.get("locale")
        if preffered and preffered in self.supported_locales:
            return preffered, False
        accept_language = request.headers.get("Accept-Language", "")
        for tag in accept_language.split(","):
            locale_tag = tag.split(";")[0].strip()
            if locale_tag in self.supported_locales:
                return locale_tag, False
            lang = locale_tag.split("-")[0]
            if lang in self.supported_locales:
                return lang, False

        return self.default_locale, False

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Get locale from query param, header or cookie
        locale, set_cookie = self._detect_best_locale(request)
        set_locale(locale)
        response = await call_next(request)
        if set_cookie:
            response.set_cookie("locale", locale, max_age=30 * 24 * 3600)
        return response
