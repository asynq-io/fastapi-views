from typing import Any

from auth0_api_python.api_client import ApiClient, BaseAuthError

from fastapi_views.exceptions import APIError

from .abc import AuthorizationScheme, ScopesAuth
from .scopes import ScopeValidator


class Auth0(ScopesAuth):
    def __init__(
        self,
        api_client: ApiClient,
        scheme: AuthorizationScheme | None = None,
        scope_validator: ScopeValidator | None = None,
    ) -> None:
        self.api_client = api_client
        super().__init__(scheme, scope_validator)

    async def verify(self, raw: str) -> dict[str, Any]:
        try:
            return await self.api_client.verify_access_token(raw)
        except BaseAuthError as e:
            raise APIError(
                title=e.get_error_code(),
                detail=e.get_error_description(),
                status=e.get_status_code(),
                headers=e.get_headers(),
            ) from None
