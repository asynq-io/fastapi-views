import secrets
from typing import Any, ClassVar

from fastapi.security import APIKeyHeader
from typing_extensions import Never

from fastapi_views.exceptions import Unauthorized

from .abc import AuthBase


class APIKeyAuth(AuthBase):
    challenge: ClassVar[str] = "APIKey"

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
            headers={"WWW-Authenticate": self.challenge},
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

    async def _resolve_principal(self, raw: Any) -> Any:
        if not secrets.compare_digest(str(raw), self.api_key):
            return None
        return self.wrap_token(raw)
