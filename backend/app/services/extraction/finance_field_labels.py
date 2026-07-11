"""Registry-driven finance field labels for money extraction (single source of truth)."""

from __future__ import annotations

import re

from app.services.extraction.extraction_field_values import _FIELD_HINT_PATTERNS
from app.services.extraction.line_item_skip_patterns import OPTIONAL_CURRENCY_MONEY_PREFIX
from app.services.extraction.locale_vocab import optional_currency_code_group

MONEY_SCALAR_KEYS: tuple[str, ...] = ("subtotal", "gst", "gst_rate", "total")

_MONEY_CAPTURE = rf"({OPTIONAL_CURRENCY_MONEY_PREFIX}[\d,]+\.?\d*)"

# Extra role-derived terms from finance defs (not duplicated in hint strings).
_ROLE_TERMS: dict[str, tuple[str, ...]] = {
    "total": ("grand total", "invoice total", "balance due", "amount payable"),
    "subtotal": ("net amount", "amount ex gst", "amount excl"),
    "gst": ("vat", "tax amount"),
    "gst_rate": ("tax rate", "vat %"),
}


def finance_label_terms(key: str) -> list[str]:
    """Normalized label search terms for a finance/money field."""
    from app.registry.adapter import use_field_registry, get_registry_adapter

    token = str(key or "").strip().lower()
    if not token:
        return []
    seen: set[str] = set()
    terms: list[str] = []
    if use_field_registry():
        for part in get_registry_adapter().synonyms_for(token):
            lowered = part.lower()
            if lowered not in seen:
                seen.add(lowered)
                terms.append(part)
    else:
        for raw in re.split(r",\s*", _FIELD_HINT_PATTERNS.get(token, "")):
            part = raw.strip()
            if not part:
                continue
            lowered = part.lower()
            if lowered not in seen:
                seen.add(lowered)
                terms.append(part)
    for extra in _ROLE_TERMS.get(token, ()):
        if extra not in seen:
            seen.add(extra)
            terms.append(extra)
    spaced = token.replace("_", " ")
    if spaced not in seen:
        terms.append(spaced)
    return terms


def _terms_regex_alternation(terms: list[str]) -> str:
    parts: list[str] = []
    for term in terms:
        body = re.escape(term.strip()).replace(r"\ ", r"\s+")
        parts.append(body)
    return "|".join(parts) if parts else re.escape("")


def build_kv_label_pattern(key: str) -> re.Pattern[str]:
    """Whole-line label pattern for layout KV / table label cells."""
    alt = _terms_regex_alternation(finance_label_terms(key))
    return re.compile(rf"(?i)^(?:{alt})\.?$")


def label_matches_field(text: str, key: str) -> bool:
    """True when text is a finance label for the given field key."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip()).rstrip(":")
    if not cleaned:
        return False
    return bool(build_kv_label_pattern(key).search(cleaned))


def build_money_label_regex(key: str, *, inline: bool = True) -> re.Pattern[str]:
    """Regex: label followed by money on same line."""
    alt = _terms_regex_alternation(finance_label_terms(key))
    if inline:
        return re.compile(
            rf"(?i)(?:{alt})\s*[:\-]?\s*{_MONEY_CAPTURE}",
            re.I,
        )
    return re.compile(rf"(?i)^(?:{alt})\s*[:\-]?\s*$", re.I | re.M)


def build_money_multiline_regex(key: str) -> re.Pattern[str]:
    """Regex: label line then amount on next 1–2 lines."""
    alt = _terms_regex_alternation(finance_label_terms(key))
    return re.compile(
        rf"(?i)^(?:{alt})\s*[:\-]?\s*$\s*{_MONEY_CAPTURE}",
        re.I | re.M,
    )


def build_money_inline_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """All inline money patterns derived from the registry."""
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for key in ("subtotal", "gst", "total"):
        patterns.append((key, build_money_label_regex(key)))
    patterns.append(
        (
            "total",
            re.compile(
                rf"(?i)FREIGHT\s*[:\-]?\s*{optional_currency_code_group()}\s*{_MONEY_CAPTURE}",
            ),
        )
    )
    patterns.append(
        (
            "gst",
            re.compile(rf"(?i)GST(?:\s*\d+%)?\s*[:\-]?\s*{_MONEY_CAPTURE}\b"),
        )
    )
    return patterns


def money_kv_label_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """KV label patterns for money scalar keys."""
    return [(key, build_kv_label_pattern(key)) for key in ("subtotal", "gst", "total")]
