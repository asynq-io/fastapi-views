from typing import Any

from auth0_api_python.api_client import ApiClient, BaseAuthError
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from fastapi_views.exceptions import APIError, Unauthorized

from .validator import JsonWebTokenT, TokenValidator


class Auth0TokenValidator(TokenValidator[JsonWebTokenT]):
    def __init__(
        self,
        token_model: type[JsonWebTokenT],
        api_client: ApiClient,
        **options: Any,
    ) -> None:
        super().__init__(token_model, **options)
        self.api_client = api_client

    async def validate(self, token: str) -> JsonWebTokenT:
        try:
            verified_claims = await self.api_client.verify_access_token(token)
            return self.token_model.model_validate(verified_claims, **self.options)
        except ValidationError as e:
            raise Unauthorized(
                "Invalid token", errors=jsonable_encoder(e.errors())
            ) from None
        except BaseAuthError as e:
            raise APIError(
                title=e.get_error_code(),
                detail=e.get_error_description(),
                status=e.get_status_code(),
                headers=e.get_headers(),
            ) from None
