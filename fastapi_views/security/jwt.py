import calendar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from json import JSONDecoder, JSONEncoder
from typing import Any, ClassVar, Literal

from joserfc import jwk, jwt
from joserfc.jwe import JWERegistry
from joserfc.jwk import KeyBase
from joserfc.jws import JWSRegistry
from pydantic import Field, PrivateAttr, computed_field, model_validator
from typing_extensions import Self

from fastapi_views.models import BaseSchema

try:
    from httpx import AsyncClient
except ImportError:
    AsyncClient = None  # type: ignore[assignment, misc, unused-ignore]


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
    claims_registry: jwt.BaseClaimsRegistry = field(
        default_factory=_get_default_registry
    )
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

    @property
    def jwks(self) -> jwk.KeySetSerialization:
        key = self.get_key()
        if isinstance(key, jwk.KeySet):
            return key.as_dict(private=False)
        return {"keys": [key.as_dict(private=False)]}

    async def fetch_jwks(self, url: str, **kwargs: Any) -> None:
        if AsyncClient is None:
            raise ImportError("httpx is not installed")

        async with AsyncClient(base_url=self.issuer_url) as client:
            response = await client.get(url, **kwargs)
            response.raise_for_status()
        data = response.json()

        if "keys" in data:
            self.key = jwk.KeySet.import_key_set(data)
        else:
            self.key = jwk.import_key(data, self.key_type)

    def import_key(
        self, data: Any, parameters: jwk.KeyParameters | None = None
    ) -> None:
        self.key = jwk.import_key(data, self.key_type, parameters=parameters)


class BearerAccessToken(BaseSchema):
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    access_token: str
    expires_in: int | None = None


class BaseJsonWebToken(BaseSchema):
    jwt_config: ClassVar[JWTConfig]

    _raw: dict[str, Any] | None = PrivateAttr(None)

    iss: str | None = None
    sub: str
    iat: int = Field(default_factory=utc_timestamp)

    @classmethod
    def configure(cls, jwt_config: JWTConfig) -> None:
        cls.jwt_config = jwt_config

    @computed_field
    def exp(self) -> int | None:
        if td := self.jwt_config.expiration_seconds:
            return self.iat + td
        return None

    @property
    def raw(self) -> dict[str, Any]:
        if self._raw is None:
            raise ValueError("raw is only accessible for decoded tokens")
        return self._raw

    @classmethod
    def decode(cls, payload: str | bytes, **options: Any) -> Self:
        decoded = jwt.decode(
            payload,
            key=cls.jwt_config.get_key(),
            algorithms=cls.jwt_config.algorithms,
            registry=cls.jwt_config.registry,
            decoder_cls=cls.jwt_config.decoder_cls,
        )
        cls.jwt_config.claims_registry.validate(decoded.claims)
        self = cls.model_validate(decoded.claims, **options)
        self._raw = decoded.claims
        return self

    def encode(
        self,
        *,
        header: dict[str, Any] | None = None,
        by_alias: bool = True,
        exclude_none: bool = True,
        **options: Any,
    ) -> str:
        claims = self.model_dump(
            by_alias=by_alias, exclude_none=exclude_none, **options
        )
        header = self.jwt_config.header | (header or {})
        return jwt.encode(
            header=header,
            claims=claims,
            key=self.jwt_config.get_key(),
            algorithms=self.jwt_config.algorithms,
            encoder_cls=self.jwt_config.encoder_cls,
            default_type=self.jwt_config.default_type,
        )

    def encode_as_bearer(
        self, *, header: dict[str, Any] | None = None, **options: Any
    ) -> BearerAccessToken:
        token = self.encode(header=header, **options)
        return BearerAccessToken(
            access_token=token, expires_in=self.jwt_config.expiration_seconds
        )

    @model_validator(mode="after")
    def set_defaults(self) -> Self:
        if not self.iss and self.jwt_config.issuer_url:
            self.iss = self.jwt_config.issuer_url
        return self
