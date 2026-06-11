"""Heuristics for rejecting bad vendor strings from OCR / Document Intelligence."""

from __future__ import annotations

import re

_DOC_TITLE_LINE = re.compile(
    r"^(?:purchase\s+order|goods\s+receipt(?:\s+note)?|tax\s+invoice|invoice|credit\s+note)\s*$",
    re.I,
)

_VENDOR_REJECT_RE = re.compile(
    r"payment\s+terms|please\s+reference|gst\s+is\s+charged|net\s+\d+\s+days|"
    r"amount\s+due|total\s+due|bank\s+details|remit\s+to|thank\s+you|"
    r"invoice\s+number\s+with\s+payment",
    re.I,
)

_HEADER_VENDOR_STOP = re.compile(
    r"^(?:TAX\s+INVOICE|INVOICE|BILL\s+TO|SHIP\s+TO|ABN\b|PURCHASE\s+ORDER|"
    r"GOODS\s+RECEIPT|DESCRIPTION\b|CURRENCY\b)",
    re.I,
)

_ADDRESSish_LINE = re.compile(
    r"^\d+\s+\w+|(?:\broad\b|\bstreet\b|\bavenue\b|\bdrive\b|\bnsw\b|\bvic\b|\bqld\b).*\d{4}\b",
    re.I,
)


def is_plausible_vendor_name(value: str | None) -> bool:
    """Reject payment footers and other non-vendor strings from OCR/DI."""
    if not value or not str(value).strip():
        return False
    text = re.sub(r"\s+", " ", str(value).strip())
    if len(text) < 3 or len(text) > 80:
        return False
    if _VENDOR_REJECT_RE.search(text):
        return False
    lower = text.lower()
    if lower.startswith(("invoice date", "due date", "abn:", "abn ")):
        return False
    if text.count(".") >= 1 and len(text) > 55:
        return False
    if len(text.split()) > 10:
        return False
    return True


def normalize_vendor_name(value: str | None) -> str | None:
    if not is_plausible_vendor_name(value):
        return None
    return re.sub(r"\s+", " ", str(value).strip())


def strip_doc_title_from_line(line: str) -> str:
    return re.sub(
        r"\s+(?:TAX\s+INVOICE|INVOICE|PURCHASE\s+ORDER|GOODS\s+RECEIPT(?:\s+NOTE)?)\s*$",
        "",
        line.strip(),
        flags=re.I,
    ).strip()


def extract_header_vendor(text: str) -> str | None:
    """First plausible supplier line before bill-to / tax invoice blocks."""
    for line in text.splitlines()[:25]:
        candidate = strip_doc_title_from_line(line)
        if not candidate:
            continue
        if _HEADER_VENDOR_STOP.match(candidate):
            break
        if _DOC_TITLE_LINE.match(candidate):
            continue
        if _ADDRESSish_LINE.search(candidate) and re.search(r"\d", candidate):
            continue
        normalized = normalize_vendor_name(candidate)
        if normalized:
            return normalized
    return None


def pick_best_vendor_name(*candidates: str | None) -> str | None:
    for candidate in candidates:
        normalized = normalize_vendor_name(candidate)
        if normalized:
            return normalized
    return None
