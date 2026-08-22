from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable, Generator, Sequence
from contextlib import contextmanager
from typing import Any, ClassVar, TypeVar

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from typing_extensions import Never

from fastapi_views.exceptions import APIError, Forbidden, Unauthorized
from fastapi_views.permissions.abc import (
    AUTH_CHALLENGE_SCOPE_KEY,
    AUTH_ERROR_SCOPE_KEY,
)

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
    """A scheme that extracts a credential and turns it into a principal.

    ``get_dependency`` is the raising FastAPI dependency used by
    ``authenticated()`` / ``requires()`` (401 on a missing/invalid credential,
    scope validation for :class:`ScopesAuth`). ``get_resolve_dependency`` is the
    non-raising one the permission bridge wires so that authorization — not
    resolution — decides 401 vs 403. Both publish the principal on
    ``request.scope["principal"]``.
    """

    #: ``WWW-Authenticate`` scheme advertised on every ``401``; ``None`` for an
    #: auth that has no challenge to offer.
    challenge: ClassVar[str | None] = None

    def __init__(self, scheme: AuthorizationScheme) -> None:
        self.scheme = scheme
        self.dependency = self.get_dependency()
        self.resolve_dependency = self.get_resolve_dependency()
        self._test_user: Any = None

    def authenticated(self) -> Any:
        return Security(self.dependency)

    def challenge_headers(self) -> dict[str, str]:
        """``WWW-Authenticate`` headers advertising this scheme, if it has one."""
        if self.challenge is None:
            return {}
        return {"WWW-Authenticate": self.challenge}

    def unauthorized(self) -> Never:
        raise Unauthorized("Missing or invalid credentials")

    def wrap_token(self, token: Any) -> Any:
        """Turn a verified credential into the principal handed to the endpoint."""
        return token

    async def _resolve_principal(self, raw: Any) -> Any:
        """Verify (when applicable) and wrap a credential into the principal.

        Returns ``None`` when the credential is rejected without raising.
        """
        return self.wrap_token(raw)

    def _publish_principal(
        self,
        request: Request,
        principal: Any,
        error: APIError | None = None,
    ) -> Any:
        """Publish ``principal`` on the request scope and hand it back.

        The scheme's challenge travels with it, plus the ``APIError`` a rejected
        credential raised, so whichever site raises the ``401`` later can state
        the real reason instead of a generic "authentication required".
        """
        request.scope["principal"] = principal
        request.scope[AUTH_CHALLENGE_SCOPE_KEY] = self.challenge_headers()
        request.scope[AUTH_ERROR_SCOPE_KEY] = error
        return principal

    def get_dependency(self) -> Any:
        async def _dependency(
            request: Request,
            raw: str | None = Depends(self.scheme),
        ) -> Any:
            if self._test_user is not None:
                return self._publish_principal(request, self._test_user)
            if raw is None:
                self.unauthorized()
            principal = await self._resolve_principal(raw)
            if principal is None:
                self.unauthorized()
            return self._publish_principal(request, principal)

        return _dependency

    def get_resolve_dependency(self) -> Any:
        """Non-raising dependency: resolve the principal (or ``None``) and publish it."""

        async def _resolve(
            request: Request,
            raw: str | None = Depends(self.scheme),
        ) -> Any:
            if self._test_user is not None:
                return self._publish_principal(request, self._test_user)
            if raw is None:
                return self._publish_principal(request, None)
            try:
                principal = await self._resolve_principal(raw)
            except APIError as exc:
                return self._publish_principal(request, None, exc)
            return self._publish_principal(request, principal)

        return _resolve

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
            headers=self.challenge_headers(),
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

    async def _resolve_principal(self, raw: Any) -> Any:
        token = await self.verify(raw)
        return self.wrap_token(token)

    def get_dependency(self) -> Any:
        async def dependency(
            request: Request,
            scopes: SecurityScopes,
            raw: str | None = Depends(self.scheme),
        ) -> Any:
            if self._test_user is not None:
                return self._publish_principal(request, self._test_user)
            if raw is None:
                self.unauthorized()
            token = await self.verify(raw)
            self.validate_scopes(token, scopes)
            return self._publish_principal(request, self.wrap_token(token))

        return dependency

    def requires(self, *scopes: Scope) -> Any:
        return Security(self.dependency, scopes=scopes)
