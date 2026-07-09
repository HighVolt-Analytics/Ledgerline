"""Evaluate user-defined document type classifier rules after OCR."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.ingest.capture_channel import infer_capture_channel
from app.services.extraction.document_heading_utils import extract_document_heading_signals, infer_page_document_kind
from app.services.extraction.extraction_field_values import (
    extracted_fields_from_invoice,
    extracted_fields_from_parsed,
    merge_extracted_field_maps,
)
from app.services.classification.heading_kind_recognition import NON_INVOICE_NUMBER_KINDS
from app.services.invoice.invoice_data import InvoiceData
from app.services.purchase.po_reference import is_plausible_po_reference
from app.services.purchase.purchase_document_service import (
    _attachment_suggests_commercial_invoice,
    _parsed_fields_suggest_commercial_invoice,
)
from app.services.rule_book.rule_engine import (
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
    invoice_date: str
    due_date: str
    total: str
    subtotal: str
    gst: str
    billing_address: str
    cost_centre: str
    account_code: str
    account_name: str
    bank_details: str
    currency: str
    attachment_extension: str
    has_po_reference: str
    has_invoice_no: str
    has_total: str
    has_abn: str
    has_vendor: str
    has_invoice_date: str
    has_due_date: str
    has_subtotal: str
    has_gst: str
    has_billing_address: str
    has_bank_details: str
    has_line_items: str
    has_cost_centre: str
    is_commercial_invoice: str
    document_heading: str
    has_heading_invoice: str
    has_heading_po: str
    has_heading_so: str
    has_heading_grn: str
    has_heading_credit_note: str
    has_heading_quote: str
    has_heading_contract: str
    extracted_fields: dict[str, str] = field(default_factory=dict)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _date_text(value: date | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _attachment_extension(name: str) -> str:
    token = (name or "").strip()
    if not token or "." not in token:
        return ""
    return token.rsplit(".", 1)[-1].lower()


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
    vendor = (parsed.vendor or invoice.vendor or "").strip()
    abn = (parsed.abn or invoice.abn or "").strip()
    billing_address = (parsed.billing_address or invoice.billing_address or "").strip()
    cost_centre = (parsed.cost_centre or invoice.cost_centre or "").strip()
    account_code = (invoice.account_code or "").strip()
    account_name = (invoice.account_name or "").strip()
    bank_bsb = (parsed.bank_bsb or invoice.bank_bsb or "").strip()
    bank_account = (parsed.bank_account or invoice.bank_account or "").strip()
    bank_details = " ".join(part for part in (bank_bsb, bank_account) if part)
    invoice_date = parsed.invoice_date or invoice.invoice_date
    due_date = parsed.due_date or invoice.due_date
    subtotal = parsed.subtotal if parsed.subtotal is not None else invoice.subtotal
    gst = parsed.gst if parsed.gst is not None else invoice.gst
    total = parsed.total if parsed.total is not None else invoice.total
    currency = (parsed.currency or invoice.currency or "SGD").strip()
    extracted_fields = merge_extracted_field_maps(
        extracted_fields_from_invoice(invoice),
        extracted_fields_from_parsed(parsed),
    )

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
        vendor=vendor,
        invoice_no=invoice_no,
        po_reference=po,
        line_text=line_text,
        document_text=document_text,
        abn=abn,
        capture_channel=channel,
        invoice_date=_date_text(invoice_date),
        due_date=_date_text(due_date),
        total=_decimal_text(total),
        subtotal=_decimal_text(subtotal),
        gst=_decimal_text(gst),
        billing_address=billing_address,
        cost_centre=cost_centre,
        account_code=account_code,
        account_name=account_name,
        bank_details=bank_details,
        currency=currency,
        attachment_extension=_attachment_extension(attachment),
        has_po_reference=_bool_text(has_po),
        has_invoice_no=_bool_text(has_invoice_number),
        has_total=_bool_text(total is not None),
        has_abn=_bool_text(bool(abn)),
        has_vendor=_bool_text(bool(vendor)),
        has_invoice_date=_bool_text(invoice_date is not None),
        has_due_date=_bool_text(due_date is not None),
        has_subtotal=_bool_text(subtotal is not None),
        has_gst=_bool_text(gst is not None),
        has_billing_address=_bool_text(bool(billing_address)),
        has_bank_details=_bool_text(bool(bank_details)),
        has_line_items=_bool_text(bool(parsed.line_items)),
        has_cost_centre=_bool_text(bool(cost_centre)),
        is_commercial_invoice=_bool_text(commercial),
        document_heading=(parsed.document_heading or heading_signals.primary_label or "").strip(),
        has_heading_invoice=_bool_text(heading_signals.has_heading_invoice),
        has_heading_po=_bool_text(heading_signals.has_heading_po),
        has_heading_so=_bool_text(heading_signals.has_heading_so),
        has_heading_grn=_bool_text(heading_signals.has_heading_grn),
        has_heading_credit_note=_bool_text(heading_signals.has_heading_credit_note),
        has_heading_quote=_bool_text(heading_signals.has_heading_quote),
        has_heading_contract=_bool_text(heading_signals.has_heading_contract),
        extracted_fields=extracted_fields,
    )


def _static_document_field_mapping(ctx: DocumentClassifierContext) -> dict[str, str]:
    return {
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
        "invoice_date": ctx.invoice_date,
        "due_date": ctx.due_date,
        "total": ctx.total,
        "subtotal": ctx.subtotal,
        "gst": ctx.gst,
        "billing_address": ctx.billing_address,
        "cost_centre": ctx.cost_centre,
        "account_code": ctx.account_code,
        "account_name": ctx.account_name,
        "bank_details": ctx.bank_details,
        "currency": ctx.currency,
        "attachment_extension": ctx.attachment_extension,
        "has_po_reference": ctx.has_po_reference,
        "has_invoice_no": ctx.has_invoice_no,
        "has_total": ctx.has_total,
        "has_abn": ctx.has_abn,
        "has_vendor": ctx.has_vendor,
        "has_invoice_date": ctx.has_invoice_date,
        "has_due_date": ctx.has_due_date,
        "has_subtotal": ctx.has_subtotal,
        "has_gst": ctx.has_gst,
        "has_billing_address": ctx.has_billing_address,
        "has_bank_details": ctx.has_bank_details,
        "has_line_items": ctx.has_line_items,
        "has_cost_centre": ctx.has_cost_centre,
        "is_commercial_invoice": ctx.is_commercial_invoice,
        "document_heading": ctx.document_heading,
        "has_heading_invoice": ctx.has_heading_invoice,
        "has_heading_po": ctx.has_heading_po,
        "has_heading_so": ctx.has_heading_so,
        "has_heading_grn": ctx.has_heading_grn,
        "has_heading_credit_note": ctx.has_heading_credit_note,
        "has_heading_quote": ctx.has_heading_quote,
        "has_heading_contract": ctx.has_heading_contract,
    }


def _document_field(ctx: DocumentClassifierContext, field: str) -> str:
    key = (field or "").strip()
    if not key:
        return ""
    mapping = _static_document_field_mapping(ctx)
    if key in mapping:
        return mapping[key]
    if key.startswith("has_"):
        base = key[4:]
        if base in mapping:
            return _bool_text(bool(str(mapping[base]).strip()))
        custom_val = ctx.extracted_fields.get(base, "")
        return _bool_text(bool(str(custom_val).strip()))
    return ctx.extracted_fields.get(key, "")


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


def build_classifier_context_from_ocr(
    *,
    invoice: Invoice,
    ocr: OcrArtifact,
) -> DocumentClassifierContext:
    """Pre-extract classifier context from OCR artifact only."""
    text = (ocr.text or "").strip()
    heading = ""
    if isinstance(ocr.payload_json, dict):
        heading = str(ocr.payload_json.get("document_heading") or "").strip()
    if not heading:
        signals = extract_document_heading_signals(text)
        heading = signals.primary_label or ""
    parsed = InvoiceData(document_text=text, document_heading=heading or None)
    return build_document_classifier_context(invoice=invoice, parsed=parsed)


def _classifier_customized(defn: DocumentTypeDefinition) -> bool:
    """True when match rules differ from recognition-derived defaults."""
    mode = (defn.recognition_mode or "signals").strip().lower()
    if mode == "prompt":
        return bool((defn.llm_prompt or "").strip())

    from app.services.classification.document_type_recognition_migration import (
        sync_classifier_from_recognition,
    )

    synced = sync_classifier_from_recognition(defn)
    return defn.classifier.model_dump() != synced.classifier.model_dump()


def is_user_defined_document_type(defn: DocumentTypeDefinition) -> bool:
    """Org custom type vs shipped matrix template."""
    from app.services.classification.document_type_playbook_service import is_dt_code

    if _classifier_customized(defn):
        return True
    token = (defn.matrix_template_code or "").strip()
    if token:
        return False
    code = (defn.code or "").strip().upper()
    return not is_dt_code(code)


def classifier_rules_match_ocr(
    defn: DocumentTypeDefinition,
    *,
    invoice: Invoice,
    ocr: OcrArtifact,
) -> bool:
    classifier = defn.classifier
    if not classifier.enabled or not classifier_has_actionable_conditions(classifier.root):
        return True
    ctx = build_classifier_context_from_ocr(invoice=invoice, ocr=ocr)
    return eval_condition_group_generic(
        classifier.root,
        field_resolver=lambda field, _ctx=ctx: _document_field(_ctx, field),
    )
