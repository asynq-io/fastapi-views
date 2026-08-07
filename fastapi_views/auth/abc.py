from abc import abstractmethod
from collections.abc import Awaitable, Callable, Generator, Sequence
from contextlib import contextmanager
from typing import Annotated, Any, ClassVar, TypeVar

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from typing_extensions import Never

from fastapi_views.exceptions import Forbidden, Unauthorized

from .scopes import (
    All,
    Delete,
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
    "Delete",
    "Edit",
    "Read",
    "Scope",
    "ScopesAuth",
    "TokenAuth",
]

T = TypeVar("T")

AuthorizationScheme = Callable[..., str | Awaitable[str | None] | None]
TokenWrapper = Callable[[Any], Any]


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
        self._test_user: Any = None

    def authenticated(self) -> Any:
        return Security(self.dependency)

    def unauthorized(self) -> Never:
        raise Unauthorized("Missing or invalid credentials")

    def wrap_token(self, token: Any) -> Any:
        """Turn a verified credential into the principal handed to the endpoint."""
        return token

    def get_dependency(self) -> Any:
        async def _dependency(
            raw: Annotated[str | None, Depends(self.scheme)],
        ) -> Any:
            if self._test_user is not None:
                return self._test_user
            if raw is None:
                self.unauthorized()
            return self.wrap_token(raw)

        return _dependency

    @contextmanager
    def with_test_user(self, user: Any) -> Generator[Any, None, None]:
        self._test_user = user
        try:
            yield
        finally:
            self._test_user = None


class TokenAuth(AuthBase):
    challenge: ClassVar[str] = "Bearer"

    def __init__(
        self,
        scheme: AuthorizationScheme | None = None,
        custom_class: TokenWrapper | None = None,
    ) -> None:
        if scheme is None:
            scheme = http_bearer()
        self.custom_class = custom_class
        super().__init__(scheme)

    def unauthorized(self) -> Never:
        raise Unauthorized(
            "Missing or invalid bearer token",
            headers={"WWW-Authenticate": self.challenge},
        )

    def wrap_token(self, token: Any) -> Any:
        """Apply ``custom_class`` to a verified token, when one is configured."""
        if self.custom_class is None:
            return token
        return self.custom_class(token)


class ScopesAuth(TokenAuth):
    def __init__(
        self,
        scheme: AuthorizationScheme | None = None,
        scope_validator: ScopeValidator | None = None,
        custom_class: TokenWrapper | None = None,
    ) -> None:
        super().__init__(scheme, custom_class)
        self.scope_validator = scope_validator or HierarchicalScopeValidator()

    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        return self.scope_validator.has_scope(scope, granted_scopes)

    def get_granted_scopes(self, token: dict[str, Any]) -> Sequence[Scope]:
        """Scopes carried by ``token``, from the space delimited ``scope`` claim."""
        scope = token.get("scope", "")
        if not scope:
            return []
        return scope.split()

    def validate_scopes(self, token: dict[str, Any], scopes: SecurityScopes) -> None:
        granted = self.get_granted_scopes(token)
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
            if self._test_user is not None:
                return self._test_user
            if raw is None:
                self.unauthorized()
            token = await self.verify(raw)
            self.validate_scopes(token, scopes)
            return self.wrap_token(token)

        return dependency

    def requires(self, *scopes: Scope) -> Any:
        return Security(self.dependency, scopes=scopes)
