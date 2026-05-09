from typing import Any

from joserfc import jwk, jwt
from joserfc.errors import JoseError

from fastapi_views.exceptions import Unauthorized

from .abc import TokenValidator


class JoserfcTokenValidator(TokenValidator):
    """Token validator backed by the `joserfc <https://joserfc.readthedocs.io>`_ library.

    Decodes and verifies JWTs (including JWS/JWE) using a ``joserfc`` key or key set.
    Standard claim validation (``exp``, ``nbf``, ``iss``, ``aud``, …) is delegated to a
    :class:`joserfc.jwt.JWTClaimsRegistry`.

    The key can be supplied at construction time or deferred and set later via
    :meth:`init_key` — useful when the JWKS must be fetched asynchronously on startup.

    :param key: A ``joserfc`` key or key-set used for verification.  May be ``None`` if
        the key will be provided later via :meth:`init_key`.
    :type key: jwk.KeyFlexible | None
    :param claims_registry: Custom claims registry for claim validation.  Defaults to
        :class:`joserfc.jwt.JWTClaimsRegistry` with no additional constraints.
    :type claims_registry: jwt.BaseClaimsRegistry | None
    :param options: Extra keyword arguments forwarded verbatim to :func:`joserfc.jwt.decode`.

    :Example:

    .. code-block:: python

        from joserfc import jwk
        from fastapi_views.security.validators.joserfc import JoserfcTokenValidator

        # HS256 shared-secret validator
        key = jwk.OctKey.import_key({"kty": "oct", "k": "<base64url-secret>"})
        validator = JoserfcTokenValidator(key=key)

        # RS256 with a JWKS fetched at startup
        validator = JoserfcTokenValidator()
        # … later, e.g. in a lifespan handler:
        jwks = jwk.KeySet.import_key_set(await fetch_jwks())
        validator.init_key(jwks)
    """

    def __init__(
        self,
        key: jwk.KeyFlexible | None = None,
        claims_registry: jwt.BaseClaimsRegistry | None = None,
        **options: Any,
    ) -> None:
        self._key = key
        self.claims_registry = claims_registry or jwt.JWTClaimsRegistry()
        self.options = options

    def init_key(self, key: jwk.KeyFlexible) -> None:
        """Set (or replace) the verification key.

        :param key: A ``joserfc`` key or key-set.
        :type key: jwk.KeyFlexible
        """
        self._key = key

    @property
    def key(self) -> jwk.KeyFlexible:
        if self._key is None:
            raise ValueError("key not initialized")
        return self._key

    async def validate(self, token: str) -> dict[str, Any]:
        """Decode and validate *token*, returning its claims.

        :param token: Raw bearer token string.
        :type token: str
        :returns: Decoded JWT claims.
        :rtype: dict[str, Any]
        :raises fastapi_views.exceptions.Unauthorized: If the token is invalid, expired,
            or fails claims validation.
        """
        try:
            token_obj = jwt.decode(token, self.key, **self.options)
            self.claims_registry.validate(token_obj.claims)
        except JoseError as e:
            raise Unauthorized(e.description, title=e.error) from None
        return token_obj.claims
