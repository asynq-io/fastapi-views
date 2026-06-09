from typing import Any

import anyio


class RequestLimitMiddleware:
    """
    A middleware that limits the number of concurrent requests handled by the API.
    """

    def __init__(self, app: Any, limit: float) -> None:
        self.app = app
        self._limiter = anyio.CapacityLimiter(limit)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
        else:
            async with self._limiter:
                await self.app(scope, receive, send)
