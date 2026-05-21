from collections.abc import Callable, Sequence
from functools import cached_property
from typing import Annotated, Any, ClassVar

from fastapi import Depends, Security
from fastapi.security import SecurityScopes
from pydantic import StringConstraints

from fastapi_views.exceptions import Forbidden, Unauthorized
from fastapi_views.views.functools import errors

from .auth import JWTAuth
from .jwt import BaseJsonWebToken
from .types import RouterType

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


Read = "read"
Edit = "edit"
All = "*"


class ScopesJsonWebToken(BaseJsonWebToken):
    scope: str = ""

    @cached_property
    def scopes(self) -> list[Scope]:
        if not self.scope:
            return []
        return self.scope.split(" ")


class OAuth2JWTAuth(JWTAuth[ScopesJsonWebToken]):
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

    def get_dependency(self) -> Any:
        async def _dependency(
            security_scopes: SecurityScopes,
            raw_token: Annotated[str | None, Depends(self.authorization_scheme)],
        ) -> ScopesJsonWebToken:
            token = await self.validate_token(raw_token)
            for scope in security_scopes.scopes:
                if not self.has_scope(scope, token.scopes):
                    raise Forbidden(
                        title="insufficient_scopes",
                        detail=f"Token is missing required scope: {scope}",
                    )
            return token

        return _dependency

    def requires(self, *scopes: Scope) -> Any:
        return Security(self._dependency, scopes=scopes)

    def protected_router(
        self, router_cls: Callable[..., RouterType], *scopes: Scope, **kwargs: Any
    ) -> RouterType:
        if not scopes:
            return super().protected_router(router_cls, **kwargs)
        dependencies = kwargs.pop("dependencies", [])
        dependencies.append(self.requires(*scopes))
        responses = kwargs.pop("responess", {})
        responses.update(errors(Unauthorized, Forbidden))
        return router_cls(dependencies=dependencies, responses=responses, **kwargs)
