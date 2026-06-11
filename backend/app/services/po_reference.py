"""PO reference plausibility — filters OCR junk before purchase routing."""

from __future__ import annotations

import re

_PO_PREFIX = re.compile(r"^PO[-\s#]?", re.IGNORECASE)


def is_plausible_po_reference(po: str | None) -> bool:
    """True when PO text looks like a real reference (not OCR noise like 'the')."""
    if not po or not po.strip():
        return False
    text = po.strip()
    if len(text) < 4:
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
