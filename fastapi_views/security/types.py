from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import APIRouter

from .jwt import BaseJsonWebToken

JsonWebTokenT = TypeVar("JsonWebTokenT", bound=BaseJsonWebToken)

RouterType = TypeVar("RouterType", bound=APIRouter)

AuthorizationScheme = Callable[..., str | None | Awaitable[str | None]]
