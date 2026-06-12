from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cache
from typing import Any

import orjson
from pydantic import BaseModel, TypeAdapter


def _orjson_default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    return obj


@cache
def _type_adapter(type_: Any) -> TypeAdapter[Any]:
    return TypeAdapter(type_)


class Serializer(ABC):
    """Converts values to/from the ``bytes`` understood by byte-oriented
    backends (e.g. Redis). Subclass to plug in a custom codec."""

    @abstractmethod
    def encode(self, value: Any) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def decode(self, data: bytes | str, type_: Any = None) -> Any:
        raise NotImplementedError


class DefaultSerializer(Serializer):
    """The batteries-included codec.

    - ``bytes``/``str`` are stored verbatim — no JSON round-trip.
    - Pydantic models go straight through their own (fast) JSON serializer.
    - When ``type_`` is given, values are validated through a cached
      :class:`~pydantic.TypeAdapter` (works for models, dataclasses,
      ``list[Model]``, ``TypedDict``, primitives, ...).
    - Anything else falls back to ``orjson``.
    """

    def encode(self, value: Any) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return orjson.dumps(value, default=_orjson_default)

    def decode(self, data: bytes | str, type_: Any = None) -> Any:
        # Raw passthrough — the value was stored verbatim, no JSON involved.
        if type_ is bytes:
            return data.encode() if isinstance(data, str) else data
        if type_ is str:
            return data.decode() if isinstance(data, bytes) else data
        # Known type (model, dataclass, list[Model], primitive, ...): let
        # pydantic validate straight from the JSON bytes in a single pass.
        if type_ is not None:
            return _type_adapter(type_).validate_json(data)
        # Untyped: best-effort JSON, falling back to the raw value when it
        # was a plain string/bytes stored verbatim (i.e. not valid JSON).
        try:
            return orjson.loads(data)
        except orjson.JSONDecodeError:
            return data
