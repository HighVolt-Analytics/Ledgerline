"""Invoice number cleanup and tight OCR extraction."""

from __future__ import annotations

import re

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
    trimmed = _INVOICE_NO_BLEED.sub("", token).strip(" ,;")
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
