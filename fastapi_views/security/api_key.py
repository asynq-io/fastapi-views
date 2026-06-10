import functools
from secrets import compare_digest
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import APIKeyHeader

from fastapi_views.exceptions import Unauthorized


def _unauthorized(detail: str = "Invalid API key") -> Unauthorized:
    return Unauthorized(
        detail,
        headers={"WWW-Authenticate": "APIKey"},
    )


@functools.cache
def require_api_key(
    api_key: str,
    *,
    name: str = "X-Api-Key",
    scheme_name: str | None = None,
    description: str | None = None,
) -> Any:
    security_scheme = APIKeyHeader(
        name=name, scheme_name=scheme_name, description=description, auto_error=False
    )

    async def _dependency(key: Annotated[str | None, Depends(security_scheme)]) -> None:
        if not key:
            raise _unauthorized("X-Api-Key header is missing")

        if not compare_digest(api_key, key):
            raise _unauthorized("Invalid X-Api-Key provided")

    return _dependency
