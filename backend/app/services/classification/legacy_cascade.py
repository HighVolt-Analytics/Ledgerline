"""v3 single-table cascade — permanent backstop after v4 category rules (architecture §9.5)."""

from __future__ import annotations

import fnmatch

from app.models.invoice import Invoice
from app.schemas.rule_book_config import LegacyCascadeConfig

_LEGACY_RULE_TYPE = "Legacy cascade"
_DEFAULT_ORDER = ("po_code", "doc_code", "vendor", "keyword")


def _norm(value: str | None) -> str:
    return (value or "").strip()


def _line_text(invoice: Invoice) -> str:
    parts: list[str] = []
    if invoice.vendor:
        parts.append(invoice.vendor)
    if invoice.invoice_no:
        parts.append(invoice.invoice_no)
    if invoice.po_reference:
        parts.append(invoice.po_reference)
    for line in invoice.line_items:
        if line.description:
            parts.append(line.description)
    return " ".join(parts)


def _match_po_code(invoice: Invoice, config: LegacyCascadeConfig) -> tuple[str, str] | None:
    po = _norm(invoice.po_reference)
    if not po:
        return None
    po_upper = po.upper()
    for code, account in config.po_codes.items():
        key = code.strip()
        if not key:
            continue
        if po_upper == key.upper() or po_upper.startswith(key.upper()):
            return account, f"Legacy PO code: {key}"
    return None


def _match_doc_code(invoice: Invoice, config: LegacyCascadeConfig) -> tuple[str, str] | None:
    doc_no = _norm(invoice.invoice_no)
    if not doc_no:
        return None
    for entry in config.doc_codes:
        pattern = entry.pattern.strip()
        if not pattern:
            continue
        if fnmatch.fnmatchcase(doc_no.upper(), pattern.upper()):
            return entry.account, f"Legacy doc code: {entry.id or pattern}"
    return None


def _match_vendor(invoice: Invoice, config: LegacyCascadeConfig) -> tuple[str, str] | None:
    vendor = _norm(invoice.vendor)
    if not vendor:
        return None
    vendor_lower = vendor.lower()
    for name, account in config.vendors.items():
        key = name.strip()
        if not key:
            continue
        if vendor_lower == key.lower():
            return account, f"Legacy vendor: {key}"
    return None


def _match_keyword(invoice: Invoice, config: LegacyCascadeConfig) -> tuple[str, str] | None:
    haystack = _line_text(invoice)
    if not haystack:
        return None
    haystack_lower = haystack.lower()
    # Longer keywords first so "Google Ads" wins over "Google".
    for keyword, account in sorted(config.keywords.items(), key=lambda kv: -len(kv[0])):
        key = keyword.strip()
        if not key:
            continue
        if key.lower() in haystack_lower:
            return account, f"Legacy keyword: {key}"
    return None


_STEP_HANDLERS = {
    "po_code": _match_po_code,
    "doc_code": _match_doc_code,
    "vendor": _match_vendor,
    "keyword": _match_keyword,
}


def match_legacy_cascade(
    invoice: Invoice,
    config: LegacyCascadeConfig,
) -> tuple[str, str] | None:
    """Return (ledger category, match_reason) when a legacy step matches."""
    if not config.enabled:
        return None
    if not any(
        (
            config.po_codes,
            config.doc_codes,
            config.vendors,
            config.keywords,
        )
    ):
        return None

    order = config.priority_order or list(_DEFAULT_ORDER)
    for step in order:
        handler = _STEP_HANDLERS.get(step)
        if handler is None:
            continue
        hit = handler(invoice, config)
        if hit:
            return hit
    return None


def legacy_rule_type() -> str:
    return _LEGACY_RULE_TYPE
