from abc import abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, TypeVar

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from typing_extensions import Never

from fastapi_views.exceptions import Forbidden, Unauthorized

from .scopes import (
    All,
    Edit,
    HierarchicalScopeValidator,
    Read,
    Scope,
    ScopeValidator,
)

__all__ = [
    "All",
    "AuthBase",
    "AuthorizationScheme",
    "Edit",
    "Read",
    "Scope",
    "ScopesAuth",
    "TokenAuth",
]

T = TypeVar("T")

AuthorizationScheme = Callable[..., str | None | Awaitable[str | None]]


def http_bearer() -> AuthorizationScheme:
    scheme = HTTPBearer(auto_error=False)

    async def http_bearer(
        bearer: HTTPAuthorizationCredentials | None = Depends(scheme),
    ) -> str | None:
        return bearer.credentials if bearer else None

    return http_bearer


class AuthBase:
    def __init__(self, scheme: AuthorizationScheme) -> None:
        self.scheme = scheme
        self.dependency = self.get_dependency()

    def authenticated(self) -> Any:
        return Security(self.dependency)

    def unauthorized(self) -> Never:
        raise Unauthorized("")

    def get_dependency(self) -> Any:
        async def _dependency(
            raw: Annotated[str | None, Depends(self.scheme)],
        ) -> Any:
            if raw is None:
                self.unauthorized()
            return raw

        return _dependency


class TokenAuth(AuthBase):
    def __init__(self, scheme: AuthorizationScheme | None = None) -> None:
        if scheme is None:
            scheme = http_bearer()
        super().__init__(scheme)


class ScopesAuth(TokenAuth):
    def __init__(
        self,
        scheme: AuthorizationScheme | None = None,
        scope_validator: ScopeValidator | None = None,
    ) -> None:
        self.scope_validator = scope_validator or HierarchicalScopeValidator()
        super().__init__(scheme)

    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        return self.scope_validator.has_scope(scope, granted_scopes)

    def validate_scopes(self, token: dict[str, Any], scopes: SecurityScopes) -> None:
        granted = token.get("scope", "").split(" ")
        for scope in scopes.scopes:
            if not self.has_scope(scope, granted):
                raise Forbidden(detail=f"Token is missing required scope: {scope}")

    @abstractmethod
    async def verify(self, raw: str) -> dict[str, Any]:
        raise NotImplementedError

    def get_dependency(self) -> Any:

        async def dependency(
            scopes: SecurityScopes,
            raw: Annotated[str | None, Depends(self.scheme)],
        ) -> Any:
            if raw is None:
                self.unauthorized()
            token = await self.verify(raw)
            self.validate_scopes(token, scopes)

            return token

        return dependency

    def requires(self, *scopes: Scope) -> Any:
        return Security(self.dependency, scopes=scopes)
