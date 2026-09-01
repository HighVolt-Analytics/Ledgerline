"""Convert invoice amounts to a single reporting currency for dashboard aggregates.

OCR helpers recover ISO codes or money symbols when DI omits CurrencyCode.
ISO validation uses ``pycountry`` via ``iso4217_catalog`` (no hardcoded code list).
"""

from __future__ import annotations

import contextvars
from collections import Counter, defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
from decimal import Decimal
import re

from app.services.shared.iso4217_catalog import is_iso4217_currency
from app.tenant_settings import COUNTRY_CURRENCY, DEFAULT_COUNTRY

# Platform reporting fallback when no tenant context is available.
BASE_CURRENCY = COUNTRY_CURRENCY[DEFAULT_COUNTRY]

UNKNOWN_CURRENCY = "UNKNOWN"

FxRates = Mapping[str, Decimal]

# Ambient tenant FX rates for the current report/dashboard build. Report code is
# many small helper functions several calls deep; threading an extra "rates"
# parameter through every one of them for this single cross-cutting concern would
# make each of them harder to read for no benefit — a context var scoped to the
# request/task does the job safely (each async task gets its own value, so
# concurrent requests for different tenants never cross-contaminate).
_tenant_fx_rates_var: contextvars.ContextVar[dict[str, Decimal] | None] = contextvars.ContextVar(
    "tenant_fx_rates", default=None
)


def current_tenant_fx_rates() -> dict[str, Decimal]:
    """The ambient tenant FX rates set by ``tenant_fx_rates_scope``, or ``{}``."""
    return dict(_tenant_fx_rates_var.get() or {})


@contextmanager
def tenant_fx_rates_scope(rates: FxRates | None):
    """Make ``rates`` the ambient tenant FX rates for every ``convert_to_base`` /
    ``fx_rate_to_base`` call inside this block that does not pass its own
    ``rates=`` explicitly. Wrap a report's top-level entrypoint with this once,
    right after loading the tenant's configured rates.
    """
    token = _tenant_fx_rates_var.set(dict(rates or {}))
    try:
        yield
    finally:
        _tenant_fx_rates_var.reset(token)


def prefer_currency(*values: str | None) -> str:
    """First non-blank currency token. Empty if none — never invents AUD/SGD/USD."""
    for raw in values:
        token = (raw or "").strip().upper()
        if token:
            return token[:3]
    return ""

# Symbols that map to more than one ISO code — never invent a country.
# Bare "$" is shared by USD/AUD/SGD/NZD/CAD/HKD/… — store the glyph only.
AMBIGUOUS_CURRENCY_SYMBOLS = frozenset({"$", "¥"})
# 1:1 glyph → ISO (safe to store without user confirm).
UNAMBIGUOUS_SYMBOL_TO_ISO = {
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
}

# Prefixed symbols that unambiguously imply an ISO (checked before bare ISO tokens).
_PREFIXED_SYMBOL_TO_ISO: tuple[tuple[str, str], ...] = (
    ("A$", "AUD"),
    ("AU$", "AUD"),
    ("AUD$", "AUD"),
    ("US$", "USD"),
    ("USD$", "USD"),
    ("NZ$", "NZD"),
    ("NZD$", "NZD"),
    ("C$", "CAD"),
    ("CA$", "CAD"),
    ("CAD$", "CAD"),
    ("S$", "SGD"),
    ("SG$", "SGD"),
    ("HK$", "HKD"),
    ("NT$", "TWD"),
    ("R$", "BRL"),
    ("RM", "MYR"),
)

# Local amount-adjacent abbreviations → ISO (prefix OR suffix near money).
# These appear widely on receipts when the full ISO code is never printed.
_AMOUNT_ABBR_TO_ISO: tuple[tuple[str, str], ...] = (
    ("Ks", "MMK"),  # Myanmar Kyat (58000Ks / Ks 58000)
    ("Tk", "BDT"),  # Bangladeshi Taka
    ("Rp", "IDR"),  # Indonesian Rupiah (when next to amounts)
)

# Spelled currency names — match as words anywhere (no digit adjacency required).
_CURRENCY_NAME_TO_ISO: tuple[tuple[str, str], ...] = (
    ("Kyats", "MMK"),
    ("Kyat", "MMK"),
)

