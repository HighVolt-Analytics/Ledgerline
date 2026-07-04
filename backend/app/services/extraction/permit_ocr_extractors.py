"""Regex helpers for clearance / permit supporting documents."""

from __future__ import annotations

import re

_PERMIT_NO = re.compile(
    r"(?i)permit\s*(?:no\.?|number|#)\s*[:\s]+([A-Z0-9][A-Z0-9\-/]{4,24})"
)
_PERMIT_NO_FALLBACK = re.compile(
    r"(?i)\b([A-Z]{1,3}\d[A-Z0-9]{6,12}[A-Z0-9]?)\b"
)
_CONSIGNMENT_REF = re.compile(
    r"(?i)(?:consignment\s*(?:ref(?:erence)?\.?|no\.?|#)|"
    r"cargo\s*ref(?:erence)?\.?|shipment\s*ref(?:erence)?\.?)"
    r"[\s:]*([A-Z0-9][A-Z0-9\-/]{3,30})"
)

_REJECT_PERMIT_TOKENS = frozenset({"PERMIT", "CLEARANCE", "NUMBER", "CARGO"})


def _valid_permit_token(token: str) -> bool:
    value = token.strip().upper()
    if len(value) < 5 or value in _REJECT_PERMIT_TOKENS:
        return False
    return any(ch.isdigit() for ch in value)


def extract_permit_fields_from_text(text: str | None) -> dict[str, str]:
    """Best-effort permit_no / consignment_ref from OCR text."""
    if not text or not str(text).strip():
        return {}
    body = str(text)
    out: dict[str, str] = {}

    match = _PERMIT_NO.search(body)
    if match:
        token = match.group(1).strip().upper()
        if _valid_permit_token(token):
            out["permit_no"] = token

    if "permit_no" not in out:
        for fallback in _PERMIT_NO_FALLBACK.finditer(body):
            token = fallback.group(1).strip().upper()
            if _valid_permit_token(token):
                out["permit_no"] = token
                break

    match = _CONSIGNMENT_REF.search(body)
    if match:
        token = match.group(1).strip().upper()
        if len(token) >= 4:
            out["consignment_ref"] = token

    return out
