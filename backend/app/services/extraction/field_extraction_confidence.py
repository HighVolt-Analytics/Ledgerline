"""Per-field OCR / parse confidence for invoice drawer UI."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from app.models.invoice import Invoice
from app.services.invoice.invoice_data import InvoiceData, invoice_data_from_invoice
from app.services.extraction.pdf_parser import _invoice_no_sane
from app.services.master_data.vendor_name_utils import is_plausible_vendor_name

_VALIDATION_RULE_FIELDS: dict[str, tuple[str, ...]] = {
    "VR01": ("subtotal", "gst", "total"),
    "VR02": ("invoice_no",),
    "VR05": ("abn",),
    "VR06": ("invoice_date", "due_date"),
    "VR07": ("currency",),
    "VR08": ("subtotal", "gst", "gst_rate", "total"),
    "VR09": ("line_items",),
    "VR11": ("invoice_date",),
    "VR12": ("vendor",),
    "VR14": ("po_reference",),
    "VR15": ("po_reference",),
}

_OPTIONAL_WHEN_EMPTY = frozenset(
    {
        "po_reference",
        "cost_centre",
        "bank_details",
        "document_text",
        "billing_address",
        "email_subject",
        "account_code",
        "account_name",
    }
)

_PO_REF_RE = re.compile(r"\bPO[-\s]?\d", re.I)


def _parse_validation(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return payload if isinstance(payload, list) else []


def _vr03_missing_fields(message: str) -> list[str]:
    marker = "Missing:"
    idx = message.find(marker)
    if idx < 0:
        return []
    return [part.strip() for part in message[idx + len(marker) :].split(",") if part.strip()]


def _vr03_applies_to_field(token: str, field_key: str) -> bool:
    if token == field_key:
        return True
    return field_key == "line_items" and token.startswith("line_items")


def _validation_failed_for_field(results: list[dict[str, Any]], field_key: str) -> bool:
    for row in results:
        if row.get("skipped") or row.get("passed"):
            continue
        rule = str(row.get("rule") or "")
        message = str(row.get("message") or "")
        if rule == "VR03":
            if any(_vr03_applies_to_field(token, field_key) for token in _vr03_missing_fields(message)):
                return True
            continue
        fields = _VALIDATION_RULE_FIELDS.get(rule)
        if fields and field_key in fields:
            return True
    return False


def _amounts_consistent(data: InvoiceData) -> bool:
    if data.subtotal is None or data.gst is None or data.total is None:
        return True
    expected = data.subtotal + data.gst
    return abs(data.total - expected) <= Decimal("0.05")


def _empty_score(field_key: str) -> float:
    if field_key == "attachment_name":
        return 28.0
    if field_key in _OPTIONAL_WHEN_EMPTY:
        return 52.0
    return 18.0


def _apply_validation_penalty(score: float, failed: bool) -> float:
    if not failed:
        return score
    return max(22.0, score - 30.0)


def _score_vendor(data: InvoiceData) -> float:
    if not (data.vendor or "").strip():
        return _empty_score("vendor")
    if is_plausible_vendor_name(data.vendor):
        return 92.0
    return 58.0


def _score_abn(data: InvoiceData) -> float:
    digits = "".join(c for c in (data.abn or "") if c.isdigit())
    if len(digits) >= 11:
        return 93.0
    if digits:
        return 64.0
    return _empty_score("abn")


def _score_invoice_no(data: InvoiceData) -> float:
    if not (data.invoice_no or "").strip():
        return _empty_score("invoice_no")
    if _invoice_no_sane(data.invoice_no):
        return 94.0
    return 62.0


def _score_date(value) -> float:
    return 91.0 if value is not None else _empty_score("invoice_date")


def _score_po_reference(data: InvoiceData) -> float:
    ref = (data.po_reference or "").strip()
    if not ref:
        return _empty_score("po_reference")
    if _PO_REF_RE.search(ref):
        return 93.0
    return 82.0


def _score_money(value: Decimal | None, *, field_key: str, data: InvoiceData) -> float:
    if value is None:
        return _empty_score(field_key)
    if field_key == "total" and not _amounts_consistent(data):
        return 54.0
    return 93.0 if _amounts_consistent(data) else 86.0


def _score_line_items(data: InvoiceData) -> float:
    items = data.line_items
    if not items:
        return _empty_score("line_items")
    row_scores: list[float] = []
    for line in items:
        has_desc = bool((line.description or "").strip())
        has_amount = line.amount is not None or line.unit_price is not None
        if has_desc and has_amount:
            row_scores.append(94.0)
        elif has_desc:
            row_scores.append(74.0)
        else:
            row_scores.append(56.0)
    return round(sum(row_scores) / len(row_scores))


def _score_bank_details(data: InvoiceData) -> float:
    if (data.bank_bsb or "").strip() or (data.bank_account or "").strip():
        return 88.0
    return _empty_score("bank_details")


def _score_document_text(data: InvoiceData) -> float:
    text = (data.document_text or "").strip()
    if not text:
        return _empty_score("document_text")
    if len(text) >= 400:
        return 90.0
    if len(text) >= 120:
        return 82.0
    return 68.0


def _score_attachment_name(invoice: Invoice) -> float:
    if (invoice.email_attachment_name or "").strip():
        return 97.0
    return _empty_score("attachment_name")


def _score_scalar_on_invoice(invoice: Invoice, attr: str, field_key: str) -> float:
    value = getattr(invoice, attr, None)
    if value is None or str(value).strip() == "":
        return _empty_score(field_key)
    return 84.0


def _score_document_heading(data: InvoiceData, invoice: Invoice) -> float:
    heading = (data.document_heading or getattr(invoice, "document_heading", None) or "").strip()
    if heading:
        return 90.0 if len(heading) >= 4 else 72.0
    return _empty_score("document_heading")


def _base_scores(data: InvoiceData, invoice: Invoice) -> dict[str, float]:
    scores = {
        "vendor": _score_vendor(data),
        "abn": _score_abn(data),
        "invoice_no": _score_invoice_no(data),
        "invoice_date": _score_date(data.invoice_date),
        "due_date": _score_date(data.due_date),
        "po_reference": _score_po_reference(data),
        "cost_centre": _score_scalar_on_invoice(invoice, "cost_centre", "cost_centre"),
        "subtotal": _score_money(data.subtotal, field_key="subtotal", data=data),
        "gst": _score_money(data.gst, field_key="gst", data=data),
        "total": _score_money(data.total, field_key="total", data=data),
        "line_items": _score_line_items(data),
        "bank_details": _score_bank_details(data),
        "attachment_name": _score_attachment_name(invoice),
        "document_text": _score_document_text(data),
        "document_heading": _score_document_heading(data, invoice),
        "billing_address": _score_scalar_on_invoice(invoice, "billing_address", "billing_address"),
        "email_subject": _score_scalar_on_invoice(invoice, "email_subject", "email_subject"),
        "account_code": _score_scalar_on_invoice(invoice, "account_code", "account_code"),
        "account_name": _score_scalar_on_invoice(invoice, "account_name", "account_name"),
        "currency": 90.0 if (data.currency or "").strip() else _empty_score("currency"),
    }
    extracted = getattr(invoice, "extracted_fields", None) or {}
    if isinstance(extracted, dict):
        for key, value in extracted.items():
            token = str(key).strip().lower()
            if not token or token in scores:
                continue
            scores[token] = 86.0 if str(value).strip() else _empty_score(token)
    return scores


def compute_extraction_field_confidence(invoice: Invoice) -> dict[str, float]:
    """Return 0–100 extraction confidence per canonical field key."""
    data = invoice_data_from_invoice(invoice)
    validation = _parse_validation(invoice.validation_results)
    scores = _base_scores(data, invoice)
    return {
        key: round(_apply_validation_penalty(score, _validation_failed_for_field(validation, key)))
        for key, score in scores.items()
    }