# ISO 4217 codes that are also common English words — never take from prose alone.
_ENGLISH_FALSE_POSITIVE_ISO = frozenset(
    {
        "ALL",  # "FOR ALL ITEMS"
        "AND",
        "ARE",
        "CAN",
        "GET",
        "HAS",
        "HIS",
        "ITS",
        "LOW",
        "MAD",
        "MAY",
        "NEW",
        "NOR",
        "NOW",
        "OLD",
        "ONE",
        "OUR",
        "OUT",
        "OWN",
        "PAN",
        "PER",
        "SET",
        "SHE",
        "SOS",
        "TOP",
        "TRY",
        "USE",
        "WAS",
        "YOU",
    }
)

# ISO codes that are also common brand / ticker / tech tokens on invoices.
# Near-money adjacency alone is not enough (e.g. "AMD Ryzen … 53.00").
# Require an explicit currency label or a totals/currency anchor before the code.
_BRAND_TICKER_ISO = frozenset(
    {
        "AMD",  # Advanced Micro Devices vs Armenian Dram
        "PHP",  # programming language vs Philippine Peso
    }
)

# Text immediately before a brand/ticker ISO+amount must look like currency use.
_BRAND_TICKER_CURRENCY_ANCHOR = re.compile(
    r"(?is)(?:currency|ccy|curr(?:ency)?(?:\s*code)?|"
    r"amount\s+in|invoiced?\s+in|payable\s+in|"
    r"grand\s+total|total(?:\s+amount)?(?:\s+payable)?|"
    r"amount\s+(?:due|payable)|net\s+(?:amount|payable))"
    r"\s*[:#\-]?\s*$"
)

# Common currency glyphs near amounts.
_CURRENCY_GLYPHS = r"[$€£¥₹₩₪₫₱₽₴₺₦₡₵₲]"

# Explicit currency label → ISO (never invent from free-floating prose tokens).
_CURRENCY_LABEL_ISO = re.compile(
    r"(?i)\b(?:currency|curr(?:ency)?\s*code|ccy|amount\s+in|invoiced?\s+in|"
    r"payable\s+in|total\s+in)\b\s*[:#\-]?\s*"
    r"(?<![A-Za-z0-9])(?P<code>[A-Za-z]{3})(?![A-Za-z0-9])"
)

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


def _brand_ticker_currency_context(match: re.Match[str], text: str) -> bool:
    """True when text before a brand/ticker ISO looks like a currency/total label."""
    prefix = text[max(0, match.start() - 48) : match.start()]
    return _BRAND_TICKER_CURRENCY_ANCHOR.search(prefix) is not None


def _iso_near_money_hit(code: str, match: re.Match[str], text: str) -> bool:
    """Validate one ``_ISO_NEAR_MONEY`` hit for ``code`` (brand tickers need anchors)."""
    hit = (match.group("code_before") or match.group("code_after") or "").upper()
    if hit != code:
        return False
    amount = match.group("amt_before") or match.group("amt_after")
    if not is_iso4217_currency(code):
        return False
    if code in _ENGLISH_FALSE_POSITIVE_ISO:
        return False
    if not _amount_looks_like_money(amount):
        return False
    if code in _BRAND_TICKER_ISO and not _brand_ticker_currency_context(match, text):
        return False
    return True


def _prefix_hit_in_text(prefix: str, text: str) -> bool:
    """True when ``prefix`` appears as a real currency marker (not inside words).

    Letter-only prefixes like ``RM`` must not match inside ``TERMS``.
    Symbol prefixes (``US$``, ``S$``) match case-insensitively as whole tokens.
    """
    if not prefix or not text:
        return False
    escaped = re.escape(prefix)
    if any(ch in prefix for ch in "$€£¥₹"):
        return re.search(rf"(?<![A-Za-z0-9]){escaped}", text, re.I) is not None
    # Alphabetic prefixes (RM, …): token boundary + money/digit context.
    return (
        re.search(
            rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])\s*(?:{_CURRENCY_GLYPHS})?\s*\d",
            text,
            re.I,
        )
        is not None
    )


def _amount_abbr_hit_in_text(abbr: str, text: str) -> bool:
    """True when local currency abbr appears before or after an amount.

    Handles both ``Ks 58000`` and ``58000Ks`` / ``58000 Ks`` forms.
    """
    if not abbr or not text:
        return False
    escaped = re.escape(abbr)
    # Prefix form: Abbr + amount
    if re.search(
        rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])\s*(?:{_CURRENCY_GLYPHS})?\s*\d",
        text,
        re.I,
    ):
        return True
    # Suffix form: amount + Abbr (common on receipts)
    return (
        re.search(
            rf"\d(?:[\d,]*(?:\.\d{{1,4}})?)?\s*{escaped}(?![A-Za-z0-9])",
            text,
            re.I,
        )
        is not None
    )


