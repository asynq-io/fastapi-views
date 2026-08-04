from collections.abc import Sequence
from typing import Any, Literal

from auth0_api_python.api_client import ApiClient, BaseAuthError

from fastapi_views.auth.abc import AuthorizationScheme, ScopesAuth, TokenWrapper
from fastapi_views.auth.scopes import Scope, ScopeValidator
from fastapi_views.exceptions import APIError


class Auth0(ScopesAuth):
    def __init__(
        self,
        api_client: ApiClient,
        scheme: AuthorizationScheme | None = None,
        scope_validator: ScopeValidator | None = None,
        custom_class: TokenWrapper | None = None,
        permission_key: Literal["permissions", "scope"] = "permissions",
    ) -> None:
        super().__init__(scheme, scope_validator, custom_class)
        self.api_client = api_client
        self.permission_key = permission_key

    def get_granted_scopes(self, token: dict[str, Any]) -> Sequence[Scope]:
        scope = token.get(self.permission_key, "")
        if not scope:
            return []
        if isinstance(scope, str):
            return scope.split(" ")
        return scope

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


# user: Annotated[User, auth.requires()] ???
