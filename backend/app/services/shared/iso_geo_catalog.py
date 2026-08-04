"""ISO 3166 countries + country→default-currency suggestions (pycountry + Babel)."""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from app.services.shared.iso4217_catalog import is_iso4217_currency

DEFAULT_CURRENCY = "SGD"


class CountryRow(TypedDict):
    code: str
    name: str


@lru_cache(maxsize=1)
def iso3166_country_codes() -> frozenset[str]:
    import pycountry

    return frozenset(c.alpha_2.upper() for c in pycountry.countries if getattr(c, "alpha_2", None))


def is_iso3166_country(code: str | None) -> bool:
    token = (code or "").strip().upper()
    if len(token) != 2 or not token.isalpha():
        return False
    return token in iso3166_country_codes()


@lru_cache(maxsize=1)
def iso3166_countries() -> tuple[CountryRow, ...]:
    import pycountry

    rows: list[CountryRow] = []
    for country in pycountry.countries:
        code = getattr(country, "alpha_2", None)
        if not code:
            continue
        name = (
            getattr(country, "common_name", None)
            or getattr(country, "name", None)
            or getattr(country, "official_name", None)
            or code
        )
        rows.append({"code": str(code).upper(), "name": str(name)})
    rows.sort(key=lambda r: r["name"].casefold())
    return tuple(rows)


def clear_iso_geo_catalog_cache() -> None:
    iso3166_country_codes.cache_clear()
    iso3166_countries.cache_clear()
    default_currency_for_country.cache_clear()
    list_iso4217_currency_meta.cache_clear()


@lru_cache(maxsize=512)
def default_currency_for_country(country_code: str) -> str:
    """Suggested books currency for a country (not enforced)."""
    code = (country_code or "").strip().upper()
    if not code:
        return DEFAULT_CURRENCY

    # Prefer jurisdiction pack default when we have a rich pack.
    try:
        from app.jurisdiction.loader import get_pack_registry

        pack = get_pack_registry().packs.get(code)
        if pack is not None and pack.currency and is_iso4217_currency(pack.currency):
            return pack.currency.strip().upper()
    except Exception:
        pass

    try:
        from babel.numbers import get_territory_currencies

        for ccy in get_territory_currencies(code):
            token = str(ccy or "").strip().upper()
            if is_iso4217_currency(token):
                return token
    except Exception:
        pass

    return DEFAULT_CURRENCY


class CurrencyMetaRow(TypedDict):
    code: str
    name: str
    symbol: str
    decimal_places: int


@lru_cache(maxsize=1)
def list_iso4217_currency_meta() -> tuple[CurrencyMetaRow, ...]:
    import pycountry
    from babel.numbers import get_currency_symbol

    rows: list[CurrencyMetaRow] = []
    for currency in pycountry.currencies:
        code = str(currency.alpha_3).upper()
        name = str(getattr(currency, "name", None) or code)
        try:
            symbol = get_currency_symbol(code, locale="en") or ""
        except Exception:
            symbol = ""
        if symbol == code:
            symbol = ""
        rows.append(
            {
                "code": code,
                "name": name,
                "symbol": symbol,
                "decimal_places": 2,
            }
        )
    rows.sort(key=lambda r: r["code"])
    return tuple(rows)
