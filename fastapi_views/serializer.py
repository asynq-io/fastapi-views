from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pydantic import TypeAdapter


def serialize(
    adapter: TypeAdapter,
    obj: Any,
    *,
    validate: bool = True,
    from_attributes: bool | Literal["auto"] = True,
    **options: Any,
) -> bytes:
    if validate:
        if from_attributes == "auto":
            from_attributes = not isinstance(obj, Mapping) or (
                isinstance(obj, Sequence) and all(isinstance(el, Mapping) for el in obj)
            )
        obj = adapter.validate_python(obj, from_attributes=from_attributes)
    return adapter.dump_json(obj, **options)
