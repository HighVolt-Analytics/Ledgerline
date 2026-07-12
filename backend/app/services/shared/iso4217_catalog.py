"""ISO 4217 currency catalog backed by ``pycountry`` (no hardcoded code list)."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def iso4217_currency_codes() -> frozenset[str]:
    """All active ISO 4217 alpha-3 currency codes from pycountry."""
    import pycountry

    return frozenset(currency.alpha_3.upper() for currency in pycountry.currencies)


def is_iso4217_currency(code: str | None) -> bool:
    """True when ``code`` is a real ISO 4217 alpha-3 currency."""
    token = (code or "").strip().upper()
    if len(token) != 3 or not token.isalpha():
        return False
    return token in iso4217_currency_codes()


def currency_alternation_regex() -> str:
    """Longest-first regex alternation of every ISO 4217 alpha-3 code."""
    codes = sorted(iso4217_currency_codes(), key=lambda token: (-len(token), token))
    return "|".join(codes)
