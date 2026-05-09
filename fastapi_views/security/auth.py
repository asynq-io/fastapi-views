from typing import Annotated, Any, TypedDict

from fastapi import Depends, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from pydantic import BaseModel
from typing_extensions import NotRequired, Unpack

from fastapi_views.exceptions import Forbidden, Unauthorized

from .scopes import Scope, ScopeValidator, SimpleScopeValidator
from .user import User
from .validators import TokenValidator


class SchemeOptions(TypedDict):
    tokenUrl: str
    scheme_name: NotRequired[str | None]
    scopes: NotRequired[dict[str, str] | None]
    description: NotRequired[str | None]
    refreshUrl: NotRequired[str | None]


class Auth:
    """Central authentication helper for JWT-protected FastAPI routes.

    ``Auth`` wires together a :class:`~fastapi_views.security.validators.TokenValidator`,
    a :class:`~fastapi_views.security.scopes.ScopeValidator`, and an OAuth2 bearer
    scheme into reusable FastAPI ``Security`` dependencies.

    Use :meth:`authenticated` to require a valid token with no scope checks, or
    :meth:`requires` to additionally enforce one or more scopes.

    :param token_validator: Validates raw bearer tokens and returns decoded claims.
    :type token_validator: TokenValidator
    :param scope_validator: Strategy used to check whether token scopes satisfy route
        requirements.  Defaults to :class:`~fastapi_views.security.scopes.SimpleScopeValidator`.
    :type scope_validator: ScopeValidator
    :param user_model: Pydantic model validated from the token claims and injected into
        route handlers.  Defaults to :class:`~fastapi_views.security.user.User`.
    :type user_model: type[BaseModel]
    :param scheme_options: Extra keyword arguments forwarded to
        :class:`fastapi.security.OAuth2PasswordBearer` (e.g. ``tokenUrl``).

    :Example:

    .. code-block:: python

        from fastapi import FastAPI
        from fastapi_views import ViewRouter
        from fastapi_views.security import Auth
        from fastapi_views.security.validators.joserfc import JoserfcTokenValidator
        from joserfc import jwk

        key = jwk.OctKey.import_key({"kty": "oct", "k": "<base64url-secret>"})
        validator = JoserfcTokenValidator(key=key)
        auth = Auth(validator, tokenUrl="/token")

        app = FastAPI()

        @app.get("/me")
        async def me(user: Annotated[User, auth.requires()]):
            return {"id": user.id}

        @app.get("/admin")
        async def admin(user: Annotated[User, auth.requires("admin:read")]):
            return {"id": user.id}
    """

    def __init__(
        self,
        token_validator: TokenValidator,
        scope_validator: ScopeValidator = SimpleScopeValidator(),
        user_model: type[BaseModel] = User,
        **scheme_options: Unpack[SchemeOptions],
    ) -> None:
        self.token_validator = token_validator
        self.scope_validator = scope_validator
        self.user_model = user_model
        self.security_scheme = OAuth2PasswordBearer(auto_error=False, **scheme_options)
        self._dependency = self.get_dependency()

    def get_dependency(self) -> Any:
        async def _dependency(
            security_scopes: SecurityScopes,
            raw_token: Annotated[str | None, Depends(self.security_scheme)],
        ) -> BaseModel:
            claims = await self.validate_token(raw_token)
            token_scopes = claims.get("scope", "").split(" ")
            for scope in security_scopes.scopes:
                if not self.scope_validator.has_scope(scope, token_scopes):
                    raise Forbidden(
                        title="insufficient_scopes",
                        detail=f"Token is missing required scope: {scope}",
                    )
            return self.user_model.model_validate(claims)

        return _dependency

    async def validate_token(self, raw_token: str | None) -> dict[str, Any]:
        """Validate *raw_token* and return its decoded claims.

        :param raw_token: Raw bearer token string, or ``None`` if no token was provided.
        :type raw_token: str | None
        :returns: Decoded token claims.
        :rtype: dict[str, Any]
        :raises fastapi_views.exceptions.Unauthorized: If *raw_token* is absent or invalid.
        """
        if not raw_token:
            raise Unauthorized(
                "Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await self.token_validator.validate(raw_token)

    def requires(self, *scopes: Scope) -> Any:
        """Return a ``Security`` dependency that requires a valid token and specific scopes.

        When *scopes* are provided, each scope is checked against the token's ``scope``
        claim using the configured :attr:`scope_validator`.  A missing scope raises
        ``403 Forbidden``.

        :param scopes: One or more scope strings the token must satisfy
            (e.g. ``"items:read"``, ``"orders:edit"``).
        :type scopes: Scope
        :returns: A FastAPI ``Security`` dependency resolving to an instance of
            ``user_model``.
        :raises fastapi_views.exceptions.Unauthorized: If the token is absent or invalid.
        :raises fastapi_views.exceptions.Forbidden: If the token lacks a required scope.
        """

        return Security(self._dependency, scopes=scopes)

    def authenticated(self) -> Any:
        """Return a ``Security`` dependency that requires a valid token with no scope checks.

        :returns: A FastAPI ``Security`` dependency resolving to an instance of
            ``user_model``.
        """
        return Security(self._dependency)
