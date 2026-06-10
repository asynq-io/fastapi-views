from abc import ABC, abstractmethod
from typing import Any, Generic

from fastapi.encoders import jsonable_encoder
from joserfc.errors import JoseError
from pydantic import ValidationError

from fastapi_views.exceptions import Unauthorized

from .types import JsonWebTokenT


class TokenValidator(ABC, Generic[JsonWebTokenT]):
    def __init__(
        self,
        token_model: type[JsonWebTokenT],
        **options: Any,
    ) -> None:
        self.token_model = token_model
        self.options = options

    @abstractmethod
    async def validate(self, token: str) -> JsonWebTokenT:
        raise NotImplementedError


class JoserfcTokenValidator(TokenValidator[JsonWebTokenT]):
    async def validate(self, token: str) -> JsonWebTokenT:
        try:
            return self.token_model.decode(token, **self.options)
        except ValidationError as e:
            raise Unauthorized(
                "Invalid token", errors=jsonable_encoder(e.errors())
            ) from None
        except JoseError as e:
            raise Unauthorized(e.description or e.error) from None
