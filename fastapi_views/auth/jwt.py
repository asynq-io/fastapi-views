import calendar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from json import JSONDecoder, JSONEncoder
from typing import Any, Literal

from joserfc import jwk, jwt
from joserfc.errors import JoseError
from joserfc.jwe import JWERegistry
from joserfc.jwk import KeyBase
from joserfc.jws import JWSRegistry
from joserfc.jwt import BaseClaimsRegistry

from fastapi_views.exceptions import Unauthorized
from fastapi_views.models import BaseSchema

from .abc import AuthorizationScheme, ScopesAuth
from .scopes import ScopeValidator

try:
    from httpx import AsyncClient
except ImportError:
    AsyncClient = None  # type: ignore[assignment, misc, unused-ignore]


class BearerAccessToken(BaseSchema):
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    access_token: str
    expires_in: int | None = None


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def utc_timestamp() -> int:
    return calendar.timegm(_utc_now().utctimetuple())


def _get_default_registry() -> jwt.JWTClaimsRegistry:
    return jwt.JWTClaimsRegistry(now=utc_timestamp, leeway=10)


@dataclass
class JWTConfig:
    key: KeyBase | None = None
    key_type: Literal["oct", "RSA", "EC", "OKP"] | None = None
    issuer_url: str = ""
    header: dict[str, Any] = field(default_factory=dict)
    algorithms: list[str] | None = None
    claims_registry: BaseClaimsRegistry = field(default_factory=_get_default_registry)
    encoder_cls: type[JSONEncoder] | None = None
    decoder_cls: type[JSONDecoder] | None = None
    registry: JWSRegistry | JWERegistry | None = None
    default_type: str | None = None
    expiration_seconds: int | None = None

    def get_key(self) -> KeyBase:
        if self.key is None:
            raise ValueError("Key not initialized")
        return self.key

    def __post_init__(self) -> None:
        if self.algorithms and len(self.algorithms) == 1 and "alg" not in self.header:
            self.header["alg"] = self.algorithms[0]
        if self.issuer_url:
            self.claims_registry.options["iss"] = {
                "essential": True,
                "value": self.issuer_url,
            }

    def import_key(
        self, data: Any, parameters: jwk.KeyParameters | None = None
    ) -> None:
        if "keys" in data:
            self.key = jwk.KeySet.import_key_set(data, parameters)
        else:
            self.key = jwk.import_key(data, self.key_type, parameters)


class JWTAuth(ScopesAuth):
    def __init__(
        self,
        config: JWTConfig,
        scheme: AuthorizationScheme | None = None,
        scope_validator: ScopeValidator | None = None,
    ) -> None:
        self.config = config
        super().__init__(scheme, scope_validator)

    @cached_property
    def jwks(self) -> jwk.KeySetSerialization:
        key = self.config.get_key()
        if isinstance(key, jwk.KeySet):
            return key.as_dict(private=False)
        return {"keys": [key.as_dict(private=False)]}

    async def fetch_jwks(self, url: str, **kwargs: Any) -> None:
        if AsyncClient is None:
            raise ImportError("httpx is not installed")

        async with AsyncClient(base_url=self.config.issuer_url) as client:
            response = await client.get(url, **kwargs)
        response.raise_for_status()
        data = response.json()
        self.config.import_key(data)

    async def verify(self, raw: str) -> dict[str, Any]:
        try:
            decoded = jwt.decode(
                raw,
                key=self.config.get_key(),
                algorithms=self.config.algorithms,
                registry=self.config.registry,
                decoder_cls=self.config.decoder_cls,
            )
            claims = decoded.claims
            self.config.claims_registry.validate(claims)
            return claims  # noqa: TRY300
        except JoseError as e:
            raise Unauthorized(str(e)) from None

    def encode(self, payload: dict[str, Any], expires_in: int | None = None) -> str:
        claims = payload.copy()
        claims.setdefault("iat", utc_timestamp())
        if self.config.issuer_url:
            claims.setdefault("iss", self.config.issuer_url)
        if expires_in is None:
            expires_in = self.config.expiration_seconds
        if expires_in is not None:
            claims.setdefault("exp", claims["iat"] + expires_in)
        return jwt.encode(
            header=self.config.header,
            claims=claims,
            key=self.config.get_key(),
            algorithms=self.config.algorithms,
            encoder_cls=self.config.encoder_cls,
            default_type=self.config.default_type,
        )

    def create_access_token(
        self, payload: dict[str, Any], expires_in: int | None = None
    ) -> BearerAccessToken:
        token = self.encode(payload, expires_in=expires_in)
        return BearerAccessToken(access_token=token, expires_in=expires_in)
