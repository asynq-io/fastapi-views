from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import UserDict
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from .formatter import Formatter, StrFormatter
from .locale import get_locale

if TYPE_CHECKING:
    from collections.abc import Sequence


class TranslationManager(ABC):
    def __init__(
        self,
        default: str = "en",
        supported_locales: Sequence[str] | None = None,
        formatter: Formatter = StrFormatter(),
    ) -> None:
        self.default = default
        self.supported_locales = supported_locales or (default,)
        self.formatter = formatter

    def format_text(self, text: str, **kwargs: Any) -> str:
        return self.formatter.format(text, **kwargs)

    def format_key(self, key: str, locale: str | None = None, **kwargs: Any) -> str:
        if locale is None:
            locale = get_locale() or self.default
        if locale not in self.supported_locales:
            msg = f"Unsupported locale {locale}"
            raise ValueError(msg)
        try:
            text = self.get_key(key, locale=locale)
        except KeyError:
            _, _, text = key.rpartition(".")
        return self.format_text(text, **kwargs)

    @abstractmethod
    def get_key(self, key: str, *, locale: str) -> str:
        raise NotImplementedError


class NoTranslations(TranslationManager):
    def get_key(self, key: str, *, locale: str) -> str:  # noqa: ARG002
        return key


class InMemoryTranslations(TranslationManager, UserDict):
    def get_key(self, key: str, *, locale: str) -> str:
        try:
            return self[locale][key]
        except KeyError:
            return self[self.default][key]


class JsonFilesTranslations(TranslationManager):
    def __init__(self, dir_name: str = "./translations") -> None:
        self.dir = Path(dir_name)
        if not self.dir.exists():
            raise NotADirectoryError(dir_name)
        self._lock = Lock()
        self._cache: dict[str, Any] = {}

    def _get_locale(self, locale: str) -> dict[str, Any]:
        with self._lock:
            if locale not in self._cache:
                path = self.dir / f"{locale}.json"
                if not path.exists():
                    return self._cache[self.default]
                with open(path) as f:
                    data = json.load(f)
                self._cache[locale] = data
            return self._cache[locale]

    def get_key(self, key: str, *, locale: str) -> str:
        value = self._get_locale(locale)
        key_parts = key.split(".")

        for key_part in key_parts:
            value = value[key_part]
        if not isinstance(value, str):
            msg = f"Expected string at {key}, got {type(value)}"
            raise TypeError(msg)
        return value


_manager: TranslationManager | None = None


def configure_translations(manager: TranslationManager) -> None:
    global _manager  # noqa: PLW0603
    _manager = manager


def gettext_lazy(text: str, locale: str | None = None, **kwargs: Any) -> str:
    if _manager is None:
        return text
    return _manager.format_key(text, locale=locale, **kwargs)
