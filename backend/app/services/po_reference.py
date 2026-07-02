"""PO reference plausibility — filters OCR junk before purchase routing."""

from __future__ import annotations

import re

_PO_PREFIX = re.compile(r"^PO[-\s#]?", re.IGNORECASE)

_PO_TEXT_PATTERNS = (
    re.compile(
        r"Purchase\s*Order\s+(?:No\.?|Number)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(
        r"Purchase\s*Order\s*(?:No\.?|Number|#)?[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(r"PO\s*Reference[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})", re.I),
    re.compile(
        r"(?:^|\n)\s*P\.?O\.?\s*(?:No\.?|Number|#)?[:\s#]+([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(
        r"\bNo\.?\s*[:\s#]+(PO[-\s][A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
)


_SO_PREFIX = re.compile(r"^SO[-\s#]?", re.IGNORECASE)


def is_plausible_po_reference(po: str | None) -> bool:
    """True when PO text looks like a real reference (not OCR noise like 'the')."""
    if not po or not po.strip():
        return False
    text = po.strip()
    if len(text) < 4:
        return False
    # Sales-order keys must not satisfy PO plausibility (common LLM conflation on AR docs).
    if _SO_PREFIX.match(text):
        return False
    if _PO_PREFIX.match(text):
        return True
    if re.search(r"\d", text):
        return True
    return False


def effective_po_reference(po: str | None) -> str | None:
    if is_plausible_po_reference(po):
        return (po or "").strip()
    return None


def extract_po_reference_from_text(text: str | None) -> str | None:
    """Best-effort PO number from OCR body (purchase-order layouts)."""
    if not text or not text.strip():
        return None
    for pattern in _PO_TEXT_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            if is_plausible_po_reference(candidate):
                return candidate
    return None
