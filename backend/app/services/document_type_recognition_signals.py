"""Detect recognition signals from parsed samples (aligns with frontend RecognitionSignalId)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.invoice import Invoice
from app.services.document_type_rule_engine import (
    DocumentClassifierContext,
    build_document_classifier_context,
)
from app.services.invoice_data import InvoiceData
from app.services.purchase_document_service import (
    _attachment_suggests_grn,
    _attachment_suggests_po,
)

RecognitionSignalId = str

_FILENAME_PATTERNS: list[tuple[RecognitionSignalId, re.Pattern[str]]] = [
    ("filename_invoice", re.compile(r"(?i)(?:^|[-_/])(?:inv|invoice|tax[_-]?inv)(?:[-_.]|$)")),
    ("filename_po", re.compile(r"(^|[-_/])po([-_.]|$)|purchase[_-]?order", re.I)),
    ("filename_grn", re.compile(r"(^|[-_/])grn([-_.]|$)|goods[_-]?receipt|delivery[_-]?note", re.I)),
    ("filename_contract", re.compile(r"contract|agreement|sow|msa", re.I)),
    ("filename_credit_note", re.compile(r"credit[_-]?note", re.I)),
    ("filename_debit_note", re.compile(r"debit[_-]?note", re.I)),
    ("filename_proforma", re.compile(r"pro[\s-]?forma|advance", re.I)),
    ("filename_quote", re.compile(r"quote|quotation|estimate|proposal", re.I)),
    ("filename_claim", re.compile(r"claim|expense|reimburse", re.I)),
    ("filename_bank_change", re.compile(r"bank[_-]?detail|change[_-]?of[_-]?bank", re.I)),
    ("filename_tax_notice", re.compile(r"ato|tax[_-]?notice|compliance[_-]?notice", re.I)),
]

_TEXT_PATTERNS: list[tuple[RecognitionSignalId, re.Pattern[str]]] = [
    ("text_invoice", re.compile(r"(?i)\b(tax\s+invoice|commercial\s+invoice)\b")),
    ("text_po", re.compile(r"(?i)purchase\s+order")),
    ("text_grn", re.compile(r"(?i)(goods\s+receipt|delivery\s+(note|docket)|\bGRN\b)")),
    ("text_contract", re.compile(r"(?i)(\bcontract\b|master service agreement|docusign)")),
    ("text_terms", re.compile(r"(?i)terms and conditions")),
    ("text_governing_law", re.compile(r"(?i)governing law")),
    ("text_signed_behalf", re.compile(r"(?i)signed for and on behalf of|executed by")),
    ("text_credit_note", re.compile(r"(?i)credit\s+note")),
    ("text_debit_note", re.compile(r"(?i)debit\s+note")),
    ("text_proforma", re.compile(r"(?i)pro[\s-]?forma")),
    ("text_quote", re.compile(r"(?i)\b(quote|quotation|estimate|proposal)\b")),
    ("text_claim", re.compile(r"(?i)(expense claim|reimbursement|employee expense)")),
    ("text_bank_change", re.compile(r"(?i)(bank\s+detail|change of bank)")),
    ("text_tax_notice", re.compile(r"(?i)(ato|tax office|compliance notice)")),
]


@dataclass(frozen=True)
class SampleSignalProfile:
    filename: str
    signals: frozenset[RecognitionSignalId]
    extraction_fields: frozenset[str]
    document_heading: str | None


def _field_keys_from_sample(
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    ctx: DocumentClassifierContext,
) -> set[str]:
    from app.services.document_type_field_checks import field_is_present

    keys = (
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "subtotal",
        "gst",
        "total",
        "line_items",
        "bank_details",
        "cost_centre",
        "billing_address",
        "document_text",
        "document_heading",
        "attachment_name",
    )
    present: set[str] = set()
    for key in keys:
        if field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
            present.add(key)

    if (parsed.vendor or invoice.vendor or "").strip():
        present.add("vendor")
    if (parsed.abn or invoice.abn or "").strip():
        present.add("abn")
    if (parsed.invoice_no or invoice.invoice_no or "").strip():
        present.add("invoice_no")
    if parsed.invoice_date or invoice.invoice_date:
        present.add("invoice_date")
    if parsed.due_date or invoice.due_date:
        present.add("due_date")
    if (parsed.po_reference or invoice.po_reference or "").strip():
        present.add("po_reference")
    if parsed.subtotal is not None or invoice.subtotal is not None:
        present.add("subtotal")
    if parsed.gst is not None or invoice.gst is not None:
        present.add("gst")
    if parsed.total is not None or invoice.total is not None:
        present.add("total")
    if parsed.line_items:
        present.add("line_items")
    if (parsed.bank_bsb or invoice.bank_bsb or parsed.bank_account or invoice.bank_account):
        present.add("bank_details")
    if (parsed.cost_centre or invoice.cost_centre or "").strip():
        present.add("cost_centre")
    if (invoice.billing_address or "").strip():
        present.add("billing_address")
    if ctx.document_text.strip():
        present.add("document_text")
    if (parsed.document_heading or ctx.document_heading or "").strip():
        present.add("document_heading")
    if ctx.attachment_name.strip():
        present.add("attachment_name")
    return present


def detect_recognition_signals(
    *,
    filename: str,
    invoice: Invoice,
    parsed: InvoiceData,
) -> SampleSignalProfile:
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    signals: set[RecognitionSignalId] = set()
    name = (filename or "").strip()

    if ctx.has_heading_po == "true":
        signals.add("heading_po")
    if ctx.has_heading_grn == "true":
        signals.add("heading_grn")
    if ctx.has_heading_contract == "true":
        signals.add("heading_contract")
    if ctx.has_heading_invoice == "true":
        signals.add("heading_invoice")
    if ctx.has_po_reference == "true":
        signals.add("has_po_reference")
    if ctx.has_invoice_no == "true":
        signals.add("has_invoice_number")
    if ctx.has_total == "true":
        signals.add("has_total_amount")

    body = ctx.document_text or ""
    for signal_id, pattern in _FILENAME_PATTERNS:
        if name and pattern.search(name):
            signals.add(signal_id)
    for signal_id, pattern in _TEXT_PATTERNS:
        if body and pattern.search(body):
            signals.add(signal_id)

    if name and _attachment_suggests_po(name):
        signals.add("filename_po")
    if name and _attachment_suggests_grn(name):
        signals.add("filename_grn")

    subject = (invoice.email_subject or "").strip()
    if subject and re.search(r"(?i)\binvoice\b", subject):
        signals.add("text_invoice")

    extraction = _field_keys_from_sample(invoice=invoice, parsed=parsed, ctx=ctx)
    heading = (parsed.document_heading or ctx.document_heading or "").strip() or None
    return SampleSignalProfile(
        filename=name,
        signals=frozenset(signals),
        extraction_fields=frozenset(extraction),
        document_heading=heading,
    )


def infer_classifier_layout(
    signals: frozenset[RecognitionSignalId],
    *,
    purchase_bundle_role: str = "",
    for_sample_analysis: bool = False,
) -> str:
    role = (purchase_bundle_role or "").strip().lower()
    if role in {"po", "grn"}:
        return "supporting_doc"
    if for_sample_analysis:
        # Sample-derived rules must tolerate variation across uploads of the same type.
        return "any_signal"
    if {"has_po_reference", "has_invoice_number", "has_total_amount"}.issubset(signals):
        return "all_signals"
    return "any_signal"


def merge_signals_for_classifier_profiles(
    profiles: list[SampleSignalProfile],
    *,
    purchase_bundle_role: str = "",
) -> tuple[frozenset[RecognitionSignalId], str]:
    """
    Build classifier signals + layout from one or more parsed samples.

    Multi-sample: prefer signals present on every file (intersection). If none overlap,
    fall back to union with OR matching so variants of the same type still route.
    """
    role = (purchase_bundle_role or "").strip().lower()
    if not profiles:
        return frozenset(), "any_signal"

    union: set[RecognitionSignalId] = set()
    for profile in profiles:
        union.update(profile.signals)

    if role in {"po", "grn"}:
        return frozenset(union), "supporting_doc"

    if len(profiles) == 1:
        return frozenset(union), "any_signal"

    per_file = [set(profile.signals) for profile in profiles]
    common = set.intersection(*per_file) if per_file else set()
    if common:
        return frozenset(common), "any_signal"
    return frozenset(union), "any_signal"


def infer_playbook_profile(signals: frozenset[RecognitionSignalId]) -> str:
    if signals & {"heading_grn", "text_grn", "filename_grn"}:
        return "supporting"
    if signals & {"heading_po", "text_po", "filename_po"}:
        if "has_invoice_number" not in signals:
            return "supporting"
    if signals & {"text_credit_note", "filename_credit_note"}:
        return "credit_adjustment"
    if signals & {"text_debit_note", "filename_debit_note"}:
        return "debit_note"
    if signals & {"text_proforma", "filename_proforma"}:
        return "pre_transactional"
    if signals & {"text_claim", "filename_claim"}:
        return "employee_claim"
    if signals & {"text_bank_change", "filename_bank_change"}:
        return "master_data"
    if signals & {"text_quote", "filename_quote"}:
        return "non_actionable"
    if signals & {"text_tax_notice", "filename_tax_notice"}:
        return "compliance_route"
    if signals & {"heading_contract", "text_contract", "text_governing_law", "filename_contract"}:
        return "supporting"
    if {"has_po_reference", "has_invoice_number", "has_total_amount"}.issubset(signals):
        return "po_goods"
    if "has_invoice_number" in signals and "has_po_reference" not in signals:
        return "direct_expense"
    return "standard_transactional"


def infer_purchase_bundle_role(signals: frozenset[RecognitionSignalId]) -> str:
    if signals & {"heading_grn", "text_grn", "filename_grn"}:
        return "grn"
    if signals & {"heading_po", "text_po", "filename_po"}:
        if "has_invoice_number" not in signals:
            return "po"
    return ""


def infer_absent_fields(signals: frozenset[RecognitionSignalId]) -> list[str]:
    absent: list[str] = []
    if signals & {"heading_po", "text_po", "filename_po", "heading_grn", "text_grn", "filename_grn"}:
        absent.append("invoice_no")
    if signals & {"text_quote", "filename_quote"}:
        absent.extend(["invoice_no", "total"])
    return list(dict.fromkeys(absent))


def infer_document_metadata(playbook: str, *, bundle_role: str = "") -> tuple[str, str, str]:
    """Return (klass, posting, route_target) from playbook profile."""
    from app.services.document_type_catalog import (
        ROUTE_EXPENSES,
        ROUTE_PURCHASE,
        ROUTE_TEAM,
        ROUTE_VAULT,
    )

    role = (bundle_role or "").strip().lower()
    if role in {"po", "grn"}:
        return "Supporting", "No", ROUTE_PURCHASE

    mapping: dict[str, tuple[str, str, str]] = {
        "po_goods": ("Transactional", "Yes", ROUTE_PURCHASE),
        "po_services": ("Transactional", "Yes", ROUTE_PURCHASE),
        "direct_expense": ("Transactional", "Yes", ROUTE_EXPENSES),
        "credit_adjustment": ("Transactional", "Yes", ROUTE_PURCHASE),
        "debit_note": ("Transactional", "Yes", ROUTE_PURCHASE),
        "pre_transactional": ("Pre-transactional", "Conditional", ROUTE_VAULT),
        "employee_claim": ("Transactional", "Yes", ROUTE_TEAM),
        "freight_logistics": ("Transactional", "Yes", ROUTE_PURCHASE),
        "intercompany": ("Transactional", "Yes", ROUTE_PURCHASE),
        "import_dossier": ("Transactional", "Yes", ROUTE_PURCHASE),
        "reconciliation": ("Reconciliation", "No", ROUTE_VAULT),
        "supporting": ("Supporting", "No", ROUTE_VAULT),
        "informational": ("Informational", "No", ROUTE_VAULT),
        "master_data": ("Master-data", "No", ROUTE_VAULT),
        "non_actionable": ("Non-actionable", "No", ROUTE_VAULT),
        "compliance_route": ("Compliance", "No", ROUTE_VAULT),
        "standard_transactional": ("Transactional", "Yes", ROUTE_PURCHASE),
    }
    return mapping.get(playbook, ("Transactional", "Yes", ROUTE_VAULT))


def suggest_bundle_members(playbook: str) -> tuple[list[str], list[str]]:
    if playbook == "po_goods":
        return ["DT-02", "DT-03"], ["Packing list", "Quality certificate"]
    if playbook == "po_services":
        return ["DT-02"], ["Service entry sheet / timesheet"]
    if playbook == "import_dossier":
        return ["DT-27", "DT-30"], ["Commercial invoice", "Bill of lading"]
    return [], []


def suggest_title_from_heading(heading: str | None) -> tuple[str | None, str | None]:
    if not heading:
        return None, None
    cleaned = heading.strip()
    if not cleaned:
        return None, None
    title = cleaned.title() if cleaned.isupper() else cleaned
    short = title if len(title) <= 48 else title[:45].rstrip() + "..."
    return title, short


def suggest_one_line(
    signals: frozenset[RecognitionSignalId],
    *,
    headings: list[str],
) -> str:
    if signals & {"heading_grn", "text_grn", "filename_grn"}:
        return "Goods receipt or delivery note linked to a purchase order."
    if signals & {"heading_po", "text_po", "filename_po"} and "has_invoice_number" not in signals:
        return "Purchase order copy used as a supporting bundle document."
    if signals & {"text_credit_note", "filename_credit_note"}:
        return "Credit or adjustment note referencing an original invoice."
    if signals & {"heading_contract", "text_contract", "text_governing_law"}:
        return "Contract or agreement with legal terms and party obligations."
    if {"has_po_reference", "has_invoice_number", "has_total_amount"}.issubset(signals):
        return "Commercial invoice with PO reference for purchase matching."
    if "has_invoice_number" in signals:
        return "Vendor invoice captured for accounts payable processing."
    label = headings[0] if headings else ""
    if label:
        return f"Document type identified from sample heading: {label}."
    return "Document type inferred from uploaded sample files."
