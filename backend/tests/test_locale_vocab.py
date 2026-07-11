"""Regression tests for centralized locale vocab (currency codes and units)."""

from __future__ import annotations

import re

from app.services.extraction.finance_field_labels import build_money_inline_patterns
from app.services.extraction.line_item_skip_patterns import OPTIONAL_CURRENCY_MONEY_PREFIX
from app.services.extraction.line_items_parser import _CHARGE_FREIGHT, _CHARGE_TOTAL, _GRN_QTY_TABLE_ROW
from app.services.extraction.locale_vocab import (
    SUPPORTED_CURRENCY_CODES,
    SUPPORTED_UNIT_TOKENS,
    currency_alternation_regex,
    optional_currency_code_group,
    unit_alternation_regex,
)


def _consumer_currency_patterns() -> list[str]:
    patterns = [
        OPTIONAL_CURRENCY_MONEY_PREFIX,
        optional_currency_code_group(),
        _CHARGE_FREIGHT.pattern,
        _CHARGE_TOTAL.pattern,
    ]
    for _key, compiled in build_money_inline_patterns():
        if "FREIGHT" in compiled.pattern:
            patterns.append(compiled.pattern)
    return patterns


def _consumer_unit_patterns() -> list[str]:
    return [_GRN_QTY_TABLE_ROW.pattern]


def test_all_consumer_patterns_include_every_currency_code() -> None:
    patterns = _consumer_currency_patterns()
    alt = currency_alternation_regex()
    for code in SUPPORTED_CURRENCY_CODES:
        assert code in alt
    for pattern in patterns:
        for code in SUPPORTED_CURRENCY_CODES:
            assert code in pattern, f"{code} missing from pattern {pattern[:80]}"


def test_all_consumer_patterns_include_every_unit_token() -> None:
    alt = unit_alternation_regex()
    for unit in SUPPORTED_UNIT_TOKENS:
        assert unit in alt or unit.lower() in alt.lower()
    for pattern in _consumer_unit_patterns():
        for unit in SUPPORTED_UNIT_TOKENS:
            assert unit in pattern, f"{unit} missing from {pattern[:80]}"


def test_unit_alternation_longest_first() -> None:
    alt = unit_alternation_regex()
    parts = alt.split("|")
    litre_idx = parts.index("Litre")
    ltr_idx = parts.index("Ltr")
    assert litre_idx < ltr_idx
    dozen_idx = parts.index("Dozen")
    doz_idx = parts.index("Doz")
    assert dozen_idx < doz_idx


def test_currency_alternation_compiles() -> None:
    re.compile(rf"(?:{currency_alternation_regex()})")
    re.compile(rf"(?:{unit_alternation_regex()})")
