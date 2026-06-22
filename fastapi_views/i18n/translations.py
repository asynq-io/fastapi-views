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
    from collections.abc import Generator, Mapping, Sequence

    Fallbacks = Mapping[str | tuple[str, ...], str | Sequence[str]]


class TranslationManager(ABC):
    def __init__(
        self,
        default: str = "en",
        supported_locales: Sequence[str] | None = None,
        formatter: Formatter = StrFormatter(),
        fallbacks: Fallbacks | None = None,
    ) -> None:
        self.default = default
        self.supported_locales = supported_locales or (default,)
        self.formatter = formatter
        self.fallbacks = self._normalize_fallbacks(fallbacks)
        if default not in self.supported_locales:
            msg = f"Default value {default} is not supported"
            raise ValueError(msg)
        self._fallback_chains: dict[str, tuple[str, ...]] = {
            locale: self._build_fallback_chain(locale)
            for locale in self.supported_locales
        }
        self._current_locale: ContextVar[str | None] = ContextVar(
            "current_locale", default=None
        )

    @staticmethod
    def _normalize_fallbacks(
        fallbacks: Fallbacks | None,
    ) -> dict[str, tuple[str, ...]]:
        """Flatten the user-facing fallback mapping into ``locale -> chain``.

        Keys may be a single locale or a tuple of locales sharing the same
        fallback; values may be a single locale or an ordered list of locales.
        """
        normalized: dict[str, tuple[str, ...]] = {}
        if not fallbacks:
            return normalized
        for locales, targets in fallbacks.items():
            sources = (locales,) if isinstance(locales, str) else tuple(locales)
            chain = (targets,) if isinstance(targets, str) else tuple(targets)
            for source in sources:
                normalized[source] = chain
        return normalized

    def _build_fallback_chain(self, locale: str) -> tuple[str, ...]:
        """Compute the ordered lookup chain for ``locale``.

        The order is the requested locale, its configured fallbacks, then the
        ``default`` locale; duplicates are removed while preserving order.
        """
        chain: list[str] = [locale]
        for fallback in (*self.fallbacks.get(locale, ()), self.default):
            if fallback not in chain:
                chain.append(fallback)
        return tuple(chain)

    def get_fallback_chain(self, locale: str) -> tuple[str, ...]:
        """Return the locales to try for ``locale``, best match first.

        Chains for the supported locales are precomputed at construction; an
        off-list locale is resolved on the fly.
        """
        return self._fallback_chains.get(locale) or self._build_fallback_chain(locale)

    def match_supported(self, tag: str) -> str | None:
        """Resolve a requested language tag to a supported locale, or ``None``.

        The tag itself is tried first, then its configured fallbacks, then its
        language subtag (``de-AT`` -> ``de``); the first supported result wins,
        so configured fallbacks take precedence over subtag stripping. Used by
        ``LocaleMiddleware`` to negotiate the active request locale.
        """
        if tag in self.supported_locales:
            return tag
        for fallback in self.fallbacks.get(tag, ()):
            if fallback in self.supported_locales:
                return fallback
        lang = tag.split("-", 1)[0]
        if lang in self.supported_locales:
            return lang
        return None

    def format_text(self, text: str, **kwargs: Any) -> str:
        return self.formatter.format(text, **kwargs)

    def format_key(self, key: str, locale: str | None = None, **kwargs: Any) -> str:
        if locale is None:
            locale = self.get_locale()
        if locale not in self.supported_locales:
            msg = f"Unsupported locale {locale}"
            raise ValueError(msg)
        text = self._resolve_key(key, locale)
        # Expose the resolved locale to the formatter (e.g. Jinja/Babel filters),
        # so an explicitly passed `locale` is honored during interpolation too.
        return self.format_text(text, **kwargs)

    def _resolve_key(self, key: str, locale: str) -> str:
        """Look up ``key`` across the fallback chain for ``locale``.

        Each candidate locale is tried in turn; if none provide the key, the
        text after the last ``.`` in the key is used so a missing key degrades
        gracefully instead of raising.
        """
        for candidate in self.get_fallback_chain(locale):
            text = self._try_get_key(key, candidate)
            if text is not None:
                return text
        _, _, text = key.rpartition(".")
        return text

    def _try_get_key(self, key: str, locale: str) -> str | None:
        """Resolve ``key`` for a single ``locale``, or ``None`` if it is missing."""
        try:
            return self.get_key(key, locale=locale)
        except KeyError:
            return None

    @abstractmethod
    def get_key(self, key: str, *, locale: str) -> str:
        raise NotImplementedError

    def set_locale(self, locale: str) -> None:
        """Set the active locale for the current context."""
        self._current_locale.set(locale)

    @contextmanager
    def override_locale(self, locale: str) -> Generator[None]:
        """Temporarily set the active locale within the ``with`` block."""
        token = self._current_locale.set(locale)
        try:
            yield
        finally:
            self._current_locale.reset(token)

    def get_locale(self) -> str:
        """Return the active locale for the current context, or the default."""
        return self._current_locale.get() or self.default


class NoTranslations(TranslationManager):
    def get_key(self, key: str, *, locale: str) -> str:  # noqa: ARG002
        return key


class _DictTranslationManager(TranslationManager):
    """Base for managers backed by nested ``dict`` data, one mapping per locale.

    Subclasses only provide ``get_locale_data``; dotted-key traversal and the
    fallback-chain lookup (inherited from ``TranslationManager``) are shared.
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
        return self._traverse(self.get_locale_data(locale), key)

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
        fallbacks: Fallbacks | None = None,
    ) -> None:
        super().__init__(default, supported_locales, formatter, fallbacks)
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
        fallbacks: Fallbacks | None = None,
    ) -> None:
        super().__init__(default, supported_locales, formatter, fallbacks)
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


@contextmanager
def override_locale(locale: str) -> Generator[None]:
    with get_manager().override_locale(locale):
        yield


def configure_translations(manager: TranslationManager) -> None:
    global _manager  # noqa: PLW0603
    _manager = manager


def translate(text: str, locale: str | None = None, **kwargs: Any) -> str:
    return get_manager().format_key(text, locale=locale, **kwargs)
