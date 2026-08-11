"""Field validators and normalizers for contract-driven resolution."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.extraction.field_contracts import FieldType
from app.utils.abn_validator import storage_abn


def normalize_amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        from app.services.shared.amount_sanity import plausible_money

        try:
            return plausible_money(value if isinstance(value, Decimal) else Decimal(str(value)))
        except (InvalidOperation, ValueError, TypeError):
            return None
    if isinstance(value, dict):
        for key in ("value", "amount", "total", "text", "content"):
            if key in value:
                return normalize_amount(value.get(key))
        return None
    from app.services.shared.amount_sanity import plausible_money
    from app.services.shared.locale_number_parser import parse_localized_decimal

    parsed = parse_localized_decimal(str(value).strip())
    return plausible_money(parsed) if parsed is not None else None


def normalize_date(value: Any, *, date_order: str = "DMY") -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    if isinstance(value, dict):
        for key in ("value", "date", "text", "content"):
            if key in value:
                return normalize_date(value.get(key), date_order=date_order)
        return None
    from app.services.shared.flexible_date import parse_flexible_date

    order = date_order if date_order in {"DMY", "MDY", "YMD"} else "DMY"
    return parse_flexible_date(str(value).strip() or None, date_order=order)  # type: ignore[arg-type]


def normalize_currency(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("value", "code", "currency", "text", "content"):
            if key in value:
                return normalize_currency(value.get(key))
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Ambiguous symbols must not invent an ISO code ($ → USD/AUD/SGD…, ¥ → JPY/CNY).
    import re

    from app.services.shared.currency import (
        AMBIGUOUS_CURRENCY_SYMBOLS,
        _ENGLISH_FALSE_POSITIVE_ISO,
        detect_prefixed_currency_in_text,
    )
    from app.services.shared.iso4217_catalog import is_iso4217_currency

    if raw in AMBIGUOUS_CURRENCY_SYMBOLS:
        return None

    def _acceptable_iso(code: str) -> bool:
        # Prose-word ISO codes are never a valid bare currency field value.
        return is_iso4217_currency(code) and code not in _ENGLISH_FALSE_POSITIVE_ISO

    # Unambiguous symbols → ISO (never bare "$")
    symbol_map = {"£": "GBP", "€": "EUR", "₹": "INR"}
    if raw in symbol_map:
        return symbol_map[raw]

    # Prefixed forms on short tokens (US$, S$ 100) — never scan long prose.
    if len(raw) <= 24:
        prefixed = detect_prefixed_currency_in_text(raw)
        if prefixed:
            return prefixed

    token = raw.upper().strip()
    # Exact ISO code
    if len(token) == 3 and _acceptable_iso(token):
        return token

    # Leading ISO: "AUD 100.00" / "USD$" / "EUR€"
    leading = re.match(r"^(?P<code>[A-Z]{3})(?:\s|[$€£¥₹]|$)", token)
    if leading:
        code = leading.group("code")
        if _acceptable_iso(code):
            return code

    # Trailing ISO: "100.00 AUD" / "$100 AUD"
    trailing = re.search(r"(?:^|[\s$])(?P<code>[A-Z]{3})$", token)
    if trailing:
        code = trailing.group("code")
        if _acceptable_iso(code):
            return code

    return None


def normalize_abn(value: Any) -> str | None:
    if value is None:
        return None
    return storage_abn(str(value).strip() or None)


def normalize_invoice_no(value: Any) -> str | None:
    if value is None:
        return None
    from app.services.extraction.invoice_no_sanitizer import sanitize_invoice_no_parts

    cleaned, _secondary = sanitize_invoice_no_parts(str(value).strip())
    return cleaned or None


def normalize_party_name(value: Any) -> str | None:
    if value is None:
        return None
    from app.services.master_data.vendor_name_utils import normalize_vendor_name

    token = str(value).strip()
    if not token:
        return None
    return normalize_vendor_name(token) or token


def normalize_string(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def normalize_field_value(field_type: FieldType | str, value: Any) -> Any:
    kind = FieldType(str(field_type)) if not isinstance(field_type, FieldType) else field_type
    if kind == FieldType.AMOUNT:
        return normalize_amount(value)
    if kind == FieldType.DATE:
        return normalize_date(value)
    if kind == FieldType.CURRENCY:
        return normalize_currency(value) or ""
    if kind == FieldType.IDENTIFIER:
        # Prefer invoice_no sanitizer for generic identifiers; ABN handled by key elsewhere
        return normalize_string(value)
    if kind == FieldType.PARTY:
        return normalize_party_name(value)
    if kind == FieldType.LINE_ITEMS:
        return value
    return normalize_string(value)


def validate_normalized(
    field_type: FieldType | str,
    value: Any,
    *,
    key: str = "",
) -> tuple[bool, str | None]:
    """Return (ok, reason). Empty/null is ok at this stage (treated as missing upstream)."""
    if value is None or value == "":
        return True, None
    kind = FieldType(str(field_type)) if not isinstance(field_type, FieldType) else field_type
    if kind == FieldType.AMOUNT and not isinstance(value, Decimal):
        return False, "invalid_amount"
    if kind == FieldType.DATE and not isinstance(value, date):
        return False, "invalid_date"
    if kind == FieldType.CURRENCY:
        token = str(value).strip().upper()
        if token and (len(token) != 3 or not token.isalpha()):
            return False, "invalid_currency"
    if key == "abn" or key.endswith("_abn"):
        digits = "".join(c for c in str(value) if c.isdigit())
        if digits and len(digits) < 8:
            return False, "invalid_tax_id"
    if kind == FieldType.LINE_ITEMS:
        if not isinstance(value, list):
            return False, "invalid_line_items"
    return True, None
