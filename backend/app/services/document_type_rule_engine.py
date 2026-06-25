"""Evaluate user-defined document type classifier rules after OCR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.capture_channel import infer_capture_channel
from app.services.document_heading_utils import extract_document_heading_signals, infer_page_document_kind
from app.services.heading_kind_recognition import NON_INVOICE_NUMBER_KINDS
from app.services.document_text import cap_document_text
from app.services.invoice_data import InvoiceData
from app.services.po_reference import is_plausible_po_reference
from app.services.purchase_document_service import (
    _attachment_suggests_commercial_invoice,
    _parsed_fields_suggest_commercial_invoice,
)
from app.services.rule_engine import (
    classifier_has_actionable_conditions,
    eval_condition_group_generic,
)


@dataclass(frozen=True)
class DocumentClassifierContext:
    attachment_name: str
    email_sender: str
    email_subject: str
    vendor: str
    invoice_no: str
    po_reference: str
    line_text: str
    document_text: str
    abn: str
    capture_channel: str
    has_po_reference: str
    has_invoice_no: str
    has_total: str
    is_commercial_invoice: str
    document_heading: str
    has_heading_invoice: str
    has_heading_po: str
    has_heading_grn: str
    has_heading_credit_note: str
    has_heading_quote: str
    has_heading_contract: str


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _resolved_document_text(*, invoice: Invoice, parsed: InvoiceData) -> str:
    if parsed.document_text:
        return parsed.document_text
    if invoice.document_text:
        return invoice.document_text
    raw = parsed.raw_fields.get("document_text")
    return raw if isinstance(raw, str) else ""


def build_document_classifier_context(
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> DocumentClassifierContext:
    attachment = (invoice.email_attachment_name or "").strip()
    po = (parsed.po_reference or invoice.po_reference or "").strip()
    invoice_no = (parsed.invoice_no or invoice.invoice_no or "").strip()
    has_po = bool(po and is_plausible_po_reference(po))
    commercial = False
    if attachment and _attachment_suggests_commercial_invoice(attachment):
        commercial = True
    elif _parsed_fields_suggest_commercial_invoice(invoice):
        commercial = True

    line_text = " ".join((line.description or "") for line in parsed.line_items)
    document_text = _resolved_document_text(invoice=invoice, parsed=parsed)
    channel = infer_capture_channel(invoice.email_sender)
    heading_label = (parsed.document_heading or "").strip()
    if heading_label and heading_label.lower() not in document_text.lower():
        document_text = f"{heading_label}\n{document_text}"
    heading_signals = extract_document_heading_signals(document_text)
    if parsed.document_heading and not heading_signals.primary_label:
        heading_signals = extract_document_heading_signals(
            f"{parsed.document_heading}\n{document_text}"
        )

    primary_kind = heading_signals.primary_kind
    if primary_kind is None and parsed.document_heading:
        primary_kind = infer_page_document_kind(f"{parsed.document_heading}\n{document_text}")

    has_invoice_number = bool(invoice_no)
    if primary_kind in NON_INVOICE_NUMBER_KINDS:
        has_invoice_number = False
    elif not has_invoice_number and heading_signals.has_heading_invoice:
        has_invoice_number = True
    elif not has_invoice_number and commercial:
        has_invoice_number = True
    elif not has_invoice_number and _parsed_fields_suggest_commercial_invoice(invoice):
        has_invoice_number = True

    return DocumentClassifierContext(
        attachment_name=attachment,
        email_sender=(invoice.email_sender or "").strip(),
        email_subject=(invoice.email_subject or "").strip(),
        vendor=(parsed.vendor or invoice.vendor or "").strip(),
        invoice_no=invoice_no,
        po_reference=po,
        line_text=line_text,
        document_text=document_text,
        abn=(parsed.abn or invoice.abn or "").strip(),
        capture_channel=channel,
        has_po_reference=_bool_text(has_po),
        has_invoice_no=_bool_text(has_invoice_number),
        has_total=_bool_text(parsed.total is not None or invoice.total is not None),
        is_commercial_invoice=_bool_text(commercial),
        document_heading=(parsed.document_heading or heading_signals.primary_label or "").strip(),
        has_heading_invoice=_bool_text(heading_signals.has_heading_invoice),
        has_heading_po=_bool_text(heading_signals.has_heading_po),
        has_heading_grn=_bool_text(heading_signals.has_heading_grn),
        has_heading_credit_note=_bool_text(heading_signals.has_heading_credit_note),
        has_heading_quote=_bool_text(heading_signals.has_heading_quote),
        has_heading_contract=_bool_text(heading_signals.has_heading_contract),
    )


def _document_field(ctx: DocumentClassifierContext, field: str) -> str:
    mapping = {
        "attachment_name": ctx.attachment_name,
        "email_sender": ctx.email_sender,
        "email_subject": ctx.email_subject,
        "vendor": ctx.vendor,
        "invoice_no": ctx.invoice_no,
        "po_reference": ctx.po_reference,
        "line_text": ctx.line_text,
        "document_text": ctx.document_text,
        "abn": ctx.abn,
        "capture_channel": ctx.capture_channel,
        "has_po_reference": ctx.has_po_reference,
        "has_invoice_no": ctx.has_invoice_no,
        "has_total": ctx.has_total,
        "is_commercial_invoice": ctx.is_commercial_invoice,
        "document_heading": ctx.document_heading,
        "has_heading_invoice": ctx.has_heading_invoice,
        "has_heading_po": ctx.has_heading_po,
        "has_heading_grn": ctx.has_heading_grn,
        "has_heading_credit_note": ctx.has_heading_credit_note,
        "has_heading_quote": ctx.has_heading_quote,
        "has_heading_contract": ctx.has_heading_contract,
    }
    return mapping.get(field, "")


def _classifier_has_conditions(root: dict[str, Any]) -> bool:
    return classifier_has_actionable_conditions(root)


def list_configured_document_type_matches(
    document_types: list[DocumentTypeDefinition],
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> list[tuple[DocumentTypeDefinition, str]]:
    """All enabled classifier matches, ordered by priority (lowest first)."""
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    candidates: list[DocumentTypeDefinition] = []
    for definition in document_types:
        if not definition.enabled:
            continue
        classifier = definition.classifier
        if not classifier.enabled or not _classifier_has_conditions(classifier.root):
            continue
        candidates.append(definition)

    candidates.sort(key=lambda item: item.classifier.priority)
    matches: list[tuple[DocumentTypeDefinition, str]] = []
    for definition in candidates:
        if eval_condition_group_generic(
            definition.classifier.root,
            field_resolver=lambda field, _ctx=ctx: _document_field(_ctx, field),
        ):
            matches.append((definition, "config_classifier"))
    return matches


def match_configured_document_type(
    document_types: list[DocumentTypeDefinition],
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> tuple[DocumentTypeDefinition, str] | None:
    """First enabled classifier match by priority wins."""
    matches = list_configured_document_type_matches(
        document_types,
        invoice=invoice,
        parsed=parsed,
    )
    if not matches:
        return None
    return matches[0]
