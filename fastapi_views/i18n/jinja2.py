from collections.abc import Callable
from typing import Any, TypeVar, overload

from babel import Locale
from babel.dates import format_date
from babel.numbers import format_currency, format_decimal
from jinja2 import Environment, StrictUndefined

from .translations import get_locale

R = TypeVar("R")


def pluralize(
    n: float,
    forms: dict[str, str],
) -> str:
    """Pick the variant in ``forms`` matching ``n``'s plural category.

    ``forms`` maps CLDR plural categories (``"one"``, ``"few"``, ``"many"``,
    ``"other"``, ...) to text; the right category for ``n`` is resolved from the
    active ``locale`` via Babel, so each language uses its own plural rules.
    """
    locale = Locale.parse(get_locale())
    category = locale.plural_form(n)
    return forms.get(category) or forms.get("other") or ""


@overload
def with_locale(func: Callable[..., R], **defaults: Any) -> Callable[..., R]: ...


@overload
def with_locale(
    func: None = ..., **defaults: Any
) -> Callable[[Callable[..., R]], Callable[..., R]]: ...


def with_locale(
    func: Callable[..., R] | None = None, **defaults: Any
) -> Callable[..., R] | Callable[[Callable[..., R]], Callable[..., R]]:
    def wrapper(func: Callable[..., R]) -> Callable[..., R]:
        def decorator(*args: Any, **kwargs: Any) -> R:
            kwargs["locale"] = get_locale()
            for k, v in defaults.items():
                kwargs.setdefault(k, v)
            return func(*args, **kwargs)

        return decorator

    if func is None:
        return wrapper
    return wrapper(func)


def build_environment() -> Environment:
    """A Jinja environment with the i18n extension and Babel locale-aware filters."""
    env = Environment(
        undefined=StrictUndefined,
        autoescape=True,
    )
    env.filters.update(
        {
            "currency": with_locale(format_currency),
            "number": with_locale(format_decimal),
            "date": with_locale(format_date, format="long"),
            "pluralize": pluralize,
        }
    )
    return env


class JinjaFormatter:
    def __init__(self, env: Environment | None = None) -> None:
        if env is None:
            env = build_environment()
        self._env = env

    def format(self, text: str, **kwargs: Any) -> str:
        template = self._env.from_string(text)
        return template.render(**kwargs)
