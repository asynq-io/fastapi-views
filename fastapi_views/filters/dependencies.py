from __future__ import annotations

from typing import Any, TypeVar

from fastapi import Depends
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from pydantic.config import ConfigDict

from .models import BaseFilter

FilterT = TypeVar("FilterT", bound=BaseFilter)


def FilterDepends(model: type[FilterT]) -> FilterT:  # noqa: N802
    class FilterWrapper(model):  # type: ignore[valid-type, misc]
        def __new__(cls, *args: Any, **kwargs: Any) -> FilterT:  # type: ignore[misc, unused-ignore]
            try:
                return model(*args, **kwargs)
            except ValidationError as e:
                raise RequestValidationError(e.errors()) from e

    return Depends(FilterWrapper)


def NestedFilter(model: type[FilterT], prefix: str | None = None) -> FilterT:  # noqa: N802
    if prefix:

        def _alias_generator(field_name: str) -> str:
            return f"{prefix}__{field_name}"

        class NestedFilterModel(model):  # type: ignore[valid-type, misc]
            model_config = ConfigDict(alias_generator=_alias_generator)

        model = NestedFilterModel

    return FilterDepends(model)
