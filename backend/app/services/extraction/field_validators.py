"""Field validators and normalizers for contract-driven resolution."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.extraction.field_contracts import FieldType
from app.services.shared.flexible_date import parse_flexible_date
from app.utils.abn_validator import storage_abn


def normalize_amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        from app.services.shared.amount_sanity import plausible_money

        return plausible_money(Decimal(str(value).replace(",", "").replace("$", "").strip()))
    except (InvalidOperation, ValueError, TypeError):
        return None


def normalize_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    return parse_flexible_date(str(value).strip() or None)


def normalize_currency(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Ambiguous symbols must not invent an ISO code (USD vs AUD, JPY vs CNY).
    if raw in {"$", "¥"}:
        return None
    from app.services.shared.iso4217_catalog import is_iso4217_currency, iso4217_currency_codes

    # Unambiguous symbols → ISO
    symbol_map = {"£": "GBP", "€": "EUR", "₹": "INR"}
    if raw in symbol_map:
        return symbol_map[raw]
    token = raw.upper()
    if is_iso4217_currency(token):
        return token
    # "AUD 100" / "USD$" — prefer real ISO substrings from the catalog
    for code in sorted(iso4217_currency_codes(), key=len, reverse=True):
        if code in token:
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
