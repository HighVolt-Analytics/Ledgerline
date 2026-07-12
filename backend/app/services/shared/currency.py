"""Convert invoice amounts to a single reporting currency for dashboard aggregates.

OCR helpers recover ISO codes or money symbols when DI omits CurrencyCode.
ISO validation uses ``pycountry`` via ``iso4217_catalog`` (no hardcoded code list).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import re

from app.services.shared.iso4217_catalog import is_iso4217_currency
from app.tenant_settings import COUNTRY_CURRENCY, DEFAULT_COUNTRY

# Static rates relative to AUD — used as an FX graph; convert via cross rates.
_FX_TO_AUD: dict[str, Decimal] = {
    "AUD": Decimal("1"),
    "USD": Decimal("1.55"),
    "INR": Decimal("0.018"),
    "GBP": Decimal("1.95"),
    "EUR": Decimal("1.65"),
    "NZD": Decimal("0.92"),
    "SGD": Decimal("1.15"),
    "AED": Decimal("0.42"),
}

# Platform reporting fallback when no tenant context is available.
BASE_CURRENCY = COUNTRY_CURRENCY[DEFAULT_COUNTRY]

UNKNOWN_CURRENCY = "UNKNOWN"

# Symbols that map to more than one ISO code — never invent a country.
AMBIGUOUS_CURRENCY_SYMBOLS = frozenset({"$", "¥"})
# 1:1 glyph → ISO (safe to store without user confirm).
UNAMBIGUOUS_SYMBOL_TO_ISO = {
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
}

# Common currency glyphs near amounts.
_CURRENCY_GLYPHS = r"[$€£¥₹₩₪₫₱₽₴₺₦₡₵₲]"

# Uppercase-only tokens (avoids matching English words like "try"/"may").
_UPPER_ISO_TOKEN = re.compile(r"(?<![A-Z0-9])([A-Z]{3})(?![A-Z0-9])")

_ISO_NEAR_MONEY = re.compile(
    rf"(?:"
    rf"(?<![A-Za-z0-9])(?P<code_before>[A-Za-z]{{3}})(?![A-Za-z0-9])\s*(?:{_CURRENCY_GLYPHS})?\s*"
    rf"(?P<amt_before>[\d][\d,]*(?:\.\d{{1,4}})?)"
    rf"|(?P<amt_after>[\d][\d,]*(?:\.\d{{1,4}})?)\s*(?:{_CURRENCY_GLYPHS})?\s*"
    rf"(?<![A-Za-z0-9])(?P<code_after>[A-Za-z]{{3}})(?![A-Za-z0-9])"
    rf")"
)
_SYMBOL_NEAR_MONEY = re.compile(
    rf"(?:(?P<sym_before>{_CURRENCY_GLYPHS})\s*(?P<amt_before>[\d][\d,]*(?:\.\d{{1,4}})?)"
    rf"|(?P<amt_after>[\d][\d,]*(?:\.\d{{1,4}})?)\s*(?P<sym_after>{_CURRENCY_GLYPHS}))"
)


def _normalize_currency_code(currency: str | None) -> str | None:
    token = (currency or "").strip().upper()
    return token or None


def _amount_looks_like_money(amount: str | None) -> bool:
    """Reject bare day numbers (e.g. May 3) — require decimals or a larger integer."""
    token = (amount or "").strip()
    if not token:
        return False
    if "." in token or "," in token:
        return True
    digits = re.sub(r"\D", "", token)
    return len(digits) >= 3


def detect_currency_code_in_text(text: str | None) -> str | None:
    """Return the strongest ISO 4217 currency code in OCR text, if any.

    Preference:
    1. Uppercase ISO tokens validated via pycountry
    2. Case-insensitive codes next to money amounts, also pycountry-validated
    """
    if not text:
        return None

    uppercase_hits = Counter(
        match.group(1)
        for match in _UPPER_ISO_TOKEN.finditer(text)
        if is_iso4217_currency(match.group(1))
    )
    if uppercase_hits:
        return uppercase_hits.most_common(1)[0][0]

    near_money: Counter[str] = Counter()
    for match in _ISO_NEAR_MONEY.finditer(text):
        code = (match.group("code_before") or match.group("code_after") or "").upper()
        amount = match.group("amt_before") or match.group("amt_after")
        if not is_iso4217_currency(code):
            continue
        if not _amount_looks_like_money(amount):
            continue
        near_money[code] += 1
    if near_money:
        return near_money.most_common(1)[0][0]
    return None


def detect_currency_symbol_in_text(text: str | None) -> str | None:
    """Return the dominant money symbol near amounts, or None when absent."""
    if not text:
        return None
    counts: Counter[str] = Counter()
    for match in _SYMBOL_NEAR_MONEY.finditer(text):
        symbol = match.group("sym_before") or match.group("sym_after")
        if symbol:
            counts[symbol] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def resolve_currency_from_ocr(
    text: str | None,
    *,
    existing_currency: str | None = None,
) -> tuple[str, str | None]:
    """Resolve (iso_currency, currency_symbol) from OCR when DI left currency empty.

    Returns:
        iso_currency: ISO code or "" when unknown / ambiguous symbol only
        currency_symbol: display symbol when ISO is empty but a symbol was found
    """
    existing = (existing_currency or "").strip().upper()
    if existing and is_iso4217_currency(existing):
        return existing, None

    code = detect_currency_code_in_text(text)
    if code:
        return code, None

    symbol = detect_currency_symbol_in_text(text)
    if not symbol:
        return "", None

    mapped = UNAMBIGUOUS_SYMBOL_TO_ISO.get(symbol)
    if mapped:
        return mapped, None
    if symbol in AMBIGUOUS_CURRENCY_SYMBOLS:
        return "", symbol
    return "", symbol


def apply_currency_ocr_fallback(parsed: object, ocr_text: str | None) -> object:
    """Fill empty currency / currency_symbol on an InvoiceData-like object from OCR."""
    from dataclasses import replace

    current = getattr(parsed, "currency", None)
    if isinstance(current, str) and current.strip():
        return parsed

    iso, symbol = resolve_currency_from_ocr(ocr_text, existing_currency=None)
    extracted = dict(getattr(parsed, "extracted_fields", None) or {})
    updates: dict[str, object] = {}
    if iso:
        updates["currency"] = iso
        extracted.pop("currency_symbol", None)
    elif symbol:
        extracted["currency_symbol"] = symbol
        updates["currency"] = ""
    else:
        return parsed
    if extracted != (getattr(parsed, "extracted_fields", None) or {}):
        updates["extracted_fields"] = extracted
    if not updates:
        return parsed
    try:
        return replace(parsed, **updates)  # type: ignore[arg-type]
    except TypeError:
        for key, value in updates.items():
            setattr(parsed, key, value)
        return parsed


def fx_rate_to_base(currency: str | None, *, base: str | None = None) -> Decimal:
    """Rate to convert ``currency`` into ``base`` (default platform base).

    Missing/blank currency is non-convertible — returns ``0`` so aggregates do
    not silently treat unknown amounts as tenant-base 1:1.
    """
    target = (base or BASE_CURRENCY).upper()
    code = _normalize_currency_code(currency)
    if code is None:
        return Decimal("0")
    if code == target:
        return Decimal("1")
    to_aud = _FX_TO_AUD.get(code, Decimal("1"))
    base_to_aud = _FX_TO_AUD.get(target, Decimal("1"))
    if base_to_aud == 0:
        return Decimal("1")
    return to_aud / base_to_aud


def convert_to_base(
    amount: Decimal | None,
    currency: str | None,
    *,
    base: str | None = None,
) -> Decimal:
    if amount is None:
        return Decimal("0")
    if _normalize_currency_code(currency) is None:
        return Decimal("0")
    return amount * fx_rate_to_base(currency, base=base)


def sum_amounts_by_currency(
    rows: list[tuple[str | None, Decimal | None]],
    *,
    base: str | None = None,
) -> tuple[Decimal, dict[str, Decimal]]:
    """Return (total in base currency, raw totals grouped by currency code).

    Rows with missing currency are bucketed under ``UNKNOWN`` and excluded from
    ``total_base`` (not converted at 1:1 into the tenant base).
    """
    target = (base or BASE_CURRENCY).upper()
    by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_base = Decimal("0")
    for currency, amount in rows:
        if amount is None:
            continue
        code = _normalize_currency_code(currency)
        if code is None:
            by_currency[UNKNOWN_CURRENCY] += amount
            continue
        by_currency[code] += amount
        total_base += convert_to_base(amount, code, base=target)
    return total_base, dict(by_currency)