def detect_amount_abbr_currency_in_text(text: str | None) -> str | None:
    """Return ISO from local amount-adjacent abbreviations (Ks, Tk, Rp, …)."""
    if not text:
        return None
    for abbr, iso in sorted(_AMOUNT_ABBR_TO_ISO, key=lambda row: -len(row[0])):
        if _amount_abbr_hit_in_text(abbr, text):
            return iso
    for name, iso in sorted(_CURRENCY_NAME_TO_ISO, key=lambda row: -len(row[0])):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, re.I):
            return iso
    return None


def detect_prefixed_currency_in_text(text: str | None) -> str | None:
    """Return ISO from unambiguous prefixed symbols (S$, US$, A$, …)."""
    if not text:
        return None
    # Longer prefixes first (USD$ before US$, AUD$ before A$).
    for prefix, iso in sorted(_PREFIXED_SYMBOL_TO_ISO, key=lambda row: -len(row[0])):
        if _prefix_hit_in_text(prefix, text):
            return iso
    return None


def detect_currency_code_in_text(text: str | None) -> str | None:
    """Return the strongest ISO 4217 currency code in OCR text, if any.

    Preference:
    1. Prefixed symbols (S$ → SGD, US$ → USD)
    2. Local amount abbreviations (Ks → MMK, Tk → BDT, …)
    3. ISO codes next to money amounts (pycountry-validated)
    4. Explicit currency labels (Currency: USD) — never free-floating prose tokens
    """
    if not text:
        return None

    prefixed = detect_prefixed_currency_in_text(text)
    if prefixed:
        return prefixed

    abbr = detect_amount_abbr_currency_in_text(text)
    if abbr:
        return abbr

    near_money: Counter[str] = Counter()
    for match in _ISO_NEAR_MONEY.finditer(text):
        code = (match.group("code_before") or match.group("code_after") or "").upper()
        if not _iso_near_money_hit(code, match, text):
            continue
        near_money[code] += 1
    if near_money:
        return near_money.most_common(1)[0][0]

    label_hits: Counter[str] = Counter()
    for match in _CURRENCY_LABEL_ISO.finditer(text):
        code = (match.group("code") or "").upper()
        if not is_iso4217_currency(code):
            continue
        if code in _ENGLISH_FALSE_POSITIVE_ISO:
            continue
        label_hits[code] += 1
    if label_hits:
        return label_hits.most_common(1)[0][0]

    return None


def currency_evidence_in_text(iso: str | None, text: str | None) -> bool:
    """True when OCR/text literally supports this ISO (code, prefix, or glyph).

    Requires corroboration for *this* code: near-money (with brand-ticker
    anchors), an explicit currency label, a prefixed symbol (US$/S$), a local
    amount abbreviation (Ks/Tk/…), or an unambiguous glyph (€/£/₹). A bare
    word-bounded ISO anywhere in the document is not evidence — brand names
    like AMD processors must not corroborate Armenian Dram.
    """
    code = (iso or "").strip().upper()
    if (
        not code
        or not is_iso4217_currency(code)
        or code in _ENGLISH_FALSE_POSITIVE_ISO
        or not (text or "").strip()
    ):
        return False
    raw = text or ""

    for prefix, mapped in _PREFIXED_SYMBOL_TO_ISO:
        if mapped == code and _prefix_hit_in_text(prefix, raw):
            return True

    for abbr, mapped in _AMOUNT_ABBR_TO_ISO:
        if mapped == code and _amount_abbr_hit_in_text(abbr, raw):
            return True

    for name, mapped in _CURRENCY_NAME_TO_ISO:
        if mapped == code and re.search(
            rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", raw, re.I
        ):
            return True

    symbol = detect_currency_symbol_in_text(raw)
    if symbol and UNAMBIGUOUS_SYMBOL_TO_ISO.get(symbol) == code:
        return True

    for match in _CURRENCY_LABEL_ISO.finditer(raw):
        if (match.group("code") or "").upper() == code:
            return True

    for match in _ISO_NEAR_MONEY.finditer(raw):
        if _iso_near_money_hit(code, match, raw):
            return True

    return False


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


