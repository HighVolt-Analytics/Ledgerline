"""Invoice number cleanup and tight OCR extraction."""

from __future__ import annotations

import re
from datetime import date

_DATE_BLEED_IN_INVOICE_NO = re.compile(
    r"(?:,\s*)?(?:DATED?|DATE)\s*[:\s]*(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})",
    re.I,
)
_INVOICE_NO_BLEED = re.compile(
    r"\s*,\s*(?:DATED?|DATE)\b.*$|\s+\bDATED?\b.*$|\s+\bOF\s+THE\b.*$",
    re.I,
)
_INVOICE_NO_TIGHT = re.compile(
    r"(?:Invoice\s*(?:No\.?|Number|#)|Inv(?:oice)?\s*#|Invoice\s*ID|"
    r"Proforma\s+Invoice\s*No\.?|PROFORMA\s+INVOICE\s*NO)\s*[:\s#]*"
    r"([A-Z0-9][A-Z0-9\-/_]{2,})",
    re.I,
)
_PROFORMA_REF = re.compile(
    r"PROFORMA\s+INVOICE\s*NO\s*:\s*([A-Z0-9][A-Z0-9\-/_]{2,})",
    re.I,
)


def is_plausible_invoice_no(value: str | None) -> bool:
    if not value or len(value.strip()) < 3:
        return False
    token = value.strip().lower()
    if token in {"level", "date", "total", "invoice", "number", "no"}:
        return False
    if _INVOICE_NO_BLEED.search(value):
        return False
    if not re.search(r"\d", value) and len(value) < 6:
        return False
    return True


def sanitize_invoice_no(value: str | None) -> str | None:
    """Trim label bleed (DATED, OF THE, comma+date) from invoice numbers."""
    if not value:
        return None
    token = str(value).strip()
    if not token:
        return None
    trimmed = _INVOICE_NO_BLEED.sub("", token).strip(" ,;/-")
    if not trimmed:
        return None
    if len(trimmed) > 48:
        parts = re.split(r"[\s,;]+", trimmed)
        trimmed = parts[0] if parts else trimmed[:48]
    return trimmed if is_plausible_invoice_no(trimmed) else None


def extract_invoice_no_from_text(text: str) -> str | None:
    """Tight regex extraction for invoice / proforma numbers."""
    if not text or not text.strip():
        return None
    for pattern in (_PROFORMA_REF, _INVOICE_NO_TIGHT):
        match = pattern.search(text)
        if match:
            candidate = sanitize_invoice_no(match.group(1))
            if candidate:
                return candidate
    return None


def invoice_no_has_label_bleed(value: str | None) -> bool:
    """True when value still contains DATED/DATE/OF THE label bleed."""
    if not value or not str(value).strip():
        return False
    return bool(_INVOICE_NO_BLEED.search(str(value).strip()))


def extract_date_from_invoice_no_bleed(value: str | None) -> date | None:
    """Parse invoice date embedded after DATED:/DATE in a combined invoice-no line."""
    if not value or not str(value).strip():
        return None
    match = _DATE_BLEED_IN_INVOICE_NO.search(str(value).strip())
    if not match:
        return None
    from app.services.shared.flexible_date import parse_flexible_date

    return parse_flexible_date(match.group(1))


def split_invoice_no_and_date(value: str | None) -> tuple[str | None, date | None]:
    """Return sanitized invoice number and optional date parsed from label bleed."""
    if not value or not str(value).strip():
        return None, None
    token = str(value).strip()
    bleed_date = extract_date_from_invoice_no_bleed(token)
    clean = sanitize_invoice_no(token)
    return clean, bleed_date
