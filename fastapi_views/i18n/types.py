from __future__ import annotations

from typing import Annotated, TypeVar

from pydantic import PlainSerializer

from .translations import translate

T = TypeVar("T", bound=str)

Translated = Annotated[
    T,
    PlainSerializer(translate, return_type=str, when_used="json-unless-none"),
]

TranslatedStr = Translated[str]
