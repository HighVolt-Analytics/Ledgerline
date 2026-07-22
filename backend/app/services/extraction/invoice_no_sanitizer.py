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
    r"|\s+(?:Invoice\s+Date|GSTIN|ABN|ACN|PAN|PO|Bill\s+To|Ship\s+To|Page|GST|Total|"
    r"Customer(?:\s*(?:PO|P/?N))?|Incoterm(?:s)?|Packing\s*List)\b.*$",
    re.I,
)
_LEADING_LABEL = re.compile(
    r"^(?:(?:tax\s+)?invoice\s*(?:no\.?|number|#)|inv\.?\s*(?:no\.?|number|#))"
    r"\s*[:#.\-\s]+",
    re.I,
)
# Label only — capture handled by look-ahead so adjacent column headers are skipped.
_INVOICE_NO_LABEL = re.compile(
    r"(?:(?<!Proforma\s)(?<!PROFORMA\s)Invoice\s*(?:No\.?|Number|#)|"
    r"Inv\.?\s*(?:No\.?|Number|#)|"
    r"Inv\.?\s*#|Invoice\s*ID|"
    r"INV\s*NO)\s*[:\s#]*",
    re.I,
)
# Kept for callers / tests that still expect a capturing form; prefer label + look-ahead.
_INVOICE_NO_TIGHT = re.compile(
    r"(?:(?<!Proforma\s)(?<!PROFORMA\s)Invoice\s*(?:No\.?|Number|#)|"
    r"Inv\.?\s*(?:No\.?|Number|#)|"
    r"Inv\.?\s*#|Invoice\s*ID|"
    r"INV\s*NO)\s*[:\s#]*"
    r"#?"
    r"([A-Z0-9][A-Z0-9\-/_]{2,})",
    re.I,
)
_CANDIDATE_TOKEN = re.compile(r"#?([A-Z0-9][A-Z0-9\-/_]{2,})", re.I)
# Packing-list / form headers glued right after "Invoice No." in reading order.
_ADJACENT_COLUMN_HEADER = re.compile(
    r"^(?:"
    r"Customer(?:\s*(?:PO|P/?N(?:\s*\(ASIN\))?|Part(?:\s*No\.?)?|No\.?|Number|#))?|"
    r"Packing\s*List\s*(?:No\.?|Number|#)?|"
    r"Incoterm(?:s)?|"
    r"Order\s*(?:No\.?|Number|#)?|"
    r"Date|"
    r"Bill\s*To|Ship\s*To"
    r")\b\s*",
    re.I,
)
_PO_LIKE_TOKEN = re.compile(r"^PO[-_]?\d", re.I)
_PACKING_LIST_NO_LABELED = re.compile(
    r"Packing\s*List\s*(?:No\.?|Number|#)?[ \t]*[:#=]?[ \t]*"
    r"([A-Z0-9][A-Z0-9\-/_]{2,})",
    re.I,
)
_CUSTOMER_PO_LABELED = re.compile(
    r"Customer\s*PO[ \t]*[:#=]?[ \t]*([A-Z0-9][A-Z0-9\-/_]{2,})",
    re.I,
)
_HEADER_CELL = re.compile(
    r"(?i)(?:"
    r"Date|Packing\s*List\s*(?:No\.?|Number|#)?|"
    r"Invoice\s*(?:No\.?|Number|#)|Inv\.?\s*(?:No\.?|Number|#)|"
    r"Customer(?:\s*(?:PO|P/?N))?|Incoterm(?:s)?|Order\s*(?:No\.?|Number|#)?"
    r")"
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
        # Adjacent form / packing-list column headers (never invoice numbers).
        "customer",
        "buyer",
        "seller",
        "shipper",
        "consignee",
        "address",
        "incoterm",
        "incoterms",
        "packing",
        "list",
        "order",
        "origin",
        "brand",
        "remark",
        "remarks",
        "description",
        "qty",
        "quantity",
        "unit",
        "price",
        "vendor",
        "supplier",
        "ship",
        "bill",
        "to",
        "from",
        "attn",
        "attention",
        "tel",
        "phone",
        "fax",
        "email",
        "po",
        "asin",
    }
)
_MAX_TOKEN_LEN = 64
_LOOKAHEAD_CHARS = 240


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


def _strip_leading_junk_tokens(token: str) -> str:
    """Drop leading form labels (Customer / Date / …) before the real ID."""
    # Split on whitespace only — never commas (money like 1,234.56).
    parts = re.split(r"\s+", token.strip())
    while parts:
        head = parts[0].strip(" .:/-#").lower()
        if head in _JUNK_WORDS or _ADJACENT_COLUMN_HEADER.match(parts[0]):
            parts = parts[1:]
            continue
        break
    return " ".join(parts).strip() if parts else ""


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
    token = _strip_leading_junk_tokens(token)
    if len(token) > _MAX_TOKEN_LEN and re.search(r"[\s,;]", token):
        parts = re.split(r"[\s,;]+", token)
        # Prefer the first plausible fragment (skip leftover label words).
        for part in parts:
            cleaned = part.strip(" .,;:/#")
            if is_plausible_invoice_no(cleaned):
                return cleaned
        token = parts[0] if parts else token[:_MAX_TOKEN_LEN]
    return token.strip(" .,;:/#")


