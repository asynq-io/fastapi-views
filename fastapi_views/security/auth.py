from collections.abc import Callable
from typing import Annotated, Any, Generic

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fastapi_views.exceptions import Forbidden, Unauthorized
from fastapi_views.views.functools import errors

from .jwt import BearerAccessToken
from .types import AuthorizationScheme, JsonWebTokenT, RouterType
from .validator import TokenValidator


def default_authorization_scheme() -> AuthorizationScheme:
    scheme = HTTPBearer(auto_error=False)

    async def http_bearer(
        bearer: HTTPAuthorizationCredentials | None = Depends(scheme),
    ) -> str | None:
        if not bearer:
            return None
        return bearer.credentials

    return http_bearer


class JWTAuth(Generic[JsonWebTokenT]):
    def __init__(
        self,
        token_validator: TokenValidator[JsonWebTokenT],
        authorization_scheme: AuthorizationScheme = default_authorization_scheme(),
    ) -> None:
        self.token_validator = token_validator
        self.authorization_scheme = authorization_scheme
        self._dependency = self.get_dependency()

    def get_jwks(self) -> Any:
        return self.token_validator.token_model.jwt_config.jwks

    def create_access_token(self, **payload: Any) -> BearerAccessToken:
        return self.token_validator.token_model(**payload).encode_as_bearer()

    def get_dependency(self) -> Any:
        async def _dependency(
            raw_token: Annotated[str | None, Depends(self.authorization_scheme)],
        ) -> JsonWebTokenT:
            return await self.validate_token(raw_token)

        return _dependency

    async def validate_token(self, raw_token: str | None) -> JsonWebTokenT:
        if raw_token is None:
            raise Unauthorized(
                "Not authenticated",
            )
        return await self.token_validator.validate(raw_token)

    def authenticated(self) -> Any:
        return Security(self._dependency)

    def protected_router(
        self, router_cls: Callable[..., RouterType], **kwargs: Any
    ) -> RouterType:
        dependencies = kwargs.pop("dependencies", [])
        dependencies.append(self.authenticated())
        responses = kwargs.pop("responess", {})
        responses.update(errors(Unauthorized, Forbidden))
        return router_cls(dependencies=dependencies, responses=responses, **kwargs)
