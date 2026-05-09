from typing import Any

from auth0_api_python.api_client import ApiClient, BaseAuthError

from fastapi_views.exceptions import APIError

from .abc import TokenValidator


class Auth0TokenValidator(TokenValidator):
    """Token validator backed by the Auth0 Python SDK.

    Delegates token verification to an ``auth0_api_python`` :class:`ApiClient`, which
    calls the Auth0 ``/userinfo`` endpoint (or performs local RS256 verification,
    depending on how the client is configured). Auth0-specific errors are translated to
    :class:`~fastapi_views.exceptions.APIError` responses so that callers receive
    well-formed RFC 9457 problem-details responses.

    :param api_client: A configured ``auth0_api_python.ApiClient`` instance.
    :type api_client: auth0_api_python.api_client.ApiClient

    :Example:

    .. code-block:: python

        from auth0_api_python.api_client import ApiClient
        from fastapi_views.security.validators.auth0 import Auth0TokenValidator

        api_client = ApiClient(
            domain="your-tenant.auth0.com",
            audience="https://api.example.com",
        )
        validator = Auth0TokenValidator(api_client=api_client)
    """

    def __init__(self, api_client: ApiClient) -> None:
        self.api_client = api_client

    async def validate(self, token: str) -> dict[str, Any]:
        """Verify *token* with Auth0 and return its decoded claims.

        :param token: Raw bearer token string.
        :type token: str
        :returns: Decoded JWT claims as returned by the Auth0 SDK.
        :rtype: dict[str, Any]
        :raises fastapi_views.exceptions.APIError: Wraps any ``BaseAuthError`` raised by
            the Auth0 SDK, preserving the original status code and error description.
        """
        try:
            return await self.api_client.verify_access_token(token)
        except BaseAuthError as e:
            raise APIError(
                title=e.get_error_code(),
                detail=e.get_error_description(),
                status=e.get_status_code(),
                headers=e.get_headers(),
            ) from None
