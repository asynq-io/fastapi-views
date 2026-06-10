from __future__ import annotations

import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from .formatter import Formatter, StrFormatter

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence


_current_locale: ContextVar[str | None] = ContextVar("_current_locale", default=None)


def set_locale(locale: str) -> None:
    _current_locale.set(locale)


@contextmanager
def override_locale(locale: str) -> Generator[None]:
    token = _current_locale.set(locale)
    try:
        yield
    finally:
        _current_locale.reset(token)


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
        if default not in self.supported_locales:
            msg = f"Default value {default} is not supported"
            raise ValueError(msg)

    def format_text(self, text: str, **kwargs: Any) -> str:
        return self.formatter.format(text, **kwargs)

    def format_key(self, key: str, locale: str | None = None, **kwargs: Any) -> str:
        if locale is None:
            locale = self.get_locale()
        if locale not in self.supported_locales:
            msg = f"Unsupported locale {locale}"
            raise ValueError(msg)
        try:
            text = self.get_key(key, locale=locale)
        except KeyError:
            _, _, text = key.rpartition(".")
        # Expose the resolved locale to the formatter (e.g. Jinja/Babel filters),
        # so an explicitly passed `locale` is honored during interpolation too.
        return self.format_text(text, **kwargs)

    @abstractmethod
    def get_key(self, key: str, *, locale: str) -> str:
        raise NotImplementedError

    def get_locale(self) -> str:
        return _current_locale.get() or self.default


class NoTranslations(TranslationManager):
    def get_key(self, key: str, *, locale: str) -> str:  # noqa: ARG002
        return key


class _DictTranslationManager(TranslationManager):
    """Base for managers backed by nested ``dict`` data, one mapping per locale.

    Subclasses only provide ``get_locale_data``; key resolution (dotted-key
    traversal plus fallback to the default locale) is shared.
    """

    @staticmethod
    def _traverse(data: dict[str, Any], key: str) -> str:
        value: Any = data
        for key_part in key.split("."):
            value = value[key_part]
        if not isinstance(value, str):
            msg = f"Expected string at {key}, got {type(value)}"
            raise TypeError(msg)
        return value

    def get_key(self, key: str, *, locale: str) -> str:
        try:
            return self._traverse(self.get_locale_data(locale), key)
        except KeyError:
            return self._traverse(self.get_locale_data(self.default), key)

    @abstractmethod
    def get_locale_data(self, locale: str) -> dict[str, Any]:
        """Return the translation mapping for ``locale``, or raise ``KeyError``."""
        raise NotImplementedError


class InMemoryTranslations(_DictTranslationManager):
    def __init__(
        self,
        data: dict[str, Any] | None = None,
        default: str = "en",
        supported_locales: Sequence[str] | None = None,
        formatter: Formatter = StrFormatter(),
    ) -> None:
        super().__init__(default, supported_locales, formatter)
        self._data: dict[str, Any] = data or {}

    def get_locale_data(self, locale: str) -> dict[str, Any]:
        return self._data[locale]


class JsonFilesTranslations(_DictTranslationManager):
    def __init__(
        self,
        dir_name: str = "./translations",
        default: str = "en",
        supported_locales: Sequence[str] | None = None,
        formatter: Formatter = StrFormatter(),
    ) -> None:
        super().__init__(default, supported_locales, formatter)
        self.dir = Path(dir_name)
        if not self.dir.exists():
            raise NotADirectoryError(dir_name)
        self._lock = Lock()
        self._cache: dict[str, Any] = {}

    def get_locale_data(self, locale: str) -> dict[str, Any]:
        with self._lock:
            if locale not in self._cache:
                path = self.dir / f"{locale}.json"
                if not path.exists():
                    raise KeyError(locale)
                with open(path) as f:
                    self._cache[locale] = json.load(f)
            return self._cache[locale]


_manager: TranslationManager | None = None


def get_manager() -> TranslationManager:
    global _manager  # noqa: PLW0603
    if _manager is None:
        _manager = NoTranslations()
    return _manager


def get_locale() -> str:
    return get_manager().get_locale()


def configure_translations(manager: TranslationManager) -> None:
    global _manager  # noqa: PLW0603
    _manager = manager


def translate(text: str, locale: str | None = None, **kwargs: Any) -> str:
    return get_manager().format_key(text, locale=locale, **kwargs)