def is_plausible_invoice_no(value: str | None) -> bool:
    if not value or len(value.strip()) < 3:
        return False
    token = value.strip()
    lowered = token.lower()
    if lowered in _JUNK_WORDS:
        return False
    # Multi-word blobs that start with a form label are never invoice numbers.
    first = re.split(r"[\s,;|]+", lowered, maxsplit=1)[0].strip(" .:/-#")
    if first in _JUNK_WORDS:
        return False
    if _ADJACENT_COLUMN_HEADER.match(token):
        return False
    if _INVOICE_NO_BLEED.search(token):
        return False
    if _DATE_ONLY.match(token):
        return False
    if _MONEY_ONLY.match(token):
        return False
    if _GSTIN_ONLY.match(token):
        return False
    # Real invoice / packing-list cross-refs always carry at least one digit.
    if not re.search(r"\d", token):
        return False
    return True


def _excluded_cross_ref_tokens(text: str) -> set[str]:
    """Values clearly labeled as Packing List No / Customer PO — not invoice_no."""
    out: set[str] = set()
    for pattern in (_PACKING_LIST_NO_LABELED, _CUSTOMER_PO_LABELED):
        for match in pattern.finditer(text or ""):
            token = match.group(1).strip().upper()
            if token:
                out.add(token)
    return out


def _table_invoice_no_from_header_row(text: str, label_match: re.Match[str]) -> str | None:
    """When Invoice No sits in a header row, take the aligned value on the next line."""
    line_start = text.rfind("\n", 0, label_match.start()) + 1
    line_end = text.find("\n", label_match.end())
    header_line = text[line_start : line_end if line_end >= 0 else len(text)]
    cells = [m.group(0) for m in _HEADER_CELL.finditer(header_line)]
    if len(cells) < 2:
        return None
    inv_idx = None
    for i, cell in enumerate(cells):
        if re.search(r"(?i)invoice\s*(?:no|number|#)|inv\.?\s*(?:no|number|#)", cell):
            inv_idx = i
            break
    if inv_idx is None:
        return None
    if line_end < 0:
        return None
    next_end = text.find("\n", line_end + 1)
    value_line = text[line_end + 1 : next_end if next_end >= 0 else len(text)].strip()
    if not value_line or not re.search(r"\d", value_line):
        return None
    values = [m.group(1) for m in _CANDIDATE_TOKEN.finditer(value_line)]
    # Also split on whitespace for tokens like "EXW Hong Kong" — keep ID-like only.
    if inv_idx >= len(values):
        return None
    return sanitize_invoice_no(values[inv_idx])


def _first_plausible_token_after(
    text: str,
    *,
    exclude: set[str] | None = None,
) -> str | None:
    """Scan look-ahead window for the first plausible invoice-no token."""
    window = (text or "")[:_LOOKAHEAD_CHARS]
    window = _ADJACENT_COLUMN_HEADER.sub("", window, count=1).lstrip(" :.\t|-")
    # Repeated adjacent headers (Invoice No. Customer PO Incoterm …).
    for _ in range(4):
        stripped = _ADJACENT_COLUMN_HEADER.sub("", window, count=1)
        if stripped == window:
            break
        window = stripped.lstrip(" :.\t|-")

    lines = window.splitlines() or [window]
    # Header residue with no digits → jump to the next line (table value row).
    if lines and not re.search(r"\d", lines[0]):
        window = "\n".join(lines[1:]) if len(lines) > 1 else window

    exclude_u = {e.upper() for e in (exclude or set())}
    for match in _CANDIDATE_TOKEN.finditer(window):
        raw_tok = match.group(1)
        if raw_tok.upper() in exclude_u:
            continue
        if _PO_LIKE_TOKEN.match(raw_tok):
            continue
        candidate = sanitize_invoice_no(raw_tok)
        if candidate:
            return candidate
    return None


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
    """Only Invoice No / INV NO / proforma-labeled tokens — never Permit/Doc No.

    Skips adjacent packing-list column headers (Customer PO, Incoterm, …) that OCR
    often places immediately after the Invoice No label in reading order.
    """
    if not text or not text.strip():
        return None
    exclude = _excluded_cross_ref_tokens(text)
    for match in _INVOICE_NO_LABEL.finditer(text):
        prefix = text[max(0, match.start() - 16) : match.start()]
        if re.search(r"proforma\s*$", prefix, re.I):
            continue
        table_candidate = _table_invoice_no_from_header_row(text, match)
        if table_candidate and table_candidate.upper() not in exclude:
            return table_candidate
        candidate = _first_plausible_token_after(text[match.end() :], exclude=exclude)
        if candidate:
            return candidate
    # Legacy capturing form as a secondary pass (already-sane layouts).
    for match in _INVOICE_NO_TIGHT.finditer(text):
        prefix = text[max(0, match.start() - 16) : match.start()]
        if re.search(r"proforma\s*$", prefix, re.I):
            continue
        candidate = sanitize_invoice_no(match.group(1))
        if candidate and candidate.upper() not in exclude:
            return candidate
        candidate = _first_plausible_token_after(text[match.end() :], exclude=exclude)
        if candidate:
            return candidate
    match = _PROFORMA_REF.search(text)
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
