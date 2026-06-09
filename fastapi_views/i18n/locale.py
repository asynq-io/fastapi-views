from contextvars import ContextVar

_CURRENT_LOCALE: ContextVar[str | None] = ContextVar("_CURRENT_LOCALE", default=None)


def get_locale() -> str | None:
    return _CURRENT_LOCALE.get()


def set_locale(locale: str) -> None:
    _CURRENT_LOCALE.set(locale)
