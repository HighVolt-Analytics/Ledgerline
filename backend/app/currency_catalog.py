"""Active ISO 4217 currency seed — used by Alembic 084 bootstrap and test fixtures.

Runtime validation uses pycountry via ``validate_currency_code`` / ``is_iso4217_currency``.
"""

from __future__ import annotations

from typing import TypedDict


class CurrencySeed(TypedDict):
    code: str
    name: str
    symbol: str
    decimal_places: int


# Platform-supported books currencies (extend without schema changes).
CURRENCY_SEEDS: tuple[CurrencySeed, ...] = (
    {"code": "AUD", "name": "Australian Dollar", "symbol": "A$", "decimal_places": 2},
    {"code": "USD", "name": "US Dollar", "symbol": "$", "decimal_places": 2},
    {"code": "GBP", "name": "British Pound", "symbol": "£", "decimal_places": 2},
    {"code": "INR", "name": "Indian Rupee", "symbol": "₹", "decimal_places": 2},
    {"code": "SGD", "name": "Singapore Dollar", "symbol": "S$", "decimal_places": 2},
    {"code": "NZD", "name": "New Zealand Dollar", "symbol": "NZ$", "decimal_places": 2},
    {"code": "AED", "name": "UAE Dirham", "symbol": "د.إ", "decimal_places": 2},
    {"code": "EUR", "name": "Euro", "symbol": "€", "decimal_places": 2},
)

ACTIVE_CURRENCY_CODES: frozenset[str] = frozenset(row["code"] for row in CURRENCY_SEEDS)

# Country → default books currency (suggestion only; matches jurisdiction packs).
COUNTRY_DEFAULT_CURRENCY: dict[str, str] = {
    "AU": "AUD",
    "US": "USD",
    "GB": "GBP",
    "IN": "INR",
    "SG": "SGD",
    "NZ": "NZD",
    "AE": "AED",
    "DE": "EUR",
}
