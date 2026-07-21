"""Invoice number cleanup and tight OCR extraction."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

INVOICE_NO_SECONDARY_KEY = "invoice_no_secondary"

_DATE_BLEED_IN_INVOICE_NO = re.compile(
    r"(?:,\s*)?(?:DATED?|DATE)\s*[:\s]*(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})",
    re.I,
)
_INVOICE_NO_BLEED = re.compile(
    r"\s*,\s*(?:DATED?|DATE)\b.*$"
    r"|\s+\bDATED?\b.*$"
    r"|\s+\bOF\s+THE\b.*$"
    r"|\s+(?:Invoice\s+Date|GSTIN|ABN|ACN|PAN|PO|Bill\s+To|Ship\s+To|Page|GST|Total)\b.*$",
    re.I,
)
_LEADING_LABEL = re.compile(
    r"^(?:(?:tax\s+)?invoice\s*(?:no\.?|number|#)|inv\.?\s*(?:no\.?|number|#))"
    r"\s*[:#.\-\s]+",
    re.I,
)
_INVOICE_NO_TIGHT = re.compile(
    r"(?:(?<!Proforma\s)(?<!PROFORMA\s)Invoice\s*(?:No\.?|Number|#)|"
    r"Inv\.?\s*(?:No\.?|Number|#)|"
    r"Inv\.?\s*#|Invoice\s*ID|"
    r"INV\s*NO)\s*[:\s#]*"
    r"#?"
    r"([A-Z0-9][A-Z0-9\-/_]{2,})",
    re.I,
)
_PERMIT_OR_DOC_NO = re.compile(
    r"(?:Permit\s*(?:No\.?|Number|#)|"
    r"Clearance\s*(?:No\.?|Number|#)|"
    r"Declaration\s*(?:No\.?|Number|#)|"
    r"Document\s*(?:No\.?|Number|#)|"
    r"Doc\.?\s*(?:No\.?|#))\s*[:\s#]*"
    r"([A-Z0-9][A-Z0-9\-/_]{2,})",
    re.I,
)
_PROFORMA_REF = re.compile(
    r"PROFORMA\s+INVOICE\s*NO\s*:\s*([A-Z0-9][A-Z0-9\-/_]{2,})",
    re.I,
)
_DUAL_NUMERIC = re.compile(r"^(\d{6,})/(\d{6,})$")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200d\ufeff\u00ad]")
_DATE_ONLY = re.compile(
    r"^(?:\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}-\d{2}-\d{2})$"
)
_MONEY_ONLY = re.compile(
    r"^(?:[$€£₹]|USD|AUD|EUR|GBP|INR)?\s*[\d,]+\.\d{2}$",
    re.I,
)
_GSTIN_ONLY = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]$", re.I)
_JUNK_WORDS = frozenset(
    {
        "level",
        "date",
        "total",
        "invoice",
        "number",
        "no",
        "original",
        "duplicate",
        "credit",
        "tax",
        "page",
        "amount",
    }
)
_MAX_TOKEN_LEN = 64


def _unicode_cleanup(value: str) -> str:
    token = unicodedata.normalize("NFKC", value)
    token = _ZERO_WIDTH.sub("", token)
    token = token.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    return token.strip()


def _strip_wrappers(value: str) -> str:
    token = value.strip()
    if len(token) >= 2:
        pairs = {("(", ")"), ("[", "]"), ('"', '"'), ("'", "'")}
        if (token[0], token[-1]) in pairs:
            token = token[1:-1].strip()
    return token


def _cleanup_token(value: str) -> str:
    """Contamination-only cleanup before dual split / plausibility."""
    token = _unicode_cleanup(str(value))
    if not token:
        return ""
    token = _LEADING_LABEL.sub("", token).strip()
    token = _INVOICE_NO_BLEED.sub("", token).strip()
    token = _strip_wrappers(token)
    # Strip decorative # / punctuation wrappers (printed "Invoice Number: #0001").
    token = token.strip(" .,;:/#")
    if token.startswith("#"):
        token = token.lstrip("#").strip()
    if len(token) > _MAX_TOKEN_LEN and re.search(r"[\s,;]", token):
        parts = re.split(r"[\s,;]+", token)
        token = parts[0] if parts else token[:_MAX_TOKEN_LEN]
    return token.strip(" .,;:/#")


def is_plausible_invoice_no(value: str | None) -> bool:
    if not value or len(value.strip()) < 3:
        return False
    token = value.strip()
    lowered = token.lower()
    if lowered in _JUNK_WORDS:
        return False
    if _INVOICE_NO_BLEED.search(token):
        return False
    if _DATE_ONLY.match(token):
        return False
    if _MONEY_ONLY.match(token):
        return False
    if _GSTIN_ONLY.match(token):
        return False
    if not re.search(r"\d", token) and len(token) < 6:
        return False
    return True


def _is_dual_numeric(token: str) -> tuple[str, str] | None:
    match = _DUAL_NUMERIC.match(token)
    if not match:
        return None
    left, right = match.group(1), match.group(2)
    if is_plausible_invoice_no(left) and is_plausible_invoice_no(right):
        return left, right
    return None


def sanitize_invoice_no_parts(value: str | None) -> tuple[str | None, str | None]:
    """Return (primary, secondary). Secondary set only for dual numeric slash pairs."""
    if not value:
        return None, None
    token = _cleanup_token(str(value))
    if not token:
        return None, None

    dual = _is_dual_numeric(token)
    if dual is not None:
        return dual[0], dual[1]

    if not is_plausible_invoice_no(token):
        return None, None
    return token, None


def sanitize_invoice_no(value: str | None) -> str | None:
    """Trim label bleed and return primary invoice number only."""
    primary, _secondary = sanitize_invoice_no_parts(value)
    return primary


def extract_invoice_no_from_text(text: str) -> str | None:
    """Extract invoice_no only from Invoice / INV / proforma labels.

    Never falls back to Permit No / Document No / Clearance No — those are not
    invoice numbers and belong in other_reference when needed.
    """
    return extract_commercial_invoice_no_from_text(text)


def extract_permit_or_doc_no_from_text(text: str) -> str | None:
    """Permit / Clearance / Declaration / Document No — not for invoice_no."""
    if not text or not text.strip():
        return None
    match = _PERMIT_OR_DOC_NO.search(text)
    if not match:
        return None
    return sanitize_invoice_no(match.group(1))


def extract_commercial_invoice_no_from_text(text: str) -> str | None:
    """Only Invoice No / INV NO / proforma-labeled tokens — never Permit/Doc No."""
    if not text or not text.strip():
        return None
    for pattern in (_INVOICE_NO_TIGHT, _PROFORMA_REF):
        match = pattern.search(text)
        if match:
            candidate = sanitize_invoice_no(match.group(1))
            if candidate:
                return candidate
    return None


def invoice_no_has_label_bleed(value: str | None) -> bool:
    """True when value still contains DATED/DATE/OF THE / next-field label bleed."""
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
    """Return sanitized primary invoice number and optional date from label bleed."""
    if not value or not str(value).strip():
        return None, None
    token = str(value).strip()
    bleed_date = extract_date_from_invoice_no_bleed(token)
    clean = sanitize_invoice_no(token)
    return clean, bleed_date


def split_invoice_no_parts_and_date(
    value: str | None,
) -> tuple[str | None, str | None, date | None]:
    """Return (primary, secondary, bleed_date)."""
    if not value or not str(value).strip():
        return None, None, None
    token = str(value).strip()
    bleed_date = extract_date_from_invoice_no_bleed(token)
    primary, secondary = sanitize_invoice_no_parts(token)
    return primary, secondary, bleed_date


def _parts_from_primary_secondary(
    primary: str | None,
    secondary: str | None = None,
) -> list[str]:
    """Collect cleaned primary/secondary parts, expanding legacy unsplit duals."""
    parts: list[str] = []
    seen: set[str] = set()
    for raw in (primary, secondary):
        if not raw or not str(raw).strip():
            continue
        left, right = sanitize_invoice_no_parts(str(raw))
        for part in (left, right):
            if not part:
                continue
            key = part.strip().upper()
            if key in seen:
                continue
            seen.add(key)
            parts.append(part.strip())
    return parts


def invoice_no_link_tokens_from_values(
    primary: str | None,
    secondary: str | None = None,
) -> set[str]:
    """Uppercased tokens for exact dossier/GRN/DN linking."""
    return {part.upper() for part in _parts_from_primary_secondary(primary, secondary)}


def normalize_invoice_number_token(value: str | None) -> str:
    """Strip punctuation/spaces, lowercase, collapse leading zeros in digit runs."""
    if not value:
        return ""
    cleaned = re.sub(r"[^a-z0-9]", "", str(value).strip().lower())
    cleaned = re.sub(r"(?<![0-9])0+(?=[0-9])", "", cleaned)
    return cleaned


def invoice_no_dup_tokens_from_values(
    primary: str | None,
    secondary: str | None = None,
) -> set[str]:
    """Alphanumeric-lowercased tokens for duplicate comparison.

    Includes:
    - primary normalized form (separators stripped, leading zeros collapsed)
    - digits-only core (INV2345 ↔ 2345)
    - form without a single trailing letter suffix (INV2345A ↔ INV2345 via core 2345)

    Over-match risk is mitigated by VR02 requiring the same vendor.
    """
    out: set[str] = set()
    for part in _parts_from_primary_secondary(primary, secondary):
        norm = normalize_invoice_number_token(part)
        if not norm:
            continue
        out.add(norm)
        digits = re.sub(r"[^0-9]", "", norm)
        if digits:
            out.add(digits)
        # Trailing revision letter: inv2345a → also inv2345 + 2345
        if len(norm) > 1 and norm[-1].isalpha() and any(ch.isdigit() for ch in norm[:-1]):
            stem = norm[:-1]
            if stem:
                out.add(stem)
                stem_digits = re.sub(r"[^0-9]", "", stem)
                if stem_digits:
                    out.add(stem_digits)
    return out


def _secondary_from_invoice(invoice: object) -> str | None:
    extracted = getattr(invoice, "extracted_fields", None) or {}
    if isinstance(extracted, dict):
        value = extracted.get(INVOICE_NO_SECONDARY_KEY)
        if value and str(value).strip():
            return str(value).strip()
    return None


def invoice_no_link_tokens(invoice: object) -> set[str]:
    """Primary + secondary invoice_no tokens for dossier/GRN/DN linking."""
    primary = getattr(invoice, "invoice_no", None)
    return invoice_no_link_tokens_from_values(
        str(primary) if primary else None,
        _secondary_from_invoice(invoice),
    )


def apply_invoice_no_secondary(
    extracted_fields: dict[str, str] | None,
    secondary: str | None,
) -> dict[str, str]:
    """Return extracted_fields with invoice_no_secondary set or cleared."""
    out = dict(extracted_fields or {})
    if secondary and str(secondary).strip():
        out[INVOICE_NO_SECONDARY_KEY] = str(secondary).strip()
    else:
        out.pop(INVOICE_NO_SECONDARY_KEY, None)
    return out
