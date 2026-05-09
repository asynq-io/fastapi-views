from abc import ABC, abstractmethod
from typing import Any


class TokenValidator(ABC):
    """Abstract base class for JWT token validators.

    Subclass this to integrate any token validation backend. The :meth:`validate`
    method receives a raw bearer token string and must return the decoded claims dict
    on success, or raise an :class:`~fastapi_views.exceptions.APIError` on failure.

    :Example:

    .. code-block:: python

        from typing import Any
        from fastapi_views.security.validators import TokenValidator
        from fastapi_views.exceptions import Unauthorized

        class MyTokenValidator(TokenValidator):
            async def validate(self, token: str) -> dict[str, Any]:
                claims = my_decode(token)
                if claims is None:
                    raise Unauthorized("Invalid token")
                return claims
    """

    @abstractmethod
    async def validate(self, token: str) -> dict[str, Any]:
        """Validate *token* and return its decoded claims.

        :param token: Raw bearer token string extracted from the ``Authorization`` header.
        :type token: str
        :returns: Decoded JWT claims as a plain dictionary.
        :rtype: dict[str, Any]
        :raises fastapi_views.exceptions.APIError: If the token is invalid or expired.
        """
        raise NotImplementedError