async def get_tenant_fx_rates(db: object, tenant_id: object) -> dict[str, Decimal]:
    """This tenant's own configured FX rates (ISO code -> rate to their books currency).

    Sourced from ``RuleBookConfigPayload.fx_rate_settings`` (tenant-owned, editable
    in Settings) — never a platform-wide table. Returns ``{}`` when the tenant has
    not configured anything yet; callers must treat that as "not convertible yet",
    not as a zero-value amount.
    """
    from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict

    try:
        data = await load_rule_book_config_dict(db, tenant_id)
    except Exception:  # noqa: BLE001 — reporting must degrade, never fail, on config load issues
        return {}
    raw = (data or {}).get("fx_rate_settings") if isinstance(data, dict) else None
    raw_rates = raw.get("rates") if isinstance(raw, dict) else None
    if not isinstance(raw_rates, dict):
        return {}
    cleaned: dict[str, Decimal] = {}
    for code, rate in raw_rates.items():
        token = str(code or "").strip().upper()
        if not is_iso4217_currency(token):
            continue
        try:
            value = rate if isinstance(rate, Decimal) else Decimal(str(rate))
        except Exception:  # noqa: BLE001 — malformed stored rate, skip it
            continue
        if value > 0:
            cleaned[token] = value
    return cleaned


def fx_rate_to_base(
    currency: str | None,
    *,
    base: str | None = None,
    rates: FxRates | None = None,
) -> Decimal | None:
    """Rate to convert one unit of ``currency`` into ``base``, or ``None`` if unknown.

    ``rates`` must be the calling tenant's own configured FX rates (see
    ``get_tenant_fx_rates`` / ``FxRateSettings``), expressed as "1 unit of code =
    how many units of ``base``". There is no platform-wide hardcoded rate table —
    an unconfigured pair returns ``None`` so callers can exclude and flag it
    instead of silently folding it into a total as if it were worth zero.
    """
    target = (base or BASE_CURRENCY).upper()
    code = _normalize_currency_code(currency)
    if code is None:
        return None
    if code == target:
        return Decimal("1")
    effective_rates = rates if rates is not None else current_tenant_fx_rates()
    if not effective_rates:
        return None
    rate = effective_rates.get(code)
    if rate is None or rate <= 0:
        return None
    return rate


def convert_to_base(
    amount: Decimal | None,
    currency: str | None,
    *,
    base: str | None = None,
    rates: FxRates | None = None,
) -> Decimal:
    """Best-effort conversion using the tenant's own ``rates``; ``0`` when unconvertible
    (no configured rate for this currency). Use ``convert_to_base_checked`` when the
    caller needs to tell "really zero" apart from "not converted yet".
    """
    amount_value, _converted = convert_to_base_checked(amount, currency, base=base, rates=rates)
    return amount_value


def convert_to_base_checked(
    amount: Decimal | None,
    currency: str | None,
    *,
    base: str | None = None,
    rates: FxRates | None = None,
) -> tuple[Decimal, bool]:
    """Like ``convert_to_base`` but also reports whether a real tenant rate was used.

    Returns ``(converted_amount, was_converted)``. ``was_converted`` is ``False``
    when the amount could not be converted (missing/unconfigured currency) — the
    caller should surface that instead of silently summing it as zero.
    """
    if amount is None:
        return Decimal("0"), True
    rate = fx_rate_to_base(currency, base=base, rates=rates)
    if rate is None:
        return Decimal("0"), False
    return amount * rate, True


def sum_amounts_by_currency(
    rows: list[tuple[str | None, Decimal | None]],
    *,
    base: str | None = None,
    rates: FxRates | None = None,
) -> tuple[Decimal, dict[str, Decimal]]:
    """Return (total in base currency, raw totals grouped by currency code).

    Rows with missing currency are bucketed under ``UNKNOWN`` and excluded from
    ``total_base``. Rows in a currency the tenant has not configured an FX rate
    for are still grouped correctly under their own code in ``by_currency`` (so
    nothing is lost), but likewise excluded from ``total_base`` rather than
    guessed at — pass this tenant's ``rates`` (``get_tenant_fx_rates``) to convert
    everything they have actually configured.
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
        total_base += convert_to_base(amount, code, base=target, rates=rates)
    return total_base, dict(by_currency)
