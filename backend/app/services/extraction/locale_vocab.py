"""Locale vocab for currency codes and unit tokens used in extraction regex.

Currency codes come from ISO 4217 via ``pycountry`` (see iso4217_catalog).
Unit tokens remain app-specific.
"""

from __future__ import annotations

import re

from app.services.shared.iso4217_catalog import (
    currency_alternation_regex as iso4217_currency_alternation_regex,
    iso4217_currency_codes,
)

# Full ISO 4217 set — single source of truth for "is this a currency code?".
SUPPORTED_CURRENCY_CODES: frozenset[str] = iso4217_currency_codes()

SUPPORTED_UNIT_TOKENS: frozenset[str] = frozenset(
    {
        "Kg",
        "Nos",
        "Box",
        "Pair",
        "Unit",
        "Units",
        "Ltr",
        "Litre",
        "Ctn",
        "Bag",
        "Set",
        "Roll",
        "Dozen",
        "Pcs",
        "Sqm",
        "Mtr",
        "Pkt",
        "Doz",
        "Case",
    }
)

_CURRENCY_SYMBOLS = r"[$€£¥₹₩₪₫₱₽₴₺₦₡₵₲]"


def _sorted_alternation(tokens: frozenset[str]) -> str:
    """Longest-first alternation to reduce partial-match shadowing."""
    ordered = sorted(tokens, key=lambda token: (-len(token), token.lower()))
    return "|".join(re.escape(token) for token in ordered)


def currency_alternation_regex() -> str:
    return iso4217_currency_alternation_regex()


def unit_alternation_regex() -> str:
    return _sorted_alternation(SUPPORTED_UNIT_TOKENS)


def optional_currency_code_group() -> str:
    """Optional ISO currency code prefix for charge/freight patterns."""
    return rf"(?:{currency_alternation_regex()})?"


def optional_currency_money_prefix() -> str:
    """Optional currency symbol or ISO code before a money amount."""
    return rf"(?:{_CURRENCY_SYMBOLS}|(?:{currency_alternation_regex()})\s*)?"


# Backward-compatible alias used across extraction and frontend parity comments.
OPTIONAL_CURRENCY_MONEY_PREFIX = optional_currency_money_prefix()
