"""Internationalization with Babel-powered Jinja translations.

Install the extra and run it:

    pip install "fastapi-views[i18n]"
    uvicorn examples.i18n:app

Then try the same endpoint in different locales and item counts. Note how each
language pluralizes the noun with its own rules — English has two forms, Polish
and Russian have three (and disagree: 21 is "few" in Polish but "one" in Russian):

    curl 'localhost:8000/cart?lang=en&count=1'    # 1 item
    curl 'localhost:8000/cart?lang=en&count=5'    # 5 items
    curl 'localhost:8000/cart?lang=pl&count=1'    # 1 produkt
    curl 'localhost:8000/cart?lang=pl&count=2'    # 2 produkty
    curl 'localhost:8000/cart?lang=pl&count=5'    # 5 produktów
    curl 'localhost:8000/cart?lang=ru&count=21'   # 21 товар

The message *text* comes from the per-locale translation tables, while Babel
formats the embedded numbers, currencies and dates — and selects the correct
plural form — for the active locale.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import FastAPI

from fastapi_views import configure_app
from fastapi_views.i18n import InMemoryTranslations
from fastapi_views.i18n import translate as _
from fastapi_views.i18n.jinja2 import JinjaFormatter

# Each language supplies the plural forms its own rules require: English needs
# only "one"/"other"; Polish and Russian add "few" and "many".
translations = InMemoryTranslations(
    {
        "en": {
            "cart": {
                "summary": "{{ count | number }}"
                " {{ count | pluralize({'one': 'item', 'other': 'items'}) }}"
                " totalling {{ total | currency(user_currency) }}.",
                "updated": "Last updated on {{ updated_at | date }}.",
            },
        },
        "pl": {
            "cart": {
                "summary": "{{ count | number }}"
                " {{ count | pluralize({'one': 'produkt', 'few': 'produkty', 'many': 'produktów'}) }}"
                " na łączną kwotę {{ total | currency(user_currency) }}.",
                "updated": "Ostatnia aktualizacja: {{ updated_at | date }}.",
            },
        },
        "ru": {
            "cart": {
                "summary": "{{ count | number }}"
                " {{ count | pluralize({'one': 'товар', 'few': 'товара', 'many': 'товаров'}) }}"
                " на сумму {{ total | currency(user_currency) }}.",
                "updated": "Последнее обновление: {{ updated_at | date }}.",
            },
        },
    },
    default="en",
    supported_locales=["en", "pl", "ru"],
    formatter=JinjaFormatter(),
)

app = FastAPI(title="i18n example")
# Installs LocaleMiddleware and registers the translation manager.
configure_app(app, translation_manager=translations)


@app.get("/cart")
async def cart(count: int = 1, currency: Literal["USD", "PLN"] = "USD"):
    # No locale argument needed — translate reads the request's locale.
    return {
        # `count` drives pluralization; `currency` is data (the cart's currency),
        # both passed at runtime. Babel handles the locale-specific formatting.
        "summary": _(
            "cart.summary", count=count, total=count * 19.99, user_currency=currency
        ),
        "updated": _("cart.updated", updated_at=date(2026, 6, 9)),
    }
