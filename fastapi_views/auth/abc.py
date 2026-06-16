from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, ClassVar, Generic, TypeVar

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from pydantic import StringConstraints
from typing_extensions import Never

from fastapi_views.exceptions import Forbidden, Unauthorized

Read = "read"
Edit = "edit"
All = "*"

Scope = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=255,
        to_lower=True,
        strip_whitespace=True,
        pattern=r"^[a-z]+:(\*|[a-z]+)$",
    ),
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


class Auth(ABC, Generic[T]):
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


class TokenAuth(Auth[dict[str, Any]]):
    def __init__(self, scheme: AuthorizationScheme | None = None) -> None:
        if scheme is None:
            scheme = http_bearer()
        super().__init__(scheme)


class ScopesAuth(TokenAuth):
    scope_hierarhy: ClassVar[dict[str, set[str]]] = {
        Read: set(),
        Edit: {Read},
        All: {Read, Edit},
    }

    def _resolve_action(self, action: str) -> set[str]:
        return self.scope_hierarhy.get(action, set()) | {action}

    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        required_resource, _, required_action = scope.partition(":")
        for s in granted_scopes:
            granted_resource, _, granted_action = s.partition(":")
            if granted_resource not in (required_resource, All):
                continue
            if granted_action == All or required_action in self._resolve_action(
                granted_action
            ):
                return True
        return False

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
