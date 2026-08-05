"""ISO 3166 countries + currency / timezone / locale suggestions (pycountry + Babel CLDR)."""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.shared.iso4217_catalog import is_iso4217_currency

DEFAULT_CURRENCY = "SGD"

# Primary commercial / HQ timezone when a country spans multiple IANA zones.
# Same convention used by ERP/SaaS products: capital or financial centre, not
# Babel's arbitrary first entry (e.g. US must not resolve to America/Adak).
PRIMARY_BUSINESS_TIMEZONE: dict[str, str] = {
    "AQ": "Antarctica/McMurdo",
    "AR": "America/Argentina/Buenos_Aires",
    "AU": "Australia/Sydney",
    "BR": "America/Sao_Paulo",
    "CA": "America/Toronto",
    "CD": "Africa/Kinshasa",
    "CL": "America/Santiago",
    "CN": "Asia/Shanghai",
    "CY": "Asia/Nicosia",
    "DE": "Europe/Berlin",
    "EC": "America/Guayaquil",
    "ES": "Europe/Madrid",
    "FM": "Pacific/Pohnpei",
    "GL": "America/Nuuk",
    "ID": "Asia/Jakarta",
    "KI": "Pacific/Tarawa",
    "KZ": "Asia/Almaty",
    "MH": "Pacific/Majuro",
    "MN": "Asia/Ulaanbaatar",
    "MX": "America/Mexico_City",
    "MY": "Asia/Kuala_Lumpur",
    "NZ": "Pacific/Auckland",
    "PF": "Pacific/Tahiti",
    "PG": "Pacific/Port_Moresby",
    "PS": "Asia/Hebron",
    "PT": "Europe/Lisbon",
    "RU": "Europe/Moscow",
    "UA": "Europe/Kyiv",
    "UM": "Pacific/Wake",
    "US": "America/New_York",
    "UZ": "Asia/Tashkent",
}


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


def _is_valid_iana_timezone(value: str) -> bool:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return False
    return True


@lru_cache(maxsize=512)
def territory_timezones(country_code: str) -> tuple[str, ...]:
    """All valid IANA zones for an ISO country (Unicode CLDR territory_zones)."""
    code = (country_code or "").strip().upper()
    if len(code) != 2:
        return ()
    try:
        from babel.core import get_global

        raw = get_global("territory_zones").get(code) or ()
    except Exception:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for zone in raw:
        token = str(zone or "").strip()
        if not token or token in seen or not _is_valid_iana_timezone(token):
            continue
        seen.add(token)
        out.append(token)
    out.sort()
    return tuple(out)


@lru_cache(maxsize=512)
def default_timezone_for_country(country_code: str) -> str | None:
    """Primary IANA timezone for an ISO country.

    Resolution order (MNC / ERP style):
    1. Curated commercial HQ zone when the country is multi-zone
    2. Sole CLDR territory zone (e.g. MM → Asia/Yangon)
    3. First valid CLDR zone as last resort for that country
    Never invents Asia/Singapore for a non-SG country that has CLDR data.
    """
    code = (country_code or "").strip().upper()
    if not code:
        return None

    zones = territory_timezones(code)
    if not zones:
        return None

    preferred = PRIMARY_BUSINESS_TIMEZONE.get(code)
    if preferred and preferred in zones:
        return preferred
    if preferred and _is_valid_iana_timezone(preferred):
        # Curated primary may use a canonical alias not listed in CLDR.
        return preferred

    if len(zones) == 1:
        return zones[0]

    return zones[0]


@lru_cache(maxsize=512)
def default_locale_for_country(country_code: str) -> str | None:
    """BCP 47 locale suggestion for an ISO country (language + territory when known)."""
    code = (country_code or "").strip().upper()
    if not code:
        return None
    try:
        from babel import Locale

        loc = Locale.parse(f"und_{code}")
        # Prefer an explicit language when CLDR knows one for the territory.
        if loc.language and loc.language != "und":
            return str(loc).replace("_", "-")
        # Fall back to English + territory (common for finance UIs).
        return f"en-{code}"
    except Exception:
        return None


def clear_iso_geo_catalog_cache() -> None:
    iso3166_country_codes.cache_clear()
    iso3166_countries.cache_clear()
    default_currency_for_country.cache_clear()
    list_iso4217_currency_meta.cache_clear()
    territory_timezones.cache_clear()
    default_timezone_for_country.cache_clear()
    default_locale_for_country.cache_clear()
