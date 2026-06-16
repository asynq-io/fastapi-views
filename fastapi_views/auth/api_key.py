import secrets
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import APIKeyHeader
from typing_extensions import Never

from fastapi_views.exceptions import Unauthorized

from .abc import Auth


class APIKeyAuth(Auth[str]):
    def __init__(
        self,
        name: str = "X-Api-Key",
        scheme_name: str | None = None,
        description: str | None = None,
    ) -> None:
        authorization_scheme = APIKeyHeader(
            name=name,
            scheme_name=scheme_name,
            description=description,
            auto_error=False,
        )
        super().__init__(scheme=authorization_scheme)

    def unauthorized(self) -> Never:
        raise Unauthorized(
            "Invalid API Key",
            headers={"WWW-Authenticate": "APIKey"},
        )


class ConstAPIKeyAuth(APIKeyAuth):
    def __init__(
        self,
        api_key: str,
        name: str = "X-Api-Key",
        scheme_name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name, scheme_name, description)
        self.api_key = api_key

    def get_dependency(self) -> Any:
        async def _dependency(
            raw: Annotated[str | None, Depends(self.scheme)],
        ) -> Any:
            if raw is None:
                self.unauthorized()
            if not secrets.compare_digest(raw, self.api_key):
                self.unauthorized()
            return raw

        return _dependency
