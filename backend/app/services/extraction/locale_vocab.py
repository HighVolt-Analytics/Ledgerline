"""Single source of truth for currency codes and unit tokens in extraction regex."""

from __future__ import annotations

import re

# Corpus: line_item_skip_patterns + audit additions (CHF, AED); grep-verified in tests.
SUPPORTED_CURRENCY_CODES: frozenset[str] = frozenset(
    {
        "AUD",
        "USD",
        "SGD",
        "NZD",
        "GBP",
        "EUR",
        "CAD",
        "INR",
        "MYR",
        "THB",
        "HKD",
        "JPY",
        "CNY",
        "CHF",
        "AED",
    }
)

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

_CURRENCY_SYMBOLS = r"[$€£¥]"


def _sorted_alternation(tokens: frozenset[str]) -> str:
    """Longest-first alternation to reduce partial-match shadowing."""
    ordered = sorted(tokens, key=lambda token: (-len(token), token.lower()))
    return "|".join(re.escape(token) for token in ordered)


def currency_alternation_regex() -> str:
    return _sorted_alternation(SUPPORTED_CURRENCY_CODES)


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
